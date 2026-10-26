"""Rotas do link para o cliente preencher (D39). Públicas (sem sessão) sob /public/requests/{token}."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUpload
from starlette.exceptions import HTTPException

from app.core.deps import Ctx, client_ip, get_ctx, read_body_capped, require_same_origin
from app.core.errors import AppError, ValidationFailed
from app.db.session import get_db, get_factory
from app.modules.assist import service as assist_service
from app.modules.requests import service

private = APIRouter(tags=["client-requests"])
public = APIRouter(prefix="/public/requests", tags=["public"])


@private.post("/generators/{generator_id}/client-requests", status_code=201)
def create_for_generator(
    generator_id: uuid.UUID, body: service.RequestIn, ctx: Ctx = Depends(get_ctx)
) -> dict[str, Any]:
    """Cria o link. O token aparece só nesta resposta (`url`); no banco fica o hash."""
    return service.create_request(ctx, body, generator_id=generator_id)


@private.post("/kits/{kit_id}/client-requests", status_code=201)
def create_for_kit(kit_id: uuid.UUID, body: service.RequestIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.create_request(ctx, body, kit_id=kit_id)


@private.get("/client-requests")
def list_requests(
    generator_id: uuid.UUID | None = None,
    kit_id: uuid.UUID | None = None,
    state: Literal["open", "answered", "expired", "cancelled"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return service.list_requests(
        ctx, generator_id=generator_id, kit_id=kit_id, state=state, page=page, page_size=page_size
    )


@private.get("/client-requests/summary")
def requests_summary(ctx: Ctx = Depends(get_ctx)) -> dict[str, int]:
    return service.summary(ctx)


@private.get("/client-requests/{request_id}")
def open_request(request_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    """Abre a resposta (com os valores). Depois de aberta, o cliente não consegue mais alterar o envio."""
    return service.open_request(ctx, request_id)


@private.post("/client-requests/{request_id}/cancel")
def cancel_request(request_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.cancel_request(ctx, request_id)


@private.post("/client-requests/{request_id}/used")
def mark_used(request_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.mark_used(ctx, request_id)


# ------------------------------------------------------------------ público (o cliente)


@public.get("/{token}")
def view(token: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.public_view(db, token, client_ip(request))


@public.post("/{token}", dependencies=[Depends(require_same_origin)])
async def submit(token: str, request: Request) -> dict[str, Any]:
    """Resposta do cliente. Rota pública: o corpo é lido com teto (SUBMIT_MAX_BYTES) antes de virar JSON, para
    um corpo enorme não ocupar a memória da API mesmo com token inválido."""
    raw = await read_body_capped(request, service.SUBMIT_MAX_BYTES)
    try:
        body = service.SubmitIn.model_validate_json(raw)
    except ValueError as exc:  # JSON quebrado ou fora do formato (ValidationError é ValueError)
        raise AppError(
            "Não foi possível ler o envio. Tente de novo.", code="FORM_INVALID", status_code=400
        ) from exc
    ip = client_ip(request)

    def run() -> dict[str, Any]:
        with get_factory()() as db:
            return service.public_submit(db, token, ip, body)

    return await run_in_threadpool(run)


@public.post("/{token}/fill-files", dependencies=[Depends(require_same_origin)])
async def fill_files(token: str, request: Request) -> dict[str, Any]:
    """Foto ou PDF do documento do cliente → valores dos campos pedidos (D37), no máximo 3 arquivos por vez.
    multipart `files`. Antes de ler o corpo: tamanho pelo Content-Length, limites por IP e por link e o próprio
    link (válido, aberto, com fotos permitidas) — token inválido não faz a API receber 24 MB."""
    max_file = assist_service.MAX_FILE_BYTES
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise AppError(
            "Envie os arquivos pelo formulário da página.", code="LENGTH_REQUIRED", status_code=411
        )
    if int(length) > service.PHOTO_FILES_PER_READ * max_file + 64 * 1024:
        raise AppError("Os arquivos passam do tamanho permitido.", code="FILE_TOO_LARGE", status_code=413)
    ip = client_ip(request)

    def precheck() -> None:
        with get_factory()() as db:
            service.public_read_precheck(db, token, ip)

    await run_in_threadpool(precheck)
    try:
        form = await request.form(max_files=service.PHOTO_FILES_PER_READ, max_fields=2, max_part_size=1024)
    except (HTTPException, ValueError) as exc:  # arquivos demais ou multipart quebrado (QA-3)
        if isinstance(exc, HTTPException) and "files" in str(exc.detail).lower():
            raise ValidationFailed(
                f"Envie no máximo {service.PHOTO_FILES_PER_READ} arquivos por vez.", code="AI_TOO_MANY_FILES"
            ) from exc
        raise AppError(
            "Não foi possível ler o envio. Tente de novo.", code="FORM_INVALID", status_code=400
        ) from exc
    try:
        uploads = [f for f in form.getlist("files") if isinstance(f, StarletteUpload)]
        if not uploads:
            raise ValidationFailed("Envie a foto ou o PDF do documento.", code="AI_FILE_EMPTY")
        data: list[bytes] = []
        for f in uploads:
            chunk = await f.read(max_file + 1)
            if len(chunk) > max_file:
                raise ValidationFailed("Cada arquivo pode ter até 8 MB.", code="FILE_TOO_LARGE")
            data.append(chunk)
    finally:
        await form.close()

    def run() -> dict[str, Any]:
        with get_factory()() as db:
            return service.public_read_files(db, token, ip, data)

    return await run_in_threadpool(run)
