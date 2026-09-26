"""Kit de documentos: agrupa geradores existentes que compartilham variáveis (nome, CPF, endereço…).

Preencher o formulário do kit uma vez cria um `GenerationJob` comum (kind="single") por documento membro —
mesma fila, retentativa, idempotência e watchdog dos jobs normais (nada de especial no runner/worker). O
status do kit e o pacote ZIP são sempre derivados desses jobs, nunca guardados à parte.
"""

from __future__ import annotations

import contextlib
import csv
import difflib
import hashlib
import io
import uuid
import zipfile
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, field_validator
from pydantic import Field as PField
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.adapters.ai import RoleClassifierUnavailable, get_role_classifier
from app.adapters.storage import StorageAdapter, get_storage
from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.errors import Conflict, LimitExceeded, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    DocumentGenerator,
    DocumentKit,
    DocumentKitItem,
    GeneratedFile,
    GenerationJob,
    KitField,
    KitFieldOption,
    KitRun,
    TemplateVersion,
    User,
)
from app.modules.audit import service as audit
from app.modules.fields import service as fields_service
from app.modules.fields.normalize import validate_row
from app.modules.fields.types import (
    FIELD_TYPES,
    NAME_RE,
    RESERVED_NAMES,
    FieldDef,
    OptionDef,
    normalize_key,
    to_snake_case,
    unique_name,
)
from app.modules.generation import filenames
from app.modules.generation import service as gen_service
from app.modules.kits.matching import (
    MemberFields,
    build_role_candidates,
    candidates_to_members,
    merge_suggestion_lists,
    suggest_kit_fields,
    suggest_kit_fields_by_role,
    unclustered_candidates,
)
from app.modules.templates import core as templates_core

log = get_logger(__name__)
SORTS = {
    "updated": DocumentKit.updated_at.desc(),
    "name": func.lower(DocumentKit.name).asc(),
    "created": DocumentKit.created_at.desc(),
}

# ------------------------------------------------------------------ CRUD do kit


class KitIn(BaseModel):
    name: str = PField(min_length=1, max_length=200)
    description: str | None = PField(default=None, max_length=500)


class KitPatch(BaseModel):
    name: str | None = PField(default=None, max_length=200)
    description: str | None = PField(default=None, max_length=500)
    filename_pattern: str | None = PField(default=None, max_length=200)


def get_kit(
    db: Session, workspace_id: uuid.UUID, kit_id: uuid.UUID, *, include_deleted: bool = False
) -> DocumentKit:
    q = select(DocumentKit).where(DocumentKit.id == kit_id, DocumentKit.workspace_id == workspace_id)
    if not include_deleted:
        q = q.where(DocumentKit.deleted_at.is_(None))
    kit = db.scalar(q)
    if kit is None:
        raise NotFound("Kit")
    return kit


def kit_out(db: Session, kit: DocumentKit) -> dict[str, Any]:
    n_items = db.scalar(select(func.count(DocumentKitItem.id)).where(DocumentKitItem.kit_id == kit.id)) or 0
    n_fields = db.scalar(select(func.count(KitField.id)).where(KitField.kit_id == kit.id)) or 0
    docs = (
        db.scalar(
            select(func.coalesce(func.sum(GenerationJob.succeeded_items), 0))
            .select_from(GenerationJob)
            .join(KitRun, KitRun.id == GenerationJob.kit_run_id)
            .where(KitRun.kit_id == kit.id)
        )
        or 0
    )
    return {
        "id": str(kit.id),
        "name": kit.name,
        "description": kit.description,
        "status": kit.status,
        "is_pinned": kit.is_pinned,
        "filename_pattern": kit.filename_pattern,
        "items_count": n_items,
        "fields_count": n_fields,
        "documents_generated": int(docs),
        "has_documents": n_items > 0,
        "created_at": kit.created_at.isoformat(),
        "updated_at": kit.updated_at.isoformat(),
        "archived_at": kit.archived_at.isoformat() if kit.archived_at else None,
    }


def list_kits(
    ctx: Ctx, *, q: str | None, status: str | None, page: int, page_size: int, sort: str
) -> dict[str, Any]:
    db = ctx.db
    cond = [DocumentKit.workspace_id == ctx.workspace_id, DocumentKit.deleted_at.is_(None)]
    if status == "archived":
        cond.append(DocumentKit.status == "archived")
    else:
        cond.append(DocumentKit.status != "archived")
    if q:
        like = f"%{q.strip().lower()}%"
        cond.append(
            or_(
                func.lower(DocumentKit.name).like(like),
                func.lower(func.coalesce(DocumentKit.description, "")).like(like),
            )
        )
    total = db.scalar(select(func.count(DocumentKit.id)).where(*cond)) or 0
    rows = db.scalars(
        select(DocumentKit)
        .where(*cond)
        .order_by(DocumentKit.is_pinned.desc(), SORTS.get(sort, SORTS["updated"]))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": [kit_out(db, k) for k in rows], "total": total, "page": page, "page_size": page_size}


def create_kit(ctx: Ctx, name: str, description: str | None) -> DocumentKit:
    db = ctx.db
    name = name.strip()
    if not name:
        raise ValidationFailed("Informe o nome do kit.", code="INVALID_NAME")
    count = (
        db.scalar(
            select(func.count(DocumentKit.id)).where(
                DocumentKit.workspace_id == ctx.workspace_id, DocumentKit.deleted_at.is_(None)
            )
        )
        or 0
    )
    if count >= ctx.limit("max_kits"):
        raise LimitExceeded("Limite de kits do seu plano atingido.", code="KIT_LIMIT")
    kit = DocumentKit(
        workspace_id=ctx.workspace_id,
        name=name[:200],
        description=(description or "").strip()[:500] or None,
        created_by=ctx.user.id,
    )
    db.add(kit)
    db.flush()
    audit.record(db, "kit.create", ctx=ctx, entity_type="kit", entity_id=kit.id)
    db.commit()
    return kit


def update_kit(ctx: Ctx, kit_id: uuid.UUID, patch: dict[str, Any]) -> DocumentKit:
    kit = get_kit(ctx.db, ctx.workspace_id, kit_id)
    if "name" in patch and patch["name"] is not None:
        if not patch["name"].strip():
            raise ValidationFailed("O nome não pode ficar vazio.", code="INVALID_NAME")
        kit.name = patch["name"].strip()[:200]
    if "description" in patch:
        kit.description = (patch["description"] or "").strip()[:500] or None
    if "filename_pattern" in patch and patch["filename_pattern"] is not None:
        pattern = patch["filename_pattern"].strip()
        if not pattern or len(pattern) > 200:
            raise ValidationFailed("Padrão de nome de arquivo inválido.", code="INVALID_FILENAME_PATTERN")
        kit.filename_pattern = pattern
    kit.updated_at = utcnow()
    audit.record(ctx.db, "kit.update", ctx=ctx, entity_type="kit", entity_id=kit.id)
    ctx.db.commit()
    return kit


def archive_kit(ctx: Ctx, kit_id: uuid.UUID, archived: bool) -> DocumentKit:
    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    kit.status = "archived" if archived else "active"
    kit.archived_at = utcnow() if archived else None
    kit.updated_at = utcnow()
    audit.record(
        db, "kit.archive" if archived else "kit.unarchive", ctx=ctx, entity_type="kit", entity_id=kit.id
    )
    db.commit()
    return kit


def pin_kit(ctx: Ctx, kit_id: uuid.UUID, pinned: bool) -> DocumentKit:
    kit = get_kit(ctx.db, ctx.workspace_id, kit_id)
    kit.is_pinned = pinned
    kit.updated_at = utcnow()
    audit.record(ctx.db, "kit.pin" if pinned else "kit.unpin", ctx=ctx, entity_type="kit", entity_id=kit.id)
    ctx.db.commit()
    return kit


def delete_kit(ctx: Ctx, kit_id: uuid.UUID) -> None:
    """Exclusão lógica: some das listas; o histórico de kit_runs já feitos é preservado."""
    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    running = (
        db.scalar(
            select(func.count(GenerationJob.id))
            .select_from(GenerationJob)
            .join(KitRun, KitRun.id == GenerationJob.kit_run_id)
            .where(KitRun.kit_id == kit.id, GenerationJob.status.in_(("queued", "processing")))
        )
        or 0
    )
    if running:
        raise Conflict(
            "Há gerações em andamento para este kit. Aguarde a conclusão para excluir.", code="JOBS_RUNNING"
        )
    kit.deleted_at = utcnow()
    kit.updated_at = utcnow()
    audit.record(db, "kit.delete", ctx=ctx, entity_type="kit", entity_id=kit.id)
    db.commit()


def dashboard(ctx: Ctx) -> dict[str, Any]:
    db = ctx.db
    total = (
        db.scalar(
            select(func.count(DocumentKit.id)).where(
                DocumentKit.workspace_id == ctx.workspace_id,
                DocumentKit.deleted_at.is_(None),
                DocumentKit.status != "archived",
            )
        )
        or 0
    )
    recent = db.scalars(
        select(DocumentKit)
        .where(
            DocumentKit.workspace_id == ctx.workspace_id,
            DocumentKit.deleted_at.is_(None),
            DocumentKit.status != "archived",
        )
        .order_by(DocumentKit.is_pinned.desc(), DocumentKit.updated_at.desc())
        .limit(6)
    ).all()
    return {"total_kits": total, "recent": [kit_out(db, k) for k in recent]}


# ------------------------------------------------------------------ membros (documentos do kit)


class _Member:
    __slots__ = ("defs", "generator", "item", "reason", "usable", "version")

    def __init__(
        self,
        item: DocumentKitItem,
        generator: DocumentGenerator | None,
        version: TemplateVersion | None,
        defs: list[FieldDef],
        usable: bool,
        reason: str | None,
    ) -> None:
        self.item, self.generator, self.version, self.defs = item, generator, version, defs
        self.usable, self.reason = usable, reason


def _load_members(db: Session, workspace_id: uuid.UUID, kit_id: uuid.UUID) -> list[_Member]:
    items = list(
        db.scalars(
            select(DocumentKitItem)
            .where(DocumentKitItem.kit_id == kit_id)
            .order_by(DocumentKitItem.position, DocumentKitItem.created_at)
        )
    )
    out: list[_Member] = []
    for it in items:
        gen = db.scalar(
            select(DocumentGenerator).where(
                DocumentGenerator.id == it.generator_id, DocumentGenerator.workspace_id == workspace_id
            )
        )
        if gen is None or gen.deleted_at is not None:
            out.append(_Member(it, None, None, [], False, "O documento foi excluído."))
            continue
        version = templates_core.current_version_or_none(db, gen)
        if version is None:
            out.append(
                _Member(it, gen, None, [], False, "O documento ainda não tem um arquivo .docx enviado.")
            )
            continue
        defs = fields_service.field_defs(db, version.id)
        out.append(_Member(it, gen, version, defs, True, None))
    return out


def _get_item(db: Session, workspace_id: uuid.UUID, kit_id: uuid.UUID, item_id: uuid.UUID) -> DocumentKitItem:
    it = db.scalar(
        select(DocumentKitItem).where(
            DocumentKitItem.id == item_id,
            DocumentKitItem.kit_id == kit_id,
            DocumentKitItem.workspace_id == workspace_id,
        )
    )
    if it is None:
        raise NotFound("Documento do kit")
    return it


def item_out(m: _Member) -> dict[str, Any]:
    mapped_member_fields = set((m.item.field_mapping or {}).values())
    extra = [d for d in m.defs if d.name not in mapped_member_fields]
    return {
        "id": str(m.item.id),
        "generator_id": str(m.item.generator_id),
        "generator_name": m.generator.name if m.generator else "(removido)",
        "position": m.item.position,
        "usable": m.usable,
        "reason": m.reason,
        "fields": [{"name": d.name, "label": d.label, "type": d.type, "required": d.required} for d in m.defs]
        if m.usable
        else [],
        "field_mapping": dict(m.item.field_mapping or {}),
        "extra_field_names": [d.name for d in extra] if m.usable else [],
    }


def list_items(ctx: Ctx, kit_id: uuid.UUID) -> list[dict[str, Any]]:
    get_kit(ctx.db, ctx.workspace_id, kit_id)
    return [item_out(m) for m in _load_members(ctx.db, ctx.workspace_id, kit_id)]


def _suggest_mapping_for_new_member(kit_fields: list[KitField], defs: list[FieldDef]) -> dict[str, str]:
    by_norm: dict[str, str] = {}
    for d in defs:
        by_norm.setdefault((normalize_key(d.label), d.type), d.name)
        by_norm.setdefault((normalize_key(d.name), d.type), d.name)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for kf in kit_fields:
        candidates = {k: v for (k, t), v in by_norm.items() if t == kf.type}
        n = normalize_key(kf.label) or normalize_key(kf.name)
        pick = candidates.get(n)
        if pick is None and n:
            close = difflib.get_close_matches(n, list(candidates), n=1, cutoff=0.82)
            pick = candidates[close[0]] if close else None
        if pick and pick not in used:
            mapping[kf.name] = pick
            used.add(pick)
    return mapping


def add_item(ctx: Ctx, kit_id: uuid.UUID, generator_id: uuid.UUID) -> dict[str, Any]:
    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    gen = templates_core.get_generator(db, ctx.workspace_id, generator_id)
    version = templates_core.current_version_or_none(db, gen)
    if version is None:
        raise ValidationFailed(
            "Este modelo ainda não tem um documento .docx enviado.", code="GENERATOR_WITHOUT_TEMPLATE"
        )
    exists = db.scalar(
        select(DocumentKitItem.id).where(
            DocumentKitItem.kit_id == kit.id, DocumentKitItem.generator_id == gen.id
        )
    )
    if exists:
        raise Conflict("Este documento já está no kit.", code="ALREADY_IN_KIT")
    count = db.scalar(select(func.count(DocumentKitItem.id)).where(DocumentKitItem.kit_id == kit.id)) or 0
    if count >= ctx.limit("max_generators_per_kit"):
        raise LimitExceeded("Limite de documentos por kit atingido.", code="KIT_ITEMS_LIMIT")
    position = (
        db.scalar(select(func.max(DocumentKitItem.position)).where(DocumentKitItem.kit_id == kit.id)) or 0
    ) + 1

    existing_fields = list(db.scalars(select(KitField).where(KitField.kit_id == kit.id)))
    defs = fields_service.field_defs(db, version.id)
    mapping = _suggest_mapping_for_new_member(existing_fields, defs) if existing_fields else {}

    item = DocumentKitItem(
        workspace_id=ctx.workspace_id,
        kit_id=kit.id,
        generator_id=gen.id,
        position=position,
        field_mapping=mapping,
    )
    db.add(item)
    kit.updated_at = utcnow()
    audit.record(
        db, "kit.item_add", ctx=ctx, entity_type="kit", entity_id=kit.id, meta={"generator": str(gen.id)}
    )
    db.commit()
    members = _load_members(db, ctx.workspace_id, kit.id)
    return item_out(next(m for m in members if m.item.id == item.id))


def remove_item(ctx: Ctx, kit_id: uuid.UUID, item_id: uuid.UUID) -> None:
    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    item = _get_item(db, ctx.workspace_id, kit.id, item_id)
    db.delete(item)
    kit.updated_at = utcnow()
    audit.record(db, "kit.item_remove", ctx=ctx, entity_type="kit", entity_id=kit.id)
    db.commit()


class ItemMappingIn(BaseModel):
    mapping: dict[str, str | None]  # nome do campo do kit -> nome do campo do gerador (ou null)


def set_item_mapping(ctx: Ctx, kit_id: uuid.UUID, item_id: uuid.UUID, body: ItemMappingIn) -> dict[str, Any]:
    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    item = _get_item(db, ctx.workspace_id, kit.id, item_id)
    kit_fields = {f.name: f for f in db.scalars(select(KitField).where(KitField.kit_id == kit.id))}
    gen = templates_core.get_generator(db, ctx.workspace_id, item.generator_id)
    defs_by_name = {
        d.name: d for d in fields_service.field_defs(db, templates_core.current_version(db, gen).id)
    }
    mapping: dict[str, str] = {}
    for kf_name, member_field in body.mapping.items():
        if kf_name not in kit_fields:
            raise ValidationFailed(f"Campo do kit desconhecido: {kf_name}.", code="UNKNOWN_KIT_FIELD")
        if member_field is None:
            continue
        target = defs_by_name.get(member_field)
        if target is None:
            raise ValidationFailed(
                f"Campo “{member_field}” não existe neste documento.", code="UNKNOWN_FIELD"
            )
        if target.type != kit_fields[kf_name].type:
            raise ValidationFailed(
                f"“{kit_fields[kf_name].label}” ({kit_fields[kf_name].type}) não combina com "
                f"“{target.label}” ({target.type}). Os tipos precisam ser iguais.",
                code="TYPE_MISMATCH",
            )
        mapping[kf_name] = member_field
    item.field_mapping = mapping
    kit.updated_at = utcnow()
    audit.record(db, "kit.mapping_update", ctx=ctx, entity_type="kit", entity_id=kit.id)
    db.commit()
    members = _load_members(db, ctx.workspace_id, kit.id)
    return item_out(next(m for m in members if m.item.id == item.id))


# ------------------------------------------------------------------ campos do kit


class KitFieldIn(BaseModel):
    label: str = PField(min_length=1, max_length=200)
    name: str | None = PField(default=None, max_length=64)
    type: str
    description: str | None = PField(default=None, max_length=500)
    required: bool = False
    default_value: Any = None
    example: str | None = PField(default=None, max_length=300)
    mask: str | None = PField(default=None, max_length=100)
    config: dict[str, Any] | None = None
    options: list[fields_service.OptionIn] | None = None

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        if v not in FIELD_TYPES:
            raise ValueError(f"Tipo de campo inválido: {v}")
        return v


class KitFieldPatch(BaseModel):
    label: str | None = PField(default=None, min_length=1, max_length=200)
    name: str | None = PField(default=None, max_length=64)
    description: str | None = PField(default=None, max_length=500)
    required: bool | None = None
    default_value: Any = PField(default=None)
    example: str | None = PField(default=None, max_length=300)
    mask: str | None = PField(default=None, max_length=100)
    config: dict[str, Any] | None = None


def kit_field_defs(db: Session, kit_id: uuid.UUID) -> list[FieldDef]:
    kfs = list(db.scalars(select(KitField).where(KitField.kit_id == kit_id).order_by(KitField.position)))
    ids = [kf.id for kf in kfs]
    opts: dict[uuid.UUID, list[KitFieldOption]] = {i: [] for i in ids}
    if ids:
        for o in db.scalars(
            select(KitFieldOption)
            .where(KitFieldOption.kit_field_id.in_(ids))
            .order_by(KitFieldOption.position)
        ):
            opts[o.kit_field_id].append(o)
    return [
        FieldDef(
            id=str(kf.id),
            name=kf.name,
            label=kf.label,
            type=kf.type,
            required=kf.required,
            default=kf.default_value,
            options=tuple(OptionDef(o.label, o.value) for o in opts[kf.id]),
            config=kf.config or {},
            mask=kf.mask,
            position=kf.position,
            description=kf.description,
            example=kf.example,
        )
        for kf in kfs
    ]


def options_by_kit_field(db: Session, field_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[KitFieldOption]]:
    out: dict[uuid.UUID, list[KitFieldOption]] = {i: [] for i in field_ids}
    if not field_ids:
        return out
    for o in db.scalars(
        select(KitFieldOption)
        .where(KitFieldOption.kit_field_id.in_(field_ids))
        .order_by(KitFieldOption.position)
    ):
        out[o.kit_field_id].append(o)
    return out


def list_kit_fields_out(db: Session, kit_id: uuid.UUID) -> list[dict[str, Any]]:
    kfs = list(db.scalars(select(KitField).where(KitField.kit_id == kit_id).order_by(KitField.position)))
    opts = options_by_kit_field(db, [kf.id for kf in kfs])
    return [kit_field_out(kf, opts[kf.id]) for kf in kfs]


def kit_field_out(kf: KitField, options: list[KitFieldOption]) -> dict[str, Any]:
    return {
        "id": str(kf.id),
        "name": kf.name,
        "label": kf.label,
        "type": kf.type,
        "description": kf.description,
        "required": kf.required,
        "default_value": kf.default_value,
        "example": kf.example,
        "mask": kf.mask,
        "position": kf.position,
        "config": kf.config or {},
        "options": [{"id": str(o.id), "label": o.label, "value": o.value} for o in options],
    }


def _validate_kit_field_name(
    db: Session, kit_id: uuid.UUID, name: str, *, exclude: uuid.UUID | None = None
) -> None:
    if not NAME_RE.match(name):
        raise ValidationFailed(
            "O nome técnico deve começar com letra minúscula e usar apenas a-z, 0-9 e _ (máx. 63).",
            code="INVALID_FIELD_NAME",
        )
    if name in RESERVED_NAMES:
        raise ValidationFailed(
            f"“{name}” é reservado. Escolha outro nome técnico.", code="RESERVED_FIELD_NAME"
        )
    q = select(KitField.id).where(KitField.kit_id == kit_id, KitField.name == name)
    if exclude:
        q = q.where(KitField.id != exclude)
    if db.scalar(q):
        raise Conflict(f"Já existe um campo do kit com o nome técnico “{name}”.", code="DUPLICATE_FIELD_NAME")


def create_kit_field(ctx: Ctx, kit_id: uuid.UUID, data: KitFieldIn) -> KitField:
    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    count = db.scalar(select(func.count(KitField.id)).where(KitField.kit_id == kit.id)) or 0
    if count >= ctx.limit("max_kit_fields"):
        raise LimitExceeded("Limite de campos do kit atingido.", code="KIT_FIELD_LIMIT")
    existing = set(db.scalars(select(KitField.name).where(KitField.kit_id == kit.id)))
    name = data.name.strip() if data.name else unique_name(to_snake_case(data.label), existing)
    _validate_kit_field_name(db, kit.id, name)
    position = (db.scalar(select(func.max(KitField.position)).where(KitField.kit_id == kit.id)) or 0) + 1
    opts = fields_service.normalize_options(data.options or []) if data.type == "select" else []
    default = data.default_value
    if data.type == "select" and default not in (None, ""):
        default = next((v for lb, v in opts if v == default or lb.lower() == str(default).lower()), default)
    kf = KitField(
        workspace_id=ctx.workspace_id,
        kit_id=kit.id,
        name=name,
        label=data.label.strip(),
        type=data.type,
        description=(data.description or "").strip() or None,
        required=data.required,
        default_value=default,
        example=(data.example or "").strip() or None,
        mask=(data.mask or "").strip() or None,
        position=position,
        config=fields_service.clean_config(data.config),
    )
    db.add(kf)
    db.flush()
    for i, (lb, val) in enumerate(opts):
        db.add(
            KitFieldOption(workspace_id=ctx.workspace_id, kit_field_id=kf.id, label=lb, value=val, position=i)
        )
    kit.updated_at = utcnow()
    audit.record(db, "kit.field_create", ctx=ctx, entity_type="kit", entity_id=kit.id, meta={"type": kf.type})
    db.commit()
    return kf


def update_kit_field(ctx: Ctx, field_id: uuid.UUID, data: KitFieldPatch) -> KitField:
    db = ctx.db
    kf = db.scalar(select(KitField).where(KitField.id == field_id, KitField.workspace_id == ctx.workspace_id))
    if kf is None:
        raise NotFound("Campo do kit")
    patch = data.model_dump(exclude_unset=True)
    if "name" in patch and patch["name"] is not None:
        _validate_kit_field_name(db, kf.kit_id, patch["name"].strip(), exclude=kf.id)
        kf.name = patch["name"].strip()
    if "label" in patch and patch["label"] is not None:
        kf.label = patch["label"].strip()
    for attr in ("description", "example", "mask"):
        if attr in patch:
            setattr(kf, attr, (patch[attr] or "").strip() or None)
    if "required" in patch and patch["required"] is not None:
        kf.required = patch["required"]
    if "config" in patch:
        kf.config = fields_service.clean_config(patch["config"])
    if "default_value" in patch:
        kf.default_value = patch["default_value"]
    kit = get_kit(db, ctx.workspace_id, kf.kit_id)
    kit.updated_at = utcnow()
    audit.record(db, "kit.field_update", ctx=ctx, entity_type="kit", entity_id=kf.kit_id)
    db.commit()
    return kf


def replace_kit_field_options(
    ctx: Ctx, field_id: uuid.UUID, items: list[fields_service.OptionIn]
) -> list[KitFieldOption]:
    db = ctx.db
    kf = db.scalar(select(KitField).where(KitField.id == field_id, KitField.workspace_id == ctx.workspace_id))
    if kf is None:
        raise NotFound("Campo do kit")
    if kf.type != "select":
        raise ValidationFailed("Só campos do tipo “Lista suspensa” têm opções.", code="NOT_A_SELECT")
    pairs = fields_service.normalize_options(items)
    db.execute(delete(KitFieldOption).where(KitFieldOption.kit_field_id == kf.id))
    db.flush()
    out = []
    for i, (lb, val) in enumerate(pairs):
        o = KitFieldOption(workspace_id=ctx.workspace_id, kit_field_id=kf.id, label=lb, value=val, position=i)
        db.add(o)
        out.append(o)
    if kf.default_value not in (None, "") and kf.default_value not in {v for _, v in pairs}:
        kf.default_value = None
    audit.record(
        db, "kit.field_options", ctx=ctx, entity_type="kit", entity_id=kf.kit_id, meta={"count": len(pairs)}
    )
    db.commit()
    return out


def delete_kit_field(ctx: Ctx, field_id: uuid.UUID) -> None:
    db = ctx.db
    kf = db.scalar(select(KitField).where(KitField.id == field_id, KitField.workspace_id == ctx.workspace_id))
    if kf is None:
        raise NotFound("Campo do kit")
    kit = get_kit(db, ctx.workspace_id, kf.kit_id)
    for item in db.scalars(select(DocumentKitItem).where(DocumentKitItem.kit_id == kit.id)):
        mapping = dict(item.field_mapping or {})
        if mapping.pop(kf.name, None) is not None:
            item.field_mapping = mapping
    db.delete(kf)
    kit.updated_at = utcnow()
    audit.record(db, "kit.field_delete", ctx=ctx, entity_type="kit", entity_id=kit.id)
    db.commit()


def auto_detect(ctx: Ctx, kit_id: uuid.UUID) -> dict[str, Any]:
    """Sugere e cria campos compartilhados a partir dos campos parecidos entre os documentos do kit."""
    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    members = [m for m in _load_members(db, ctx.workspace_id, kit.id) if m.usable]
    if len(members) < 2:
        raise ValidationFailed(
            "Adicione ao menos 2 documentos com modelo enviado para detectar campos em comum.",
            code="NOT_ENOUGH_MEMBERS",
        )
    member_fields = [
        MemberFields(str(m.item.generator_id), m.generator.name, tuple(m.defs))  # type: ignore[union-attr]
        for m in members
    ]
    provider = "similarity"
    classifier = get_role_classifier()
    if classifier is None:
        suggestions = suggest_kit_fields(member_fields)
    else:
        candidates = build_role_candidates(member_fields)
        try:
            answers = classifier.classify(candidates)
        except RoleClassifierUnavailable as exc:
            log.warning("kit_auto_detect_ia_indisponivel", extra={"kit_id": str(kit.id), "code": exc.code})
            suggestions = suggest_kit_fields(member_fields)
        else:
            # o que o agrupamento por papel não usou (baixa confiança OU confiante mas sem par no mesmo
            # papel) volta pra heurística por similaridade, senão um rótulo IDÊNTICO em dois documentos
            # poderia deixar de ser agrupado só por indecisão do classificador — pior que o D24 original
            # para o caso mais simples que existe (ver `unclustered_candidates`).
            role_suggestions = suggest_kit_fields_by_role(candidates, answers)
            leftover = unclustered_candidates(candidates, role_suggestions)
            leftover_suggestions = suggest_kit_fields(candidates_to_members(leftover)) if leftover else []
            suggestions = merge_suggestion_lists(role_suggestions, leftover_suggestions)
            provider = "typesafe"
    existing = list(db.scalars(select(KitField).where(KitField.kit_id == kit.id)))
    existing_by_key = {(normalize_key(f.label), f.type): f for f in existing}
    existing_names = {f.name for f in existing}
    items_by_gen = {str(m.item.generator_id): m.item for m in members}

    created, updated = 0, 0
    for sug in suggestions:
        key = (normalize_key(sug.label), sug.type)
        kf = existing_by_key.get(key)
        if kf is None:
            name = unique_name(sug.name, existing_names)
            existing_names.add(name)
            kf = KitField(
                workspace_id=ctx.workspace_id,
                kit_id=kit.id,
                name=name,
                label=sug.label,
                type=sug.type,
                required=sug.required,
                mask=sug.mask,
                example=sug.example,
                config=sug.config or None,
                position=(
                    db.scalar(select(func.max(KitField.position)).where(KitField.kit_id == kit.id)) or 0
                )
                + 1,
            )
            db.add(kf)
            db.flush()
            existing_by_key[key] = kf
            created += 1
        else:
            updated += 1
        for gid, member_field_name in sug.mapping.items():
            item = items_by_gen.get(gid)
            if item is None:
                continue
            mapping = dict(item.field_mapping or {})
            mapping[kf.name] = member_field_name
            item.field_mapping = mapping
    kit.updated_at = utcnow()
    audit.record(
        db,
        "kit.auto_detect",
        ctx=ctx,
        entity_type="kit",
        entity_id=kit.id,
        meta={"created": created, "updated": updated, "provider": provider},
    )
    db.commit()
    return {
        "created_fields": created,
        "updated_fields": updated,
        "suggested": len(suggestions),
        "provider": provider,
    }


# ------------------------------------------------------------------ formulário


def kit_form(ctx: Ctx, kit_id: uuid.UUID) -> dict[str, Any]:
    from app.adapters.pdf import pdf_available

    db = ctx.db
    kit = get_kit(db, ctx.workspace_id, kit_id)
    kfs = list(db.scalars(select(KitField).where(KitField.kit_id == kit.id).order_by(KitField.position)))
    opts = {kf.id: [] for kf in kfs}
    if kfs:
        for o in db.scalars(
            select(KitFieldOption)
            .where(KitFieldOption.kit_field_id.in_([kf.id for kf in kfs]))
            .order_by(KitFieldOption.position)
        ):
            opts[o.kit_field_id].append(o)
    members = _load_members(db, ctx.workspace_id, kit.id)
    warnings = [
        f"“{m.generator.name if m.generator else 'Documento removido'}”: {m.reason}"
        for m in members
        if not m.usable
    ]
    return {
        "kit": kit_out(db, kit),
        "fields": [kit_field_out(kf, opts[kf.id]) for kf in kfs],
        "members": [item_out(m) for m in members],
        "pdf_available": pdf_available(),
        "warnings": warnings,
    }


# ------------------------------------------------------------------ geração (kit_runs)


Format = Literal["docx", "pdf", "both"]


class KitRunIn(BaseModel):
    values: dict[str, Any] = PField(default_factory=dict)  # campos compartilhados do kit
    member_values: dict[str, dict[str, Any]] = PField(
        default_factory=dict
    )  # generator_id -> campos só daquele documento
    format: Format = "docx"
    filename_pattern: str | None = PField(default=None, max_length=200)
    idempotency_key: str | None = PField(default=None, max_length=120)


def _row_for_member(
    kit_defs: list[FieldDef], mapping: dict[str, str], values: dict[str, Any], member_values: dict[str, Any]
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for kf in kit_defs:
        member_field = mapping.get(kf.name)
        if member_field:
            row[member_field] = values.get(kf.name)
    row.update(member_values or {})
    return row


def _existing_run_by_key(ctx: Ctx, key: str | None) -> KitRun | None:
    if not key:
        return None
    return ctx.db.scalar(
        select(KitRun).where(KitRun.workspace_id == ctx.workspace_id, KitRun.idempotency_key == key)
    )


def create_kit_run(
    ctx: Ctx, kit_id: uuid.UUID, body: KitRunIn, header_key: str | None
) -> tuple[KitRun, bool]:
    from app.adapters.pdf import PdfConverterUnavailable, pdf_available

    db = ctx.db
    idem = header_key or body.idempotency_key
    if (existing := _existing_run_by_key(ctx, idem)) is not None:
        return existing, False
    kit = get_kit(db, ctx.workspace_id, kit_id)
    kit_defs = kit_field_defs(db, kit.id)
    members = [m for m in _load_members(db, ctx.workspace_id, kit.id) if m.usable]
    if not members:
        raise ValidationFailed(
            "Este kit não tem nenhum documento pronto para gerar.", code="NO_USABLE_MEMBERS"
        )
    if body.format in ("pdf", "both") and not pdf_available():
        raise PdfConverterUnavailable

    rows: dict[uuid.UUID, dict[str, Any]] = {}
    problems: list[dict[str, Any]] = []
    for m in members:
        mv = body.member_values.get(str(m.item.generator_id), {})
        row = _row_for_member(kit_defs, m.item.field_mapping or {}, body.values, mv)
        res = validate_row(m.defs, row)
        if not res.valid:
            labels = {d.name: d.label for d in m.defs}
            problems.append(
                {
                    "generator_id": str(m.item.generator_id),
                    "generator_name": m.generator.name if m.generator else "",
                    "errors": {labels.get(k, k): v for k, v in res.errors.items()},
                    "field_errors": dict(res.errors),
                }
            )
        rows[m.item.id] = row
    if problems:
        raise ValidationFailed(
            f"{len(problems)} documento(s) com campos inválidos. Corrija-os antes de gerar.",
            code="KIT_INVALID_VALUES",
            details={"problems": problems},
        )
    if gen_service._month_usage(ctx) + len(members) > ctx.limit("max_docs_per_month"):
        raise LimitExceeded("A cota mensal de documentos do seu plano seria excedida.", code="MONTHLY_QUOTA")

    # Registro informativo do que foi pedido; cada documento usa o próprio padrão de nome (`gen.filename_pattern`)
    # a menos que o usuário digite um padrão explícito no momento de gerar, que aí vale para todos igualmente.
    pattern_record = (body.filename_pattern or kit.filename_pattern or "{gerador}_{hoje}").strip()
    run = KitRun(
        workspace_id=ctx.workspace_id,
        kit_id=kit.id,
        idempotency_key=idem,
        output_format=body.format,
        filename_pattern=pattern_record,
        values_snapshot={"values": body.values, "member_values": body.member_values},
        total_members=len(members),
        created_by=ctx.user.id,
    )
    db.add(run)
    try:
        db.commit()
    except Exception:
        db.rollback()
        existing = _existing_run_by_key(ctx, idem)
        if existing is None:
            raise
        return existing, False
    db.refresh(run)

    member_pattern = body.filename_pattern.strip() if body.filename_pattern else None
    jobs: list[GenerationJob] = []
    for m in members:
        assert m.generator is not None
        member_idem = f"{idem}:{m.item.generator_id}" if idem else None
        try:
            job, _created = gen_service._create_job(
                ctx,
                m.generator,
                kind="single",
                fmt=body.format,
                rows=[rows[m.item.id]],
                only_valid=False,
                pattern=member_pattern,
                idem=member_idem,
                kit_run_id=run.id,
            )
            jobs.append(job)
        except Exception:
            # Isola a falha: os demais documentos do kit seguem gerando; este fica sem job (não aparece nos
            # "membros" do resultado do kit — o front mostra a diferença entre total_members e jobs recebidos).
            # Registrado (não silenciado) para investigação; erros esperados aqui são raros (a validação já
            # rodou acima) — normalmente só cota/fila em condição de corrida com outra requisição concorrente.
            log.exception(
                "kit_run_membro_falhou_ao_criar_job",
                extra={"kit_run_id": str(run.id), "generator_id": str(m.item.generator_id)},
            )
    audit.record(
        db,
        "kit.run_create",
        ctx=ctx,
        entity_type="kit_run",
        entity_id=run.id,
        meta={"kit": str(kit.id), "members": len(members), "jobs": len(jobs), "format": body.format},
    )
    db.commit()
    return run, True


def aggregate_status(statuses: list[str]) -> str:
    """Deriva o status do kit a partir do status de cada job membro. Nunca guardado — sempre calculado."""
    if not statuses:
        return "failed"  # nenhum job foi criado (todas as tentativas de criação falharam)
    s = set(statuses)
    if s & {"queued", "processing"}:
        return "processing"
    if s == {"succeeded"}:
        return "succeeded"
    if s == {"cancelled"}:
        return "cancelled"
    if s == {"failed"}:
        return "failed"
    return "partial"  # mistura de sucesso/falha/cancelado


def _csv_safe(v: str) -> str:
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _kit_report_csv(report_rows: list[tuple[str, str, str, str, str]]) -> bytes:
    out = io.StringIO(newline="")
    w = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["documento", "status", "arquivos", "codigo_erro", "mensagem"])
    for gen_name, status, files_str, code, msg in report_rows:
        w.writerow([gen_name, status, _csv_safe(files_str), code, _csv_safe(msg)])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")  # BOM: o Excel abre acentos corretamente


def build_bundle(ctx: Ctx, run: KitRun, jobs: list[GenerationJob]) -> None:
    """ZIP com os documentos do kit + relatório CSV. Idempotente: refaz do zero a cada chamada (mesmo padrão
    de `app.modules.generation.runner._build_artifacts`, usado para o ZIP de um lote comum)."""
    db, storage = ctx.db, get_storage()
    for old in db.scalars(select(GeneratedFile).where(GeneratedFile.kit_run_id == run.id)):
        with contextlib.suppress(Exception):
            storage.delete(old.storage_key)
        db.delete(old)
    db.flush()

    entries: list[tuple[str, bytes]] = []
    report_rows: list[tuple[str, str, str, str, str]] = []
    for job in jobs:
        gen = db.get(DocumentGenerator, job.generator_id)
        gen_name = gen.name if gen else "(removido)"
        files = list(
            db.scalars(
                select(GeneratedFile).where(
                    GeneratedFile.job_id == job.id,
                    GeneratedFile.kind.in_(("docx", "pdf")),
                    GeneratedFile.deleted_at.is_(None),
                )
            )
        )
        if job.status == "succeeded" and files:
            for f in files:
                entries.append((f.filename, storage.get(f.storage_key)))
            report_rows.append((gen_name, "gerado", "; ".join(sorted(f.filename for f in files)), "", ""))
        else:
            report_rows.append((gen_name, "falhou", "", job.error_code or "", job.error_message or ""))
    names = filenames.dedupe(
        [n for n, _ in entries]
    )  # nomes podem colidir entre documentos diferentes do kit
    report_bytes = _kit_report_csv(report_rows)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, (_, data) in zip(names, entries, strict=True):
            zf.writestr(name, data)
        zf.writestr("relatorio.csv", report_bytes)

    retention = get_settings().file_retention_days
    _store_kit_file(db, storage, run, "zip", f"kit_{str(run.id)[:8]}.zip", buf.getvalue(), retention)
    _store_kit_file(db, storage, run, "report", f"relatorio_{str(run.id)[:8]}.csv", report_bytes, retention)
    db.commit()


def _store_kit_file(
    db: Session,
    storage: StorageAdapter,
    run: KitRun,
    kind: str,
    filename: str,
    data: bytes,
    retention_days: int,
) -> GeneratedFile:
    key = f"w/{run.workspace_id}/kit/{run.id}/{uuid.uuid4().hex}.{'csv' if kind == 'report' else kind}"
    content_type = {"zip": "application/zip", "report": "text/csv; charset=utf-8"}[kind]
    storage.put(key, data, content_type)
    gf = GeneratedFile(
        workspace_id=run.workspace_id,
        kit_run_id=run.id,
        kind=kind,
        filename=filename[:255],
        storage_key=key,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        expires_at=utcnow() + timedelta(days=retention_days),
    )
    db.add(gf)
    return gf


def kit_run_out(ctx: Ctx, run: KitRun, *, with_files: bool = True) -> dict[str, Any]:
    db = ctx.db
    kit = db.get(DocumentKit, run.kit_id)
    author = db.get(User, run.created_by) if run.created_by else None
    jobs = list(
        db.scalars(
            select(GenerationJob).where(GenerationJob.kit_run_id == run.id).order_by(GenerationJob.created_at)
        )
    )
    statuses = [j.status for j in jobs]
    status = aggregate_status(statuses)
    if status not in ("queued", "processing") and jobs:
        has_bundle = db.scalar(
            select(func.count(GeneratedFile.id)).where(
                GeneratedFile.kit_run_id == run.id, GeneratedFile.kind == "zip"
            )
        )
        if not has_bundle:
            build_bundle(ctx, run, jobs)
    succeeded = sum(j.succeeded_items for j in jobs)
    failed = sum(j.failed_items for j in jobs) + max(0, run.total_members - len(jobs))
    out: dict[str, Any] = {
        "id": str(run.id),
        "kit_id": str(run.kit_id),
        "kit_name": kit.name if kit else "(removido)",
        "status": status,
        "output_format": run.output_format,
        "total_members": run.total_members,
        "succeeded_items": succeeded,
        "failed_items": failed,
        "created_at": run.created_at.isoformat(),
        "created_by": author.name if author else None,
        "members": [
            {"generator_id": str(j.generator_id), "job": gen_service.job_out(ctx, j, with_files=True)}
            for j in jobs
        ],
    }
    if with_files:
        files = list(
            db.scalars(
                select(GeneratedFile)
                .where(
                    GeneratedFile.kit_run_id == run.id,
                    GeneratedFile.deleted_at.is_(None),
                    GeneratedFile.kind.in_(("zip", "report")),
                )
                .order_by(GeneratedFile.created_at)
            )
        )
        out["files"] = [gen_service.file_out(f) for f in files]
    return out


def get_kit_run(ctx: Ctx, run_id: uuid.UUID) -> KitRun:
    run = ctx.db.scalar(select(KitRun).where(KitRun.id == run_id, KitRun.workspace_id == ctx.workspace_id))
    if run is None:
        raise NotFound("Geração de kit")
    return run


def list_kit_runs(ctx: Ctx, *, kit_id: uuid.UUID | None, page: int, page_size: int) -> dict[str, Any]:
    db = ctx.db
    cond = [KitRun.workspace_id == ctx.workspace_id]
    if kit_id:
        cond.append(KitRun.kit_id == kit_id)
    total = db.scalar(select(func.count(KitRun.id)).where(*cond)) or 0
    rows = db.scalars(
        select(KitRun)
        .where(*cond)
        .order_by(KitRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [kit_run_out(ctx, r, with_files=True) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
