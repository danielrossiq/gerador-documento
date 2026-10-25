"""Roteador principal (/api/v1). Cada rota delega a um serviço; nenhuma regra de negócio mora aqui."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import Field as PField

from app.core.deps import Ctx, get_ctx
from app.core.errors import ValidationFailed
from app.db.base import utcnow
from app.db.models import BatchImport
from app.modules.assist import service as assist_service
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.modules.fields import service as fields_service
from app.modules.generation import filenames, identify, imports
from app.modules.generation import service as gen_service
from app.modules.generators import service as generators_service
from app.modules.kits import service as kits_service
from app.modules.samples import service as samples_service
from app.modules.suggestions import service as suggestions_service
from app.modules.templates import core
from app.modules.templates import service as templates_service

api = APIRouter(prefix="/api/v1")
api.include_router(auth_router)
api.include_router(billing_router)

IdemHeader = Annotated[str | None, Header(alias="Idempotency-Key", max_length=120)]


# ------------------------------------------------------------------ IA para quem usa o modelo (D33)


class AssistFillIn(BaseModel):
    text: str = PField(min_length=1, max_length=20_000)


class AssistReviewIn(BaseModel):
    values: dict[str, Any] = PField(default_factory=dict)


@api.get("/assist/status", tags=["assist"])
def assist_status(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return assist_service.status(ctx)


@api.post("/generators/{generator_id}/assist/fill", tags=["assist"])
def assist_fill(generator_id: uuid.UUID, body: AssistFillIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    """Texto colado (e-mail, WhatsApp, ficha) → valores para os campos do formulário, já validados."""
    return assist_service.fill_generator(ctx, generator_id, body.text)


@api.post("/kits/{kit_id}/assist/fill", tags=["assist"])
def assist_fill_kit(kit_id: uuid.UUID, body: AssistFillIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return assist_service.fill_kit(ctx, kit_id, body.text)


@api.post("/generators/{generator_id}/assist/fill-files", tags=["assist"])
def assist_fill_files(
    generator_id: uuid.UUID, files: list[UploadFile] = File(...), ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    """Fotos/PDF dos documentos do cliente (RG, CNH, comprovante…) → valores para os campos, já validados."""
    return assist_service.fill_generator_files(ctx, generator_id, _read_assist_files(files, ctx))


@api.post("/kits/{kit_id}/assist/fill-files", tags=["assist"])
def assist_fill_kit_files(
    kit_id: uuid.UUID, files: list[UploadFile] = File(...), ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return assist_service.fill_kit_files(ctx, kit_id, _read_assist_files(files, ctx))


def _read_assist_files(files: list[UploadFile], ctx: Ctx) -> list[bytes]:
    if len(files) > assist_service.MAX_FILES:
        raise ValidationFailed(
            f"Envie no máximo {assist_service.MAX_FILES} arquivos por vez.", code="AI_TOO_MANY_FILES"
        )
    return [_read_upload(f, ctx, limit_mb=assist_service.MAX_FILE_BYTES // (1024 * 1024)) for f in files]


@api.post("/generators/{generator_id}/assist/review", tags=["assist"])
def assist_review(generator_id: uuid.UUID, body: AssistReviewIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    """Documento preenchido → apontamentos de incoerência (datas, nomes, concordância, valores)."""
    return assist_service.review_generator(ctx, generator_id, body.values)


# ------------------------------------------------------------------ dashboard e geradores


@api.get("/dashboard", tags=["dashboard"])
def dashboard(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return {**generators_service.dashboard(ctx), "kits": kits_service.dashboard(ctx)}


@api.post("/samples/generator", status_code=201, tags=["samples"])
def create_sample_generator(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return generators_service.generator_out(ctx.db, samples_service.create_sample_contract(ctx))


@api.post("/samples/kit", status_code=201, tags=["samples"])
def create_sample_kit(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_out(ctx.db, samples_service.create_sample_kit(ctx))


class GeneratorIn(BaseModel):
    name: str = PField(min_length=1, max_length=200)
    description: str | None = PField(default=None, max_length=500)


class GeneratorPatch(BaseModel):
    name: str | None = PField(default=None, max_length=200)
    description: str | None = PField(default=None, max_length=500)
    filename_pattern: str | None = PField(default=None, max_length=200)


@api.get("/generators", tags=["generators"])
def list_generators(
    q: str | None = Query(default=None, max_length=100),
    status: Literal["archived"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: Literal["updated", "name", "created"] = "updated",
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return generators_service.list_generators(
        ctx, q=q, status=status, page=page, page_size=page_size, sort=sort
    )


@api.post("/generators", status_code=201, tags=["generators"])
def create_generator(body: GeneratorIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    gen = generators_service.create_generator(ctx, body.name, body.description)
    return generators_service.generator_out(ctx.db, gen)


@api.get("/generators/{generator_id}", tags=["generators"])
def get_generator(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return generators_service.generator_out(
        ctx.db, core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    )


@api.patch("/generators/{generator_id}", tags=["generators"])
def patch_generator(
    generator_id: uuid.UUID, body: GeneratorPatch, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    gen = generators_service.update_generator(ctx, generator_id, body.model_dump(exclude_unset=True))
    return generators_service.generator_out(ctx.db, gen)


@api.post("/generators/{generator_id}/duplicate", status_code=201, tags=["generators"])
def duplicate_generator(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return generators_service.generator_out(ctx.db, generators_service.duplicate_generator(ctx, generator_id))


@api.post("/generators/{generator_id}/archive", tags=["generators"])
def archive_generator(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return generators_service.generator_out(
        ctx.db, generators_service.archive_generator(ctx, generator_id, True)
    )


@api.post("/generators/{generator_id}/unarchive", tags=["generators"])
def unarchive_generator(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return generators_service.generator_out(
        ctx.db, generators_service.archive_generator(ctx, generator_id, False)
    )


@api.post("/generators/{generator_id}/pin", tags=["generators"])
def pin_generator(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return generators_service.generator_out(ctx.db, generators_service.pin_generator(ctx, generator_id, True))


@api.post("/generators/{generator_id}/unpin", tags=["generators"])
def unpin_generator(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return generators_service.generator_out(
        ctx.db, generators_service.pin_generator(ctx, generator_id, False)
    )


@api.delete("/generators/{generator_id}", status_code=204, tags=["generators"])
def delete_generator(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    generators_service.delete_generator(ctx, generator_id)
    return Response(status_code=204)


# ------------------------------------------------------------------ modelo (upload, editor, versões, publicação)


def _read_upload(file: UploadFile, ctx: Ctx, limit_mb: int | None = None) -> bytes:
    max_bytes = (limit_mb or ctx.limit("max_upload_mb")) * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidationFailed(
            f"O arquivo excede o limite de {max_bytes // (1024 * 1024)} MB.", code="FILE_TOO_LARGE"
        )
    return data


@api.post("/generators/{generator_id}/template", status_code=201, tags=["templates"])
def upload_template(
    generator_id: uuid.UUID, file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    data = _read_upload(file, ctx)
    version = templates_service.upload_template(ctx, generator_id, file.filename or "", data)
    return {
        "version": templates_service.version_out(version),
        "generator": generators_service.generator_out(
            ctx.db, core.get_generator(ctx.db, ctx.workspace_id, generator_id)
        ),
    }


@api.get("/generators/{generator_id}/editor", tags=["templates"])
def get_editor(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return templates_service.get_editor(ctx, generator_id)


class ContentIn(BaseModel):
    revision: int
    doc: dict[str, Any]


@api.put("/generators/{generator_id}/editor/content", tags=["templates"])
def save_content(generator_id: uuid.UUID, body: ContentIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return templates_service.save_editor_doc(ctx, generator_id, body.doc, body.revision)


@api.get("/generators/{generator_id}/versions", tags=["templates"])
def list_versions(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return {"items": templates_service.list_versions(ctx, generator_id)}


@api.post("/generators/{generator_id}/versions/{version_id}/restore", status_code=201, tags=["templates"])
def restore_version(
    generator_id: uuid.UUID, version_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return templates_service.version_out(templates_service.restore_version(ctx, generator_id, version_id))


@api.get("/generators/{generator_id}/form", tags=["generation"])
def get_form(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return templates_service.form_payload(ctx, generator_id)


# ------------------------------------------------------------------ campos


@api.get("/generators/{generator_id}/fields", tags=["fields"])
def list_fields(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    v = core.current_version_or_none(ctx.db, gen)
    return {"items": fields_service.list_out(ctx.db, v) if v else []}


@api.post("/generators/{generator_id}/fields", status_code=201, tags=["fields"])
def create_field(
    generator_id: uuid.UUID, body: fields_service.FieldIn, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    f = fields_service.create_field(ctx, generator_id, body)
    opts = fields_service.options_by_field(ctx.db, [f.id])[f.id]
    return fields_service.field_out(f, opts, 0)


class OrderIn(BaseModel):
    ids: list[uuid.UUID]


@api.put("/generators/{generator_id}/fields/order", status_code=204, tags=["fields"])
def reorder_fields(generator_id: uuid.UUID, body: OrderIn, ctx: Ctx = Depends(get_ctx)) -> Response:
    fields_service.reorder_fields(ctx, generator_id, body.ids)
    return Response(status_code=204)


@api.patch("/fields/{field_id}", tags=["fields"])
def patch_field(
    field_id: uuid.UUID, body: fields_service.FieldPatch, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    f = fields_service.update_field(ctx, field_id, body)
    _, version = fields_service.get_field_scoped(ctx.db, ctx.workspace_id, f.id)
    opts = fields_service.options_by_field(ctx.db, [f.id])[f.id]
    return fields_service.field_out(f, opts, core.occurrence_counts(ctx.db, version.id).get(str(f.id), 0))


class OptionsIn(BaseModel):
    options: list[fields_service.OptionIn]


@api.put("/fields/{field_id}/options", tags=["fields"])
def put_options(field_id: uuid.UUID, body: OptionsIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    opts = fields_service.replace_options(ctx, field_id, body.options)
    return {"options": [{"id": str(o.id), "label": o.label, "value": o.value} for o in opts]}


@api.delete("/fields/{field_id}", tags=["fields"])
def delete_field(
    field_id: uuid.UUID,
    occurrences: Literal["keep_text", "remove_text"] = "keep_text",
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    n, revision = fields_service.delete_field(ctx, field_id, occurrences)
    return {"affected_occurrences": n, "revision": revision}


# ------------------------------------------------------------------ sugestões


@api.get("/generators/{generator_id}/suggestions", tags=["suggestions"])
def list_suggestions(
    generator_id: uuid.UUID,
    status: Literal["pending", "accepted", "ignored"] = "pending",
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return suggestions_service.list_suggestions(ctx, generator_id, status)


class AnalyzeIn(BaseModel):
    force: bool = False


@api.post("/generators/{generator_id}/suggestions/analyze", status_code=202, tags=["suggestions"])
def analyze(
    generator_id: uuid.UUID, body: AnalyzeIn | None = None, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return suggestions_service.request_analysis(ctx, generator_id, body.force if body else False)


class AcceptAllIn(BaseModel):
    min_confidence: float = PField(default=0.85, ge=0, le=1)


@api.post("/generators/{generator_id}/suggestions/accept-all", tags=["suggestions"])
def accept_all(
    generator_id: uuid.UUID, body: AcceptAllIn | None = None, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return suggestions_service.accept_all(ctx, generator_id, body.min_confidence if body else 0.85)


@api.post("/suggestions/{suggestion_id}/accept", tags=["suggestions"])
def accept_suggestion(
    suggestion_id: uuid.UUID, body: suggestions_service.AcceptIn | None = None, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return suggestions_service.accept(ctx, suggestion_id, body or suggestions_service.AcceptIn())


@api.post("/suggestions/{suggestion_id}/ignore", tags=["suggestions"])
def ignore_suggestion(
    suggestion_id: uuid.UUID, apply_to_all: bool = True, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return {"ignored": suggestions_service.ignore(ctx, suggestion_id, apply_to_all)}


# ------------------------------------------------------------------ geração


@api.post("/generators/{generator_id}/generate", status_code=202, tags=["generation"])
def generate(
    generator_id: uuid.UUID,
    body: gen_service.SingleIn,
    response: Response,
    idempotency_key: IdemHeader = None,
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    job, created = gen_service.create_single(ctx, generator_id, body, idempotency_key)
    response.status_code = 202 if created else 200
    response.headers["Idempotent-Replayed"] = "false" if created else "true"
    return gen_service.job_out(ctx, job, with_files=True)


@api.post("/generators/{generator_id}/batch/validate", tags=["batch"])
def validate_batch(
    generator_id: uuid.UUID, body: gen_service.ValidateIn, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return gen_service.validate_batch_endpoint(ctx, generator_id, body)


@api.post("/generators/{generator_id}/batches", status_code=202, tags=["batch"])
def create_batch(
    generator_id: uuid.UUID,
    body: gen_service.BatchIn,
    response: Response,
    idempotency_key: IdemHeader = None,
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    job, created = gen_service.create_batch(ctx, generator_id, body, idempotency_key)
    response.status_code = 202 if created else 200
    response.headers["Idempotent-Replayed"] = "false" if created else "true"
    return gen_service.job_out(ctx, job, with_files=True)


def _batch_defs(ctx: Ctx, generator_id: uuid.UUID) -> tuple[Any, list[Any]]:
    gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
    _, defs = gen_service._defs_for(ctx, gen)
    return gen, defs


@api.get("/generators/{generator_id}/batch/template.xlsx", tags=["batch"])
def batch_template(generator_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    gen, defs = _batch_defs(ctx, generator_id)
    data = imports.build_template_xlsx(gen.name, defs)
    name = filenames.sanitize_filename(f"modelo_{gen.name}") + ".xlsx"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": filenames.content_disposition(name),
            "Cache-Control": "private, no-store",
        },
    )


@api.post("/generators/{generator_id}/batch/imports", status_code=201, tags=["batch"])
def import_upload(
    generator_id: uuid.UUID, file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    gen, defs = _batch_defs(ctx, generator_id)
    data = _read_upload(file, ctx, 10)
    columns, rows = imports.parse_table(file.filename or "", data, max_rows=ctx.limit("max_batch_rows"))
    batchable = [d for d in defs if d.include_in_batch]
    row = BatchImport(
        workspace_id=ctx.workspace_id,
        generator_id=gen.id,
        filename=(file.filename or "")[:300],
        columns=columns,
        rows=rows,
        created_by=ctx.user.id,
        expires_at=utcnow() + timedelta(hours=1),
    )
    ctx.db.add(row)
    ctx.db.commit()
    return {
        "import_id": str(row.id),
        "filename": row.filename,
        "columns": columns,
        "sample": rows[:5],
        "row_count": len(rows),
        "suggested_mapping": imports.suggest_mapping(columns, batchable),
        "fields": [
            {
                "id": d.id,
                "name": d.name,
                "label": d.label,
                "type": d.type,
                "required": d.required,
                "options": (
                    [{"label": o.label, "value": o.value} for o in d.options] if d.type == "select" else None
                ),
            }
            for d in batchable
        ],
    }


class IdentifyIn(BaseModel):
    headers: list[Annotated[str, PField(max_length=200)]] = PField(
        min_length=1, max_length=identify.MAX_COLUMNS
    )
    rows: list[list[Annotated[str, PField(max_length=1000)]]] = PField(default_factory=list, max_length=50)
    generator_id: uuid.UUID | None = None  # modelo escolhido na mão: devolve o mapeamento dele mesmo se fraco


@api.post("/batch/identify", tags=["batch"])
def batch_identify(body: IdentifyIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    """Tabela colada (cabeçalho + primeiras linhas) → qual modelo ela preenche e como mapear as colunas."""
    return identify.identify(ctx, body.headers, body.rows, generator_id=body.generator_id)


class MappingIn(BaseModel):
    mapping: list[str | None]


@api.post("/generators/{generator_id}/batch/imports/{import_id}/apply", tags=["batch"])
def import_apply(
    generator_id: uuid.UUID, import_id: uuid.UUID, body: MappingIn, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    from sqlalchemy import select

    _, defs = _batch_defs(ctx, generator_id)
    row = ctx.db.scalar(
        select(BatchImport).where(
            BatchImport.id == import_id,
            BatchImport.workspace_id == ctx.workspace_id,
            BatchImport.generator_id == generator_id,
        )
    )
    if row is None or row.expires_at <= utcnow():
        raise ValidationFailed("Importação expirada. Envie o arquivo novamente.", code="IMPORT_EXPIRED")
    valid_names = {d.name for d in defs if d.include_in_batch}
    if len(body.mapping) != len(row.columns) or any(
        m is not None and m not in valid_names for m in body.mapping
    ):
        raise ValidationFailed("Mapeamento inválido.", code="INVALID_MAPPING")
    picked = [m for m in body.mapping if m]
    if len(picked) != len(set(picked)):
        raise ValidationFailed(
            "Dois campos da planilha foram mapeados para o mesmo campo.", code="INVALID_MAPPING"
        )
    out_rows = [{m: r[i] for i, m in enumerate(body.mapping) if m} for r in row.rows]
    validation = gen_service.validate_batch_endpoint(ctx, generator_id, gen_service.ValidateIn(rows=out_rows))
    ctx.db.delete(row)
    ctx.db.commit()
    return {"rows": out_rows, "validation": validation}


# ------------------------------------------------------------------ histórico, jobs, downloads


@api.get("/jobs", tags=["history"])
def list_jobs(
    kind: Literal["single", "batch", "kit"] | None = None,
    status: str | None = Query(default=None, max_length=20),
    generator_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return gen_service.list_jobs(
        ctx, kind=kind, status=status, generator_id=generator_id, page=page, page_size=page_size
    )


@api.get("/jobs/{job_id}", tags=["history"])
def get_job(job_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return gen_service.job_out(ctx, gen_service.get_job(ctx, job_id), with_files=True)


@api.get("/jobs/{job_id}/items", tags=["history"])
def job_items(
    job_id: uuid.UUID,
    status: str | None = Query(default=None, max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return gen_service.list_items(ctx, job_id, status=status, page=page, page_size=page_size)


@api.post("/jobs/{job_id}/repeat", status_code=202, tags=["history"])
def repeat_job(
    job_id: uuid.UUID, response: Response, idempotency_key: IdemHeader = None, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    job, created = gen_service.repeat_job(ctx, job_id, idempotency_key)
    response.status_code = 202 if created else 200
    return gen_service.job_out(ctx, job, with_files=True)


@api.post("/jobs/{job_id}/cancel", tags=["history"])
def cancel_job(job_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return gen_service.job_out(ctx, gen_service.cancel_job(ctx, job_id), with_files=True)


@api.post("/files/{file_id}/link", tags=["downloads"])
def file_link(file_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return gen_service.create_download_link(ctx, file_id)


@api.get("/downloads/{token}", tags=["downloads"])
def download(token: str, ctx: Ctx = Depends(get_ctx)) -> StreamingResponse:
    f = gen_service.open_download(ctx, token)
    headers = {
        "Content-Disposition": filenames.content_disposition(f.filename),
        "Content-Length": str(f.size_bytes),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(gen_service.stream_file(f), media_type=f.content_type, headers=headers)


# ------------------------------------------------------------------ kits (documentos com variáveis compartilhadas)


@api.get("/kits", tags=["kits"])
def list_kits(
    q: str | None = Query(default=None, max_length=100),
    status: Literal["archived"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: Literal["updated", "name", "created"] = "updated",
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return kits_service.list_kits(ctx, q=q, status=status, page=page, page_size=page_size, sort=sort)


@api.post("/kits", status_code=201, tags=["kits"])
def create_kit(body: kits_service.KitIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    kit = kits_service.create_kit(ctx, body.name, body.description)
    return kits_service.kit_out(ctx.db, kit)


@api.get("/kits/{kit_id}", tags=["kits"])
def get_kit(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_out(ctx.db, kits_service.get_kit(ctx.db, ctx.workspace_id, kit_id))


@api.patch("/kits/{kit_id}", tags=["kits"])
def patch_kit(kit_id: uuid.UUID, body: kits_service.KitPatch, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    kit = kits_service.update_kit(ctx, kit_id, body.model_dump(exclude_unset=True))
    return kits_service.kit_out(ctx.db, kit)


@api.delete("/kits/{kit_id}", status_code=204, tags=["kits"])
def delete_kit(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    kits_service.delete_kit(ctx, kit_id)
    return Response(status_code=204)


@api.post("/kits/{kit_id}/archive", tags=["kits"])
def archive_kit(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_out(ctx.db, kits_service.archive_kit(ctx, kit_id, True))


@api.post("/kits/{kit_id}/unarchive", tags=["kits"])
def unarchive_kit(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_out(ctx.db, kits_service.archive_kit(ctx, kit_id, False))


@api.post("/kits/{kit_id}/pin", tags=["kits"])
def pin_kit(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_out(ctx.db, kits_service.pin_kit(ctx, kit_id, True))


@api.post("/kits/{kit_id}/unpin", tags=["kits"])
def unpin_kit(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_out(ctx.db, kits_service.pin_kit(ctx, kit_id, False))


class KitItemIn(BaseModel):
    generator_id: uuid.UUID


@api.get("/kits/{kit_id}/items", tags=["kits"])
def list_kit_items(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return {"items": kits_service.list_items(ctx, kit_id)}


@api.post("/kits/{kit_id}/items", status_code=201, tags=["kits"])
def add_kit_item(kit_id: uuid.UUID, body: KitItemIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.add_item(ctx, kit_id, body.generator_id)


@api.delete("/kits/{kit_id}/items/{item_id}", status_code=204, tags=["kits"])
def remove_kit_item(kit_id: uuid.UUID, item_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    kits_service.remove_item(ctx, kit_id, item_id)
    return Response(status_code=204)


@api.put("/kits/{kit_id}/items/{item_id}/mapping", tags=["kits"])
def set_kit_item_mapping(
    kit_id: uuid.UUID, item_id: uuid.UUID, body: kits_service.ItemMappingIn, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    return kits_service.set_item_mapping(ctx, kit_id, item_id, body)


@api.post("/kits/{kit_id}/auto-detect", tags=["kits"])
def auto_detect_kit_fields(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.auto_detect(ctx, kit_id)


@api.get("/kits/{kit_id}/fields", tags=["kits"])
def list_kit_fields(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    kits_service.get_kit(ctx.db, ctx.workspace_id, kit_id)
    return {"items": kits_service.list_kit_fields_out(ctx.db, kit_id)}


@api.post("/kits/{kit_id}/fields", status_code=201, tags=["kits"])
def create_kit_field(
    kit_id: uuid.UUID, body: kits_service.KitFieldIn, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    kf = kits_service.create_kit_field(ctx, kit_id, body)
    return kits_service.kit_field_out(kf, [])


@api.patch("/kit-fields/{field_id}", tags=["kits"])
def patch_kit_field(
    field_id: uuid.UUID, body: kits_service.KitFieldPatch, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    kf = kits_service.update_kit_field(ctx, field_id, body)
    opts = kits_service.options_by_kit_field(ctx.db, [kf.id])[kf.id]
    return kits_service.kit_field_out(kf, opts)


@api.delete("/kit-fields/{field_id}", status_code=204, tags=["kits"])
def delete_kit_field(field_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    kits_service.delete_kit_field(ctx, field_id)
    return Response(status_code=204)


class KitFieldOptionsIn(BaseModel):
    options: list[fields_service.OptionIn]


@api.put("/kit-fields/{field_id}/options", tags=["kits"])
def put_kit_field_options(
    field_id: uuid.UUID, body: KitFieldOptionsIn, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    opts = kits_service.replace_kit_field_options(ctx, field_id, body.options)
    return {"options": [{"id": str(o.id), "label": o.label, "value": o.value} for o in opts]}


@api.get("/kits/{kit_id}/form", tags=["kits"])
def get_kit_form(kit_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_form(ctx, kit_id)


@api.post("/kits/{kit_id}/runs", status_code=202, tags=["kits"])
def create_kit_run(
    kit_id: uuid.UUID,
    body: kits_service.KitRunIn,
    response: Response,
    idempotency_key: IdemHeader = None,
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    run, created = kits_service.create_kit_run(ctx, kit_id, body, idempotency_key)
    response.status_code = 202 if created else 200
    response.headers["Idempotent-Replayed"] = "false" if created else "true"
    return kits_service.kit_run_out(ctx, run)


@api.get("/kit-runs", tags=["kits"])
def list_kit_runs(
    kit_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return kits_service.list_kit_runs(ctx, kit_id=kit_id, page=page, page_size=page_size)


@api.get("/kit-runs/{run_id}", tags=["kits"])
def get_kit_run(run_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return kits_service.kit_run_out(ctx, kits_service.get_kit_run(ctx, run_id))
