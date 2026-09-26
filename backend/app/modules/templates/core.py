"""Acesso escopado por workspace e operações de bloco/versão reutilizadas por vários serviços.

Toda consulta filtra por `workspace_id`; recurso de outro workspace responde 404 (nunca 403).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.adapters.storage import get_storage
from app.core.errors import NotFound
from app.db.base import utcnow
from app.db.models import (
    DocumentGenerator,
    Field,
    FieldOccurrence,
    FieldOption,
    TemplateBlock,
    TemplateFile,
    TemplateVersion,
)
from app.docx_engine.inline import inline_text
from app.docx_engine.nodes import context_around, iter_field_spans


def get_generator(
    db: Session, workspace_id: uuid.UUID, generator_id: uuid.UUID, *, include_deleted: bool = False
) -> DocumentGenerator:
    q = select(DocumentGenerator).where(
        DocumentGenerator.id == generator_id, DocumentGenerator.workspace_id == workspace_id
    )
    if not include_deleted:
        q = q.where(DocumentGenerator.deleted_at.is_(None))
    gen = db.scalar(q)
    if gen is None:
        raise NotFound("Modelo")
    return gen


def get_version(db: Session, workspace_id: uuid.UUID, version_id: uuid.UUID) -> TemplateVersion:
    v = db.scalar(
        select(TemplateVersion).where(
            TemplateVersion.id == version_id, TemplateVersion.workspace_id == workspace_id
        )
    )
    if v is None:
        raise NotFound("Versão")
    return v


def current_version_or_none(db: Session, gen: DocumentGenerator) -> TemplateVersion | None:
    if gen.current_version_id is None:
        return None
    return db.get(TemplateVersion, gen.current_version_id)


def current_version(db: Session, gen: DocumentGenerator) -> TemplateVersion:
    v = current_version_or_none(db, gen)
    if v is None:
        raise NotFound("Documento .docx deste modelo")
    return v


def latest_version(db: Session, generator_id: uuid.UUID) -> TemplateVersion | None:
    return db.scalar(
        select(TemplateVersion)
        .where(TemplateVersion.generator_id == generator_id)
        .order_by(TemplateVersion.version_number.desc())
        .limit(1)
    )


def next_version_number(db: Session, generator_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.max(TemplateVersion.version_number)).where(
                TemplateVersion.generator_id == generator_id
            )
        )
        or 0
    ) + 1


def get_file(db: Session, workspace_id: uuid.UUID, file_id: uuid.UUID) -> TemplateFile:
    f = db.scalar(
        select(TemplateFile).where(TemplateFile.id == file_id, TemplateFile.workspace_id == workspace_id)
    )
    if f is None:
        raise NotFound("Arquivo")
    return f


def store_file(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    generator_id: uuid.UUID | None,
    role: str,
    data: bytes,
    filename: str,
    user_id: uuid.UUID | None,
) -> TemplateFile:
    key = f"w/{workspace_id}/tpl/{uuid.uuid4().hex}.docx"  # nome interno aleatório
    get_storage().put(key, data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    f = TemplateFile(
        workspace_id=workspace_id,
        generator_id=generator_id,
        role=role,
        storage_key=key,
        original_filename=filename[:300],
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_by=user_id,
    )
    db.add(f)
    db.flush()
    return f


def load_blocks(db: Session, version_id: uuid.UUID) -> list[TemplateBlock]:
    return list(db.scalars(select(TemplateBlock).where(TemplateBlock.version_id == version_id)))


def ordered_blocks(blocks: list[TemplateBlock], part_order: list[str]) -> list[TemplateBlock]:
    """Ordem de leitura do documento: por parte, percorrendo tabelas (linhas → células) em profundidade."""
    by_container: dict[str, list[TemplateBlock]] = defaultdict(list)
    for b in blocks:
        by_container[b.container_key].append(b)
    for lst in by_container.values():
        lst.sort(key=lambda x: x.ordinal)
    out: list[TemplateBlock] = []

    def walk(container: str) -> None:
        for b in by_container.get(container, []):
            out.append(b)
            if b.kind == "table" and isinstance(b.content, dict):
                for row in b.content.get("rows", []):
                    for cell in row:
                        walk(cell["container"])

    for part in part_order:
        walk(part)
    return out


def part_order_of(version: TemplateVersion, blocks: list[TemplateBlock]) -> list[str]:
    parts = [p["name"] for p in (version.meta or {}).get("parts", [])]
    if parts:
        return parts
    return sorted({b.part for b in blocks})


def recompute_occurrences(db: Session, version: TemplateVersion) -> dict[str, int]:
    """Reconstrói as âncoras (bloco + offsets + trecho + contexto) a partir do conteúdo dos blocos."""
    db.execute(delete(FieldOccurrence).where(FieldOccurrence.version_id == version.id))
    blocks = load_blocks(db, version.id)
    known = {str(fid) for fid in db.scalars(select(Field.id).where(Field.version_id == version.id))}
    counts: dict[str, int] = defaultdict(int)
    ordinal = 0
    for b in ordered_blocks(blocks, part_order_of(version, blocks)):
        if b.kind != "paragraph" or not isinstance(b.content, list):
            continue
        text = inline_text(b.content)
        for start, end, node in iter_field_spans(b.content):
            fid = (node.get("attrs") or {}).get("fieldId")
            if fid not in known:
                continue
            before, after = context_around(text, start, end)
            db.add(
                FieldOccurrence(
                    workspace_id=version.workspace_id,
                    version_id=version.id,
                    field_id=uuid.UUID(fid),
                    block_key=b.key,
                    ordinal=ordinal,
                    start_offset=start,
                    end_offset=end,
                    sample=(node.get("attrs") or {}).get("sample", ""),
                    context_before=before,
                    context_after=after,
                    status="ok",
                )
            )
            counts[fid] += 1
            ordinal += 1
    db.flush()
    return dict(counts)


def occurrence_counts(db: Session, version_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(FieldOccurrence.field_id, func.count())
        .where(FieldOccurrence.version_id == version_id)
        .group_by(FieldOccurrence.field_id)
    ).all()
    return {str(fid): n for fid, n in rows}


def touch(version: TemplateVersion, generator: DocumentGenerator, *, content: bool = False) -> None:
    """Atualiza carimbos. `revision` (concorrência otimista do editor) só muda quando o CONTEÚDO do documento muda:
    criar/renomear campos não invalida o autosave em andamento."""
    now = utcnow()
    if content:
        version.revision += 1
    version.updated_at = now
    generator.updated_at = now


def clone_version(
    db: Session,
    src: TemplateVersion,
    generator: DocumentGenerator,
    *,
    user_id: uuid.UUID | None,
    note: str | None,
    source_file_id: uuid.UUID | None = None,
) -> TemplateVersion:
    """Cria uma nova versão em `generator` copiando blocos, campos e opções de `src` (ids de campo remapeados).
    Não define `generator.current_version_id`: quem chama decide quando a cópia passa a valer.

    `generator` pode ser outro gerador (duplicação); nesse caso passe `source_file_id` com a cópia do arquivo original.
    """
    new = TemplateVersion(
        workspace_id=src.workspace_id,
        generator_id=generator.id,
        version_number=next_version_number(db, generator.id),
        revision=1,
        source_file_id=source_file_id or src.source_file_id,
        based_on_version_id=src.id if generator.id == src.generator_id else None,
        analysis_status="skipped",
        note=note,
        meta=src.meta,
        created_by=user_id,
    )
    db.add(new)
    db.flush()

    id_map: dict[str, str] = {}
    for f in db.scalars(select(Field).where(Field.version_id == src.id).order_by(Field.position)):
        nf = Field(
            workspace_id=f.workspace_id,
            version_id=new.id,
            name=f.name,
            label=f.label,
            type=f.type,
            description=f.description,
            required=f.required,
            default_value=f.default_value,
            example=f.example,
            mask=f.mask,
            group_name=f.group_name,
            position=f.position,
            include_in_batch=f.include_in_batch,
            config=f.config,
        )
        db.add(nf)
        db.flush()
        id_map[str(f.id)] = str(nf.id)
        for o in db.scalars(
            select(FieldOption).where(FieldOption.field_id == f.id).order_by(FieldOption.position)
        ):
            db.add(
                FieldOption(
                    workspace_id=o.workspace_id,
                    field_id=nf.id,
                    label=o.label,
                    value=o.value,
                    position=o.position,
                )
            )

    for b in load_blocks(db, src.id):
        content: Any = b.content
        if b.kind == "paragraph" and isinstance(content, list):
            content = remap_field_ids(content, id_map)
        db.add(
            TemplateBlock(
                workspace_id=b.workspace_id,
                version_id=new.id,
                key=b.key,
                part=b.part,
                container_key=b.container_key,
                ordinal=b.ordinal,
                kind=b.kind,
                origin=b.origin,
                content=content,
                attrs=b.attrs,
                text=b.text,
                source_text=b.source_text,
            )
        )
    db.flush()
    recompute_occurrences(db, new)
    return new


def remap_field_ids(content: list[dict[str, Any]], id_map: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for n in content:
        if n.get("type") == "field":
            n = {
                **n,
                "attrs": {
                    **(n.get("attrs") or {}),
                    "fieldId": id_map.get(
                        (n.get("attrs") or {}).get("fieldId", ""), (n.get("attrs") or {}).get("fieldId")
                    ),
                },
            }
        out.append(n)
    return out
