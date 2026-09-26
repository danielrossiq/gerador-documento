"""Campos do gerador: criação, edição, opções, ordenação e exclusão (com efeito no documento)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, field_validator
from pydantic import Field as PField
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.deps import Ctx
from app.core.errors import Conflict, LimitExceeded, NotFound, ValidationFailed
from app.db.models import Field, FieldOption, TemplateBlock, TemplateVersion
from app.docx_engine.inline import inline_text
from app.docx_engine.nodes import unwrap_field
from app.modules.audit import service as audit
from app.modules.fields.normalize import normalize_value
from app.modules.fields.types import (
    FIELD_TYPES,
    NAME_RE,
    RESERVED_NAMES,
    FieldDef,
    OptionDef,
    option_value_from_label,
    to_snake_case,
    unique_name,
)
from app.modules.templates import core

MAX_OPTIONS = 500


class OptionIn(BaseModel):
    label: str = PField(min_length=1, max_length=200)
    value: str | None = PField(default=None, max_length=200)

    @field_validator("label")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("O rótulo da opção não pode ser vazio.")
        return v


class FieldIn(BaseModel):
    label: str = PField(min_length=1, max_length=200)
    name: str | None = PField(default=None, max_length=64)
    type: str
    description: str | None = PField(default=None, max_length=500)
    required: bool = False
    default_value: Any = None
    example: str | None = PField(default=None, max_length=300)
    mask: str | None = PField(default=None, max_length=100)
    group_name: str | None = PField(default=None, max_length=100)
    include_in_batch: bool = True
    config: dict[str, Any] | None = None
    options: list[OptionIn] | None = None

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        if v not in FIELD_TYPES:
            raise ValueError(f"Tipo de campo inválido: {v}")
        return v


class FieldPatch(BaseModel):
    label: str | None = PField(default=None, min_length=1, max_length=200)
    name: str | None = PField(default=None, max_length=64)
    type: str | None = None
    description: str | None = PField(default=None, max_length=500)
    required: bool | None = None
    default_value: Any = PField(default=None)
    example: str | None = PField(default=None, max_length=300)
    mask: str | None = PField(default=None, max_length=100)
    group_name: str | None = PField(default=None, max_length=100)
    include_in_batch: bool | None = None
    config: dict[str, Any] | None = None

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v: str | None) -> str | None:
        if v is not None and v not in FIELD_TYPES:
            raise ValueError(f"Tipo de campo inválido: {v}")
        return v


ALLOWED_CONFIG_KEYS = {
    "decimals",
    "min",
    "max",
    "max_length",
    "date_format",
    "checked_text",
    "unchecked_text",
    "rows",
}


def clean_config(cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    if not cfg:
        return None
    out = {k: v for k, v in cfg.items() if k in ALLOWED_CONFIG_KEYS and v not in (None, "")}
    if "date_format" in out and out["date_format"] not in ("short", "long"):
        raise ValidationFailed("Formato de data inválido.", code="INVALID_CONFIG")
    return out or None


# ------------------------------------------------------------------ leitura


def fields_of_version(db: Session, version_id: uuid.UUID) -> list[Field]:
    return list(
        db.scalars(
            select(Field).where(Field.version_id == version_id).order_by(Field.position, Field.created_at)
        )
    )


def options_by_field(db: Session, field_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[FieldOption]]:
    out: dict[uuid.UUID, list[FieldOption]] = {fid: [] for fid in field_ids}
    if not field_ids:
        return out
    for o in db.scalars(
        select(FieldOption).where(FieldOption.field_id.in_(field_ids)).order_by(FieldOption.position)
    ):
        out[o.field_id].append(o)
    return out


def to_def(f: Field, options: list[FieldOption]) -> FieldDef:
    return FieldDef(
        id=str(f.id),
        name=f.name,
        label=f.label,
        type=f.type,
        required=f.required,
        default=f.default_value,
        options=tuple(OptionDef(o.label, o.value) for o in options),
        config=f.config or {},
        mask=f.mask,
        include_in_batch=f.include_in_batch,
        position=f.position,
        group=f.group_name,
        description=f.description,
        example=f.example,
    )


def field_defs(db: Session, version_id: uuid.UUID) -> list[FieldDef]:
    fields = fields_of_version(db, version_id)
    opts = options_by_field(db, [f.id for f in fields])
    return [to_def(f, opts[f.id]) for f in fields]


def field_out(f: Field, options: list[FieldOption], occurrences: int) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "name": f.name,
        "label": f.label,
        "type": f.type,
        "description": f.description,
        "required": f.required,
        "default_value": f.default_value,
        "example": f.example,
        "mask": f.mask,
        "group_name": f.group_name,
        "position": f.position,
        "include_in_batch": f.include_in_batch,
        "config": f.config or {},
        "options": [{"id": str(o.id), "label": o.label, "value": o.value} for o in options],
        "occurrences": occurrences,
        "missing_in_document": occurrences == 0,
    }


def list_out(db: Session, version: TemplateVersion) -> list[dict[str, Any]]:
    fields = fields_of_version(db, version.id)
    opts = options_by_field(db, [f.id for f in fields])
    counts = core.occurrence_counts(db, version.id)
    return [field_out(f, opts[f.id], counts.get(str(f.id), 0)) for f in fields]


def get_field_scoped(
    db: Session, workspace_id: uuid.UUID, field_id: uuid.UUID
) -> tuple[Field, TemplateVersion]:
    f = db.scalar(select(Field).where(Field.id == field_id, Field.workspace_id == workspace_id))
    if f is None:
        raise NotFound("Campo")
    return f, core.get_version(db, workspace_id, f.version_id)


# ------------------------------------------------------------------ escrita


def _validate_name(
    db: Session, version_id: uuid.UUID, name: str, *, exclude: uuid.UUID | None = None
) -> None:
    if not NAME_RE.match(name):
        raise ValidationFailed(
            "O nome técnico deve começar com letra minúscula e usar apenas a-z, 0-9 e _ (máx. 63).",
            code="INVALID_FIELD_NAME",
        )
    if name in RESERVED_NAMES:
        raise ValidationFailed(
            f"“{name}” é reservado para o nome do arquivo. Escolha outro nome técnico.",
            code="RESERVED_FIELD_NAME",
        )
    q = select(Field.id).where(Field.version_id == version_id, Field.name == name)
    if exclude:
        q = q.where(Field.id != exclude)
    if db.scalar(q):
        raise Conflict(f"Já existe um campo com o nome técnico “{name}”.", code="DUPLICATE_FIELD_NAME")


def normalize_options(items: list[OptionIn]) -> list[tuple[str, str]]:
    """[(label, value)] validando duplicatas por rótulo e por valor (sem diferenciar maiúsculas)."""
    if len(items) > MAX_OPTIONS:
        raise ValidationFailed(f"Limite de {MAX_OPTIONS} opções por lista.", code="TOO_MANY_OPTIONS")
    seen_labels: set[str] = set()
    seen_values: set[str] = set()
    out: list[tuple[str, str]] = []
    for it in items:
        label = it.label.strip()
        value = (it.value or "").strip() or option_value_from_label(label)
        if label.lower() in seen_labels:
            raise ValidationFailed(f"A opção “{label}” está duplicada.", code="DUPLICATE_OPTION")
        if value.lower() in seen_values:
            raise ValidationFailed(
                f"O valor interno “{value}” está duplicado (opção “{label}”).", code="DUPLICATE_OPTION"
            )
        seen_labels.add(label.lower())
        seen_values.add(value.lower())
        out.append((label, value))
    return out


def _check_default(fd: FieldDef) -> None:
    if fd.default in (None, ""):
        return
    if fd.type == "select":
        if not any(o.value == fd.default for o in fd.options):
            raise ValidationFailed(
                "O valor padrão precisa ser uma das opções da lista.", code="INVALID_DEFAULT"
            )
        return
    _, err = normalize_value(
        FieldDef(
            fd.id,
            fd.name,
            fd.label,
            fd.type,
            required=False,
            options=fd.options,
            config=fd.config,
            mask=fd.mask,
        ),
        fd.default,
    )
    if err:
        raise ValidationFailed(f"Valor padrão inválido: {err}", code="INVALID_DEFAULT")


def create_field(ctx: Ctx, generator_id: uuid.UUID, data: FieldIn, *, commit: bool = True) -> Field:
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    version = core.current_version(db, gen)
    if (db.scalar(select(func.count(Field.id)).where(Field.version_id == version.id)) or 0) >= ctx.limit(
        "max_fields_per_generator"
    ):
        raise LimitExceeded("Limite de campos por modelo atingido.", code="FIELD_LIMIT")
    existing = set(db.scalars(select(Field.name).where(Field.version_id == version.id)))
    name = data.name.strip() if data.name else unique_name(to_snake_case(data.label), existing)
    _validate_name(db, version.id, name)
    position = (db.scalar(select(func.max(Field.position)).where(Field.version_id == version.id)) or 0) + 1
    default = data.default_value
    opts = normalize_options(data.options or []) if data.type == "select" else []
    if data.type == "select" and default not in (None, ""):
        default = next((v for lb, v in opts if v == default or lb.lower() == str(default).lower()), default)
    f = Field(
        workspace_id=ctx.workspace_id,
        version_id=version.id,
        name=name,
        label=data.label.strip(),
        type=data.type,
        description=(data.description or "").strip() or None,
        required=data.required,
        default_value=default,
        example=(data.example or "").strip() or None,
        mask=(data.mask or "").strip() or None,
        group_name=(data.group_name or "").strip() or None,
        position=position,
        include_in_batch=data.include_in_batch,
        config=clean_config(data.config),
    )
    db.add(f)
    db.flush()
    for i, (lb, val) in enumerate(opts):
        db.add(FieldOption(workspace_id=ctx.workspace_id, field_id=f.id, label=lb, value=val, position=i))
    db.flush()
    _check_default(
        to_def(
            f,
            [
                FieldOption(label=lb, value=val, position=i, workspace_id=ctx.workspace_id, field_id=f.id)
                for i, (lb, val) in enumerate(opts)
            ],
        )
    )
    core.touch(version, gen)
    audit.record(
        db,
        "field.create",
        ctx=ctx,
        entity_type="field",
        entity_id=f.id,
        meta={"type": f.type, "generator_id": str(gen.id)},
    )
    if commit:
        db.commit()
    return f


def update_field(ctx: Ctx, field_id: uuid.UUID, data: FieldPatch) -> Field:
    db = ctx.db
    f, version = get_field_scoped(db, ctx.workspace_id, field_id)
    gen = core.get_generator(db, ctx.workspace_id, version.generator_id)
    patch = data.model_dump(exclude_unset=True)
    if "name" in patch and patch["name"] is not None:
        _validate_name(db, version.id, patch["name"].strip(), exclude=f.id)
        f.name = patch["name"].strip()
    if "label" in patch and patch["label"] is not None:
        f.label = patch["label"].strip()
    if "type" in patch and patch["type"] and patch["type"] != f.type:
        if f.type == "select":
            db.execute(delete(FieldOption).where(FieldOption.field_id == f.id))
        f.type = patch["type"]
        f.mask = None
        f.config = None
        f.default_value = None
    for attr, key in (
        ("description", "description"),
        ("example", "example"),
        ("mask", "mask"),
        ("group_name", "group_name"),
    ):
        if key in patch:
            setattr(f, attr, (patch[key] or "").strip() or None)
    for key in ("required", "include_in_batch"):
        if key in patch and patch[key] is not None:
            setattr(f, key, patch[key])
    if "config" in patch:
        f.config = clean_config(patch["config"])
    if "default_value" in patch:
        f.default_value = patch["default_value"]
    db.flush()
    opts = options_by_field(db, [f.id])[f.id]
    _check_default(to_def(f, opts))
    core.touch(version, gen)
    audit.record(db, "field.update", ctx=ctx, entity_type="field", entity_id=f.id)
    db.commit()
    return f


def replace_options(ctx: Ctx, field_id: uuid.UUID, items: list[OptionIn]) -> list[FieldOption]:
    db = ctx.db
    f, version = get_field_scoped(db, ctx.workspace_id, field_id)
    if f.type != "select":
        raise ValidationFailed("Só campos do tipo “Lista suspensa” têm opções.", code="NOT_A_SELECT")
    pairs = normalize_options(items)
    db.execute(delete(FieldOption).where(FieldOption.field_id == f.id))
    db.flush()
    out = []
    for i, (lb, val) in enumerate(pairs):
        o = FieldOption(workspace_id=ctx.workspace_id, field_id=f.id, label=lb, value=val, position=i)
        db.add(o)
        out.append(o)
    if f.default_value not in (None, "") and f.default_value not in {v for _, v in pairs}:
        f.default_value = None  # o padrão removido deixa de existir
    core.touch(version, core.get_generator(db, ctx.workspace_id, version.generator_id))
    audit.record(
        db, "field.options", ctx=ctx, entity_type="field", entity_id=f.id, meta={"count": len(pairs)}
    )
    db.commit()
    return out


def reorder_fields(ctx: Ctx, generator_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    version = core.current_version(db, gen)
    fields = {f.id: f for f in fields_of_version(db, version.id)}
    if set(ids) != set(fields) or len(ids) != len(set(ids)):
        raise ValidationFailed(
            "A lista de campos para ordenação está incompleta ou tem itens repetidos.", code="INVALID_ORDER"
        )
    for pos, fid in enumerate(ids, start=1):
        fields[fid].position = pos
    core.touch(version, gen)
    db.commit()


def delete_field(
    ctx: Ctx, field_id: uuid.UUID, occurrences: Literal["keep_text", "remove_text"]
) -> tuple[int, int]:
    """Remove o campo. `keep_text`: o texto original volta ao documento; `remove_text`: o trecho é apagado."""
    db = ctx.db
    f, version = get_field_scoped(db, ctx.workspace_id, field_id)
    gen = core.get_generator(db, ctx.workspace_id, version.generator_id)
    changed = 0
    for b in core.load_blocks(db, version.id):
        if b.kind != "paragraph" or not isinstance(b.content, list):
            continue
        new, n = unwrap_field(b.content, str(f.id), keep_text=occurrences == "keep_text")
        if n:
            b.content = new
            b.text = inline_text(new)
            changed += n
    db.delete(f)
    db.flush()
    core.recompute_occurrences(db, version)
    core.touch(version, gen, content=True)
    audit.record(
        db,
        "field.delete",
        ctx=ctx,
        entity_type="field",
        entity_id=field_id,
        meta={"occurrences": changed, "mode": occurrences},
    )
    db.commit()
    return changed, version.revision


__all__ = [
    "FieldIn",
    "FieldPatch",
    "OptionIn",
    "TemplateBlock",
    "create_field",
    "delete_field",
    "field_defs",
    "field_out",
    "list_out",
    "reorder_fields",
    "replace_options",
    "to_def",
    "update_field",
]
