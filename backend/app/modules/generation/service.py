"""Geração individual e em lote: validação, criação de jobs idempotentes, histórico e downloads."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.pdf import PdfConverterUnavailable, pdf_available
from app.adapters.queue import enqueue
from app.adapters.storage import get_storage
from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.errors import (
    AppError,
    Conflict,
    Forbidden,
    LimitExceeded,
    NotFound,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.security import sign_payload, verify_payload
from app.db.base import utcnow
from app.db.models import (
    DocumentGenerator,
    DocumentKit,
    GeneratedFile,
    GenerationItem,
    GenerationJob,
    KitRun,
    TemplateVersion,
    User,
)
from app.modules.audit import service as audit
from app.modules.fields import service as fields_service
from app.modules.fields.normalize import RowResult, format_value, is_empty, today_utc, validate_row
from app.modules.fields.types import FieldDef
from app.modules.generation import filenames
from app.modules.templates import core
from app.modules.templates import service as templates_service

Format = Literal["docx", "pdf", "both"]
MAX_ROWS_PAYLOAD = 5000


class SingleIn(BaseModel):
    values: dict[str, Any]
    format: Format = "docx"
    filename_pattern: str | None = PField(default=None, max_length=200)
    idempotency_key: str | None = PField(default=None, max_length=120)


class BatchIn(BaseModel):
    rows: list[dict[str, Any]] = PField(max_length=MAX_ROWS_PAYLOAD)
    format: Format = "docx"
    only_valid: bool = False
    filename_pattern: str | None = PField(default=None, max_length=200)
    idempotency_key: str | None = PField(default=None, max_length=120)


class ValidateIn(BaseModel):
    rows: list[dict[str, Any]] = PField(max_length=MAX_ROWS_PAYLOAD)


# ------------------------------------------------------------------ validação


def _defs_for(ctx: Ctx, gen: DocumentGenerator) -> tuple[TemplateVersion, list[FieldDef]]:
    db = ctx.db
    v = core.current_version(db, gen)
    defs = fields_service.field_defs(db, v.id)
    if not defs:
        raise ValidationFailed("Este modelo ainda não tem campos.", code="NO_FIELDS")
    return v, defs


def validate_rows(defs: list[FieldDef], rows: list[dict[str, Any]], *, batch: bool) -> list[RowResult]:
    in_batch = {d.name for d in defs if d.include_in_batch}
    results: list[RowResult] = []
    for row in rows:
        data = {k: v for k, v in row.items() if k in in_batch} if batch else row
        res = validate_row(defs, data)
        if batch:
            for d in defs:
                if not d.include_in_batch and d.required and is_empty(res.values.get(d.name)):
                    res.errors[d.name] = "Campo obrigatório fora do lote e sem valor padrão."
        results.append(res)
    return results


def validate_batch_endpoint(ctx: Ctx, generator_id: uuid.UUID, body: ValidateIn) -> dict[str, Any]:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    _, defs = _defs_for(ctx, gen)
    if len(body.rows) > ctx.limit("max_batch_rows"):
        raise LimitExceeded(
            f"O lote pode ter no máximo {ctx.limit('max_batch_rows')} linhas.", code="BATCH_TOO_LARGE"
        )
    results = validate_rows(defs, body.rows, batch=True)
    labels = {d.name: d.label for d in defs}
    return {
        "rows": [{"index": i + 1, "valid": r.valid, "errors": r.errors} for i, r in enumerate(results)],
        "valid_count": sum(1 for r in results if r.valid),
        "invalid_count": sum(1 for r in results if not r.valid),
        "labels": labels,
    }


# ------------------------------------------------------------------ criação de jobs


def _month_usage(ctx: Ctx) -> int:
    now = utcnow()
    start = datetime(now.year, now.month, 1, tzinfo=now.tzinfo)
    return int(
        ctx.db.scalar(
            select(func.coalesce(func.sum(GenerationJob.total_items), 0)).where(
                GenerationJob.workspace_id == ctx.workspace_id,
                GenerationJob.created_at >= start,
                GenerationJob.status != "cancelled",
            )
        )
        or 0
    )


def _existing_by_key(ctx: Ctx, key: str | None) -> GenerationJob | None:
    if not key:
        return None
    return ctx.db.scalar(
        select(GenerationJob).where(
            GenerationJob.workspace_id == ctx.workspace_id, GenerationJob.idempotency_key == key
        )
    )


def _tokens(defs: list[FieldDef], values: dict[str, Any], row_no: int, gen_name: str) -> dict[str, str]:
    today = today_utc().isoformat()
    tokens = {d.name: format_value(d, values.get(d.name)) for d in defs}
    tokens.setdefault("data", today)
    tokens["hoje"], tokens["linha"], tokens["gerador"] = today, f"{row_no:04d}", gen_name
    # {modelo} é o nome atual do código {gerador} (que continua valendo); não é reservado — se o modelo tiver
    # um campo chamado "modelo" (ex.: modelo do veículo), o campo vence
    tokens.setdefault("modelo", gen_name)
    return tokens


def _create_job(
    ctx: Ctx,
    gen: DocumentGenerator,
    *,
    kind: str,
    fmt: Format,
    rows: list[dict[str, Any]],
    only_valid: bool,
    pattern: str | None,
    idem: str | None,
    kit_run_id: uuid.UUID | None = None,
) -> tuple[GenerationJob, bool]:
    db = ctx.db
    if (existing := _existing_by_key(ctx, idem)) is not None:
        return existing, False
    if fmt in ("pdf", "both") and not pdf_available():
        raise PdfConverterUnavailable
    if not rows:
        raise ValidationFailed("Informe ao menos uma linha.", code="EMPTY_BATCH")
    if len(rows) > ctx.limit("max_batch_rows"):
        raise LimitExceeded(
            f"O lote pode ter no máximo {ctx.limit('max_batch_rows')} linhas.", code="BATCH_TOO_LARGE"
        )

    version, defs = _defs_for(ctx, gen)
    results = validate_rows(defs, rows, batch=kind == "batch")
    invalid = [i for i, r in enumerate(results) if not r.valid]
    if invalid and not only_valid:
        labels = {d.name: d.label for d in defs}
        detail = [
            {
                "row": i + 1,
                "errors": {labels.get(k, k): v for k, v in results[i].errors.items()},
                "field_errors": dict(results[i].errors),
            }
            for i in invalid[:50]
        ]
        raise ValidationFailed(
            f"{len(invalid)} linha(s) com erro. Corrija-as ou gere apenas as linhas válidas.",
            code="BATCH_INVALID_ROWS",
            details={"invalid_rows": detail, "invalid_count": len(invalid), "total": len(rows)},
        )
    valid_idx = [i for i, r in enumerate(results) if r.valid]
    if not valid_idx:
        raise ValidationFailed("Nenhuma linha válida para gerar.", code="NO_VALID_ROWS")
    if _month_usage(ctx) + len(valid_idx) > ctx.limit("max_docs_per_month"):
        raise LimitExceeded("A cota mensal de documentos do seu plano seria excedida.", code="MONTHLY_QUOTA")

    _, compiled = templates_service.compile_current(ctx, gen)
    pattern = (pattern or gen.filename_pattern or "{modelo}_{linha}").strip()
    names = filenames.dedupe(
        [
            filenames.render_pattern(pattern, _tokens(defs, results[i].values, i + 1, gen.name))
            for i in valid_idx
        ]
    )
    name_of = dict(zip(valid_idx, names, strict=True))

    job = GenerationJob(
        workspace_id=ctx.workspace_id,
        generator_id=gen.id,
        template_version_id=version.id,
        compiled_file_id=compiled.id,
        kind=kind,
        status="queued",
        output_format=fmt,
        idempotency_key=idem,
        filename_pattern=pattern,
        fields_snapshot=[d.to_snapshot() for d in defs],
        total_items=len(valid_idx),
        created_by=ctx.user.id,
        kit_run_id=kit_run_id,
    )
    db.add(job)
    db.flush()
    labels = {d.name: d.label for d in defs}
    for i, res in enumerate(results):
        if res.valid:
            db.add(
                GenerationItem(
                    workspace_id=ctx.workspace_id,
                    job_id=job.id,
                    row_index=i + 1,
                    status="pending",
                    values=res.values,
                    filename=name_of[i],
                )
            )
        else:
            msg = "; ".join(f"{labels.get(k, k)}: {m}" for k, m in res.errors.items())[:480]
            db.add(
                GenerationItem(
                    workspace_id=ctx.workspace_id,
                    job_id=job.id,
                    row_index=i + 1,
                    status="skipped",
                    values={
                        k: v for k, v in rows[i].items() if isinstance(v, (str, int, float, bool, type(None)))
                    },
                    error_code="VALIDATION_FAILED",
                    error_message=msg,
                )
            )
    audit.record(
        db,
        "generation.create",
        ctx=ctx,
        entity_type="job",
        entity_id=job.id,
        meta={"kind": kind, "rows": len(rows), "valid": len(valid_idx), "format": fmt},
    )
    try:
        db.commit()
    except IntegrityError:  # corrida de idempotência: outra requisição com a mesma chave venceu
        db.rollback()
        existing = _existing_by_key(ctx, idem)
        if existing is None:
            raise
        return existing, False
    _enqueue_or_fail(db, job)
    db.refresh(job)
    return job, True


def _enqueue_or_fail(db: Session, job: GenerationJob) -> None:
    try:
        enqueue("generation", job_id=str(job.id))
    except Exception as exc:
        job.status, job.error_code, job.finished_at = "failed", "QUEUE_UNAVAILABLE", utcnow()
        job.error_message = (
            "A fila de processamento está indisponível. Nenhum documento foi gerado; tente novamente."
        )
        db.commit()
        raise ServiceUnavailable(job.error_message, code="QUEUE_UNAVAILABLE") from exc


def create_single(
    ctx: Ctx, generator_id: uuid.UUID, body: SingleIn, header_key: str | None
) -> tuple[GenerationJob, bool]:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    return _create_job(
        ctx,
        gen,
        kind="single",
        fmt=body.format,
        rows=[body.values],
        only_valid=False,
        pattern=body.filename_pattern,
        idem=header_key or body.idempotency_key,
    )


def create_batch(
    ctx: Ctx, generator_id: uuid.UUID, body: BatchIn, header_key: str | None
) -> tuple[GenerationJob, bool]:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    return _create_job(
        ctx,
        gen,
        kind="batch",
        fmt=body.format,
        rows=body.rows,
        only_valid=body.only_valid,
        pattern=body.filename_pattern,
        idem=header_key or body.idempotency_key,
    )


def repeat_job(ctx: Ctx, job_id: uuid.UUID, idem: str | None) -> tuple[GenerationJob, bool]:
    """Nova geração com os mesmos dados, versão e gabarito. Membro só repete o que ele mesmo gerou; owner repete qualquer um."""
    db = ctx.db
    src = get_job(ctx, job_id)
    if not ctx.is_owner and src.created_by != ctx.user.id:
        raise Forbidden("Você só pode repetir gerações criadas por você.")
    if (existing := _existing_by_key(ctx, idem)) is not None:
        return existing, False
    if src.output_format in ("pdf", "both") and not pdf_available():
        raise PdfConverterUnavailable
    items = list(
        db.scalars(
            select(GenerationItem)
            .where(GenerationItem.job_id == src.id, GenerationItem.status != "skipped")
            .order_by(GenerationItem.row_index)
        )
    )
    if not items:
        raise ValidationFailed("Não há dados válidos para repetir.", code="NOTHING_TO_REPEAT")
    if _month_usage(ctx) + len(items) > ctx.limit("max_docs_per_month"):
        raise LimitExceeded("A cota mensal de documentos do seu plano seria excedida.", code="MONTHLY_QUOTA")
    job = GenerationJob(
        workspace_id=ctx.workspace_id,
        generator_id=src.generator_id,
        template_version_id=src.template_version_id,
        compiled_file_id=src.compiled_file_id,
        kind=src.kind,
        status="queued",
        output_format=src.output_format,
        idempotency_key=idem,
        filename_pattern=src.filename_pattern,
        fields_snapshot=src.fields_snapshot,
        total_items=len(items),
        source_job_id=src.id,
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    for n, it in enumerate(items, start=1):
        db.add(
            GenerationItem(
                workspace_id=ctx.workspace_id,
                job_id=job.id,
                row_index=n,
                status="pending",
                values=it.values,
                filename=it.filename,
            )
        )
    audit.record(
        db,
        "generation.repeat",
        ctx=ctx,
        entity_type="job",
        entity_id=job.id,
        meta={"source": str(src.id), "rows": len(items)},
    )
    db.commit()
    _enqueue_or_fail(db, job)
    db.refresh(job)
    return job, True


def cancel_job(ctx: Ctx, job_id: uuid.UUID) -> GenerationJob:
    job = get_job(ctx, job_id)
    if job.status not in ("queued", "processing"):
        raise Conflict("Esta geração já foi concluída.", code="JOB_FINISHED")
    if not ctx.is_owner and job.created_by != ctx.user.id:
        raise Forbidden("Você só pode cancelar gerações criadas por você.")
    job.status = "cancelled"
    job.finished_at = utcnow()
    audit.record(ctx.db, "generation.cancel", ctx=ctx, entity_type="job", entity_id=job.id)
    ctx.db.commit()
    return job


# ------------------------------------------------------------------ leitura


def get_job(ctx: Ctx, job_id: uuid.UUID) -> GenerationJob:
    job = ctx.db.scalar(
        select(GenerationJob).where(
            GenerationJob.id == job_id, GenerationJob.workspace_id == ctx.workspace_id
        )
    )
    if job is None:
        raise NotFound("Geração")
    return job


def file_out(f: GeneratedFile) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "kind": f.kind,
        "filename": f.filename,
        "size_bytes": f.size_bytes,
        "expires_at": f.expires_at.isoformat(),
        "expired": f.deleted_at is not None or f.expires_at <= utcnow(),
        "item_id": str(f.item_id) if f.item_id else None,
    }


def job_out(ctx: Ctx, job: GenerationJob, *, with_files: bool = False) -> dict[str, Any]:
    db = ctx.db
    gen = db.get(DocumentGenerator, job.generator_id)
    version = db.get(TemplateVersion, job.template_version_id)
    author = db.get(User, job.created_by) if job.created_by else None
    skipped = (
        db.scalar(
            select(func.count(GenerationItem.id)).where(
                GenerationItem.job_id == job.id, GenerationItem.status == "skipped"
            )
        )
        or 0
    )
    processed = job.succeeded_items + job.failed_items
    kit_name = None
    if job.kit_run_id:
        run = db.get(KitRun, job.kit_run_id)
        kit = db.get(DocumentKit, run.kit_id) if run else None
        kit_name = kit.name if kit else "(kit removido)"
    out: dict[str, Any] = {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "output_format": job.output_format,
        "generator_id": str(job.generator_id),
        "generator_name": gen.name if gen else "(removido)",
        "version_number": version.version_number if version else None,
        "total_items": job.total_items,
        "succeeded_items": job.succeeded_items,
        "failed_items": job.failed_items,
        "skipped_items": skipped,
        "progress": round(processed / job.total_items, 4) if job.total_items else 0.0,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "bytes_total": job.bytes_total,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_ms": job.duration_ms,
        "created_by": author.name if author else None,
        "source_job_id": str(job.source_job_id) if job.source_job_id else None,
        "kit_run_id": str(job.kit_run_id) if job.kit_run_id else None,
        "kit_name": kit_name,
        "can_repeat": ctx.is_owner or job.created_by == ctx.user.id,
    }
    files = list(
        db.scalars(
            select(GeneratedFile)
            .where(GeneratedFile.job_id == job.id, GeneratedFile.deleted_at.is_(None))
            .order_by(GeneratedFile.created_at)
        )
    )
    exp = [f.expires_at for f in files]
    out["files_expire_at"] = min(exp).isoformat() if exp else None
    if with_files:
        visible = [f for f in files if job.kind == "single" or f.kind in ("zip", "report", "signed")]
        out["files"] = [file_out(f) for f in visible]
    return out


def list_jobs(
    ctx: Ctx,
    *,
    kind: str | None,
    status: str | None,
    generator_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    db = ctx.db
    cond = [GenerationJob.workspace_id == ctx.workspace_id]
    if kind == "kit":
        cond.append(GenerationJob.kit_run_id.is_not(None))
    elif kind in ("single", "batch"):
        cond.append(GenerationJob.kind == kind)
        if kind == "single":
            cond.append(GenerationJob.kit_run_id.is_(None))  # documentos de kit têm filtro próprio
    if status:
        cond.append(GenerationJob.status == status)
    if generator_id:
        cond.append(GenerationJob.generator_id == generator_id)
    total = db.scalar(select(func.count(GenerationJob.id)).where(*cond)) or 0
    rows = db.scalars(
        select(GenerationJob)
        .where(*cond)
        .order_by(GenerationJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [job_out(ctx, j, with_files=True) for j in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_items(
    ctx: Ctx, job_id: uuid.UUID, *, status: str | None, page: int, page_size: int
) -> dict[str, Any]:
    db = ctx.db
    job = get_job(ctx, job_id)
    cond = [GenerationItem.job_id == job.id]
    if status:
        cond.append(GenerationItem.status == status)
    total = db.scalar(select(func.count(GenerationItem.id)).where(*cond)) or 0
    items = db.scalars(
        select(GenerationItem)
        .where(*cond)
        .order_by(GenerationItem.row_index)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    files: dict[uuid.UUID, list[GeneratedFile]] = {}
    ids = [i.id for i in items]
    if ids:
        for f in db.scalars(
            select(GeneratedFile).where(GeneratedFile.item_id.in_(ids), GeneratedFile.deleted_at.is_(None))
        ):
            files.setdefault(f.item_id, []).append(f)  # type: ignore[arg-type]
    return {
        "items": [
            {
                "id": str(i.id),
                "row_index": i.row_index,
                "status": i.status,
                "filename": i.filename,
                "error_code": i.error_code,
                "error_message": i.error_message,
                "attempts": i.attempts,
                "files": [file_out(f) for f in files.get(i.id, [])],
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ------------------------------------------------------------------ downloads


def create_download_link(ctx: Ctx, file_id: uuid.UUID) -> dict[str, Any]:
    f = _get_file(ctx, file_id)
    ttl = get_settings().download_token_ttl_seconds
    token = sign_payload({"f": str(f.id), "w": str(ctx.workspace_id), "u": str(ctx.user.id)}, ttl)
    audit.record(ctx.db, "file.link", ctx=ctx, entity_type="file", entity_id=f.id, meta={"kind": f.kind})
    ctx.db.commit()
    return {
        "url": f"/api/v1/downloads/{token}",
        "expires_in": ttl,
        "filename": f.filename,
        "file_expires_at": f.expires_at.isoformat(),
    }


def _get_file(ctx: Ctx, file_id: uuid.UUID) -> GeneratedFile:
    f = ctx.db.scalar(
        select(GeneratedFile).where(
            GeneratedFile.id == file_id, GeneratedFile.workspace_id == ctx.workspace_id
        )
    )
    if f is None:
        raise NotFound("Arquivo")
    if f.deleted_at is not None or f.expires_at <= utcnow():
        raise AppError(
            "Este arquivo expirou e foi removido conforme a política de retenção. Gere-o novamente.",
            code="FILE_EXPIRED",
            status_code=410,
        )
    return f


def open_download(ctx: Ctx, token: str) -> GeneratedFile:
    payload = verify_payload(token)
    if not payload or payload.get("w") != str(ctx.workspace_id) or payload.get("u") != str(ctx.user.id):
        raise NotFound("Link de download")  # inválido, expirado ou de outro usuário/workspace: indistinguível
    f = _get_file(ctx, uuid.UUID(payload["f"]))
    audit.record(
        ctx.db,
        "file.download",
        ctx=ctx,
        entity_type="file",
        entity_id=f.id,
        meta={"kind": f.kind, "bytes": f.size_bytes},
    )
    ctx.db.commit()
    return f


def stream_file(f: GeneratedFile):  # type: ignore[no-untyped-def]
    return get_storage().stream(f.storage_key)


def retention_deadline() -> datetime:
    return utcnow() + timedelta(days=get_settings().file_retention_days)
