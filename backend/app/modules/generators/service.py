"""CRUD de geradores, listagem paginada e dashboard."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.adapters.storage import get_storage
from app.core.deps import Ctx
from app.core.errors import Conflict, LimitExceeded, ValidationFailed
from app.db.base import utcnow
from app.db.models import DocumentGenerator, Field, GenerationJob
from app.modules.audit import service as audit
from app.modules.templates import core

SORTS = {
    "updated": DocumentGenerator.updated_at.desc(),
    "name": func.lower(DocumentGenerator.name).asc(),
    "created": DocumentGenerator.created_at.desc(),
}


def generator_out(db: Session, gen: DocumentGenerator) -> dict[str, Any]:
    current = core.current_version_or_none(db, gen)
    n_fields = db.scalar(select(func.count(Field.id)).where(Field.version_id == current.id)) if current else 0
    docs = (
        db.scalar(
            select(func.coalesce(func.sum(GenerationJob.succeeded_items), 0)).where(
                GenerationJob.generator_id == gen.id
            )
        )
        or 0
    )
    return {
        "id": str(gen.id),
        "name": gen.name,
        "description": gen.description,
        "status": gen.status,
        "is_pinned": gen.is_pinned,
        "filename_pattern": gen.filename_pattern,
        "fields_count": n_fields or 0,
        "documents_generated": int(docs),
        "has_template": current is not None,
        "analysis_status": current.analysis_status if current else None,
        "created_at": gen.created_at.isoformat(),
        "updated_at": gen.updated_at.isoformat(),
        "archived_at": gen.archived_at.isoformat() if gen.archived_at else None,
    }


def list_generators(
    ctx: Ctx, *, q: str | None, status: str | None, page: int, page_size: int, sort: str
) -> dict[str, Any]:
    db = ctx.db
    cond = [DocumentGenerator.workspace_id == ctx.workspace_id, DocumentGenerator.deleted_at.is_(None)]
    if status == "archived":
        cond.append(DocumentGenerator.status == "archived")
    else:
        cond.append(DocumentGenerator.status != "archived")
    if q:
        like = f"%{q.strip().lower()}%"
        cond.append(
            or_(
                func.lower(DocumentGenerator.name).like(like),
                func.lower(func.coalesce(DocumentGenerator.description, "")).like(like),
            )
        )
    total = db.scalar(select(func.count(DocumentGenerator.id)).where(*cond)) or 0
    rows = db.scalars(
        select(DocumentGenerator)
        .where(*cond)
        .order_by(DocumentGenerator.is_pinned.desc(), SORTS.get(sort, SORTS["updated"]))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [generator_out(db, g) for g in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def pin_generator(ctx: Ctx, generator_id: uuid.UUID, pinned: bool) -> DocumentGenerator:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    gen.is_pinned = pinned
    gen.updated_at = utcnow()
    audit.record(
        ctx.db,
        "generator.pin" if pinned else "generator.unpin",
        ctx=ctx,
        entity_type="generator",
        entity_id=gen.id,
    )
    ctx.db.commit()
    return gen


def create_generator(ctx: Ctx, name: str, description: str | None) -> DocumentGenerator:
    db = ctx.db
    name = name.strip()
    if not name:
        raise ValidationFailed("Informe o nome do modelo.", code="INVALID_NAME")
    count = (
        db.scalar(
            select(func.count(DocumentGenerator.id)).where(
                DocumentGenerator.workspace_id == ctx.workspace_id, DocumentGenerator.deleted_at.is_(None)
            )
        )
        or 0
    )
    if count >= ctx.limit("max_generators"):
        raise LimitExceeded("Limite de modelos do seu plano atingido.", code="GENERATOR_LIMIT")
    gen = DocumentGenerator(
        workspace_id=ctx.workspace_id,
        name=name[:200],
        description=(description or "").strip()[:500] or None,
        created_by=ctx.user.id,
    )
    db.add(gen)
    db.flush()
    audit.record(db, "generator.create", ctx=ctx, entity_type="generator", entity_id=gen.id)
    db.commit()
    return gen


def update_generator(ctx: Ctx, generator_id: uuid.UUID, patch: dict[str, Any]) -> DocumentGenerator:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    if "name" in patch and patch["name"] is not None:
        if not patch["name"].strip():
            raise ValidationFailed("O nome não pode ficar vazio.", code="INVALID_NAME")
        gen.name = patch["name"].strip()[:200]
    if "description" in patch:
        gen.description = (patch["description"] or "").strip()[:500] or None
    if "filename_pattern" in patch and patch["filename_pattern"] is not None:
        pattern = patch["filename_pattern"].strip()
        if not pattern or len(pattern) > 200:
            raise ValidationFailed("Padrão de nome de arquivo inválido.", code="INVALID_FILENAME_PATTERN")
        gen.filename_pattern = pattern
    gen.updated_at = utcnow()
    audit.record(ctx.db, "generator.update", ctx=ctx, entity_type="generator", entity_id=gen.id)
    ctx.db.commit()
    return gen


def duplicate_generator(ctx: Ctx, generator_id: uuid.UUID) -> DocumentGenerator:
    db = ctx.db
    src = core.get_generator(db, ctx.workspace_id, generator_id)
    count = (
        db.scalar(
            select(func.count(DocumentGenerator.id)).where(
                DocumentGenerator.workspace_id == ctx.workspace_id, DocumentGenerator.deleted_at.is_(None)
            )
        )
        or 0
    )
    if count >= ctx.limit("max_generators"):
        raise LimitExceeded("Limite de modelos do seu plano atingido.", code="GENERATOR_LIMIT")
    base = core.current_version_or_none(db, src)
    copy = DocumentGenerator(
        workspace_id=ctx.workspace_id,
        name=f"{src.name} (cópia)"[:200],
        description=src.description,
        filename_pattern=src.filename_pattern,
        created_by=ctx.user.id,
    )
    db.add(copy)
    db.flush()
    if base is not None and base.source_file_id is not None:
        old_file = core.get_file(db, ctx.workspace_id, base.source_file_id)
        new_file = core.store_file(
            db,
            workspace_id=ctx.workspace_id,
            generator_id=copy.id,
            role="source",
            data=get_storage().get(old_file.storage_key),
            filename=old_file.original_filename,
            user_id=ctx.user.id,
        )
        new_version = core.clone_version(
            db, base, copy, user_id=ctx.user.id, note=f"Duplicado de “{src.name}”", source_file_id=new_file.id
        )
        copy.current_version_id = new_version.id
    audit.record(
        db,
        "generator.duplicate",
        ctx=ctx,
        entity_type="generator",
        entity_id=copy.id,
        meta={"from": str(src.id)},
    )
    db.commit()
    return copy


def archive_generator(ctx: Ctx, generator_id: uuid.UUID, archived: bool) -> DocumentGenerator:
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    if archived:
        gen.status = "archived"
        gen.archived_at = utcnow()
    else:
        gen.archived_at = None
        gen.status = "active"
    gen.updated_at = utcnow()
    audit.record(
        db,
        "generator.archive" if archived else "generator.unarchive",
        ctx=ctx,
        entity_type="generator",
        entity_id=gen.id,
    )
    db.commit()
    return gen


def delete_generator(ctx: Ctx, generator_id: uuid.UUID) -> None:
    """Exclusão lógica: some das listas, o histórico de gerações é preservado (arquivos seguem a retenção)."""
    db = ctx.db
    gen = core.get_generator(db, ctx.workspace_id, generator_id)
    running = (
        db.scalar(
            select(func.count(GenerationJob.id)).where(
                GenerationJob.generator_id == gen.id, GenerationJob.status.in_(("queued", "processing"))
            )
        )
        or 0
    )
    if running:
        raise Conflict(
            "Há gerações em andamento para este modelo. Aguarde a conclusão para excluir.",
            code="JOBS_RUNNING",
        )
    gen.deleted_at = utcnow()
    gen.updated_at = utcnow()
    audit.record(db, "generator.delete", ctx=ctx, entity_type="generator", entity_id=gen.id)
    db.commit()


def dashboard(ctx: Ctx) -> dict[str, Any]:
    db = ctx.db
    now = utcnow()
    month_start = datetime(now.year, now.month, 1, tzinfo=now.tzinfo)
    total = (
        db.scalar(
            select(func.count(DocumentGenerator.id)).where(
                DocumentGenerator.workspace_id == ctx.workspace_id,
                DocumentGenerator.deleted_at.is_(None),
                DocumentGenerator.status != "archived",
            )
        )
        or 0
    )
    docs_month = (
        db.scalar(
            select(func.coalesce(func.sum(GenerationJob.succeeded_items), 0)).where(
                GenerationJob.workspace_id == ctx.workspace_id,
                GenerationJob.created_at >= month_start,
            )
        )
        or 0
    )
    running = (
        db.scalar(
            select(func.count(GenerationJob.id)).where(
                GenerationJob.workspace_id == ctx.workspace_id,
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
        or 0
    )
    problems = (
        db.scalar(
            select(func.count(GenerationJob.id)).where(
                GenerationJob.workspace_id == ctx.workspace_id,
                GenerationJob.status.in_(("failed", "partial")),
            )
        )
        or 0
    )
    recent = db.scalars(
        select(DocumentGenerator)
        .where(
            DocumentGenerator.workspace_id == ctx.workspace_id,
            DocumentGenerator.deleted_at.is_(None),
            DocumentGenerator.status != "archived",
        )
        .order_by(DocumentGenerator.is_pinned.desc(), DocumentGenerator.updated_at.desc())
        .limit(6)
    ).all()
    return {
        "total_generators": total,
        "documents_this_month": int(docs_month),
        "jobs_in_progress": running,
        "jobs_with_problems": problems,
        "quota": {"documents_per_month": ctx.limit("max_docs_per_month")},
        "recent": [generator_out(db, g) for g in recent],
    }
