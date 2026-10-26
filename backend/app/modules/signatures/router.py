"""Rotas da assinatura eletrônica (D40). O webhook é público (sem sessão nem CSRF) e só confia na verificação do
provedor; a chave da URL é mascarada no log de acesso (`app.core.logging`)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUpload
from starlette.exceptions import HTTPException

from app.core.config import get_settings
from app.core.deps import Ctx, client_ip, get_ctx, read_body_capped
from app.core.errors import AppError, ValidationFailed
from app.db.session import get_factory
from app.modules.signatures import service

router = APIRouter(prefix="/signatures", tags=["signatures"])


@router.get("/providers")
def list_providers(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.list_providers(ctx)


@router.put("/providers/{provider}")
def configure_provider(provider: str, body: service.ProviderIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    """Só o proprietário. A URL do webhook (e, na ZapSign, o cabeçalho secreto) aparece só nesta resposta."""
    return service.configure_provider(ctx, provider, body)


@router.post("/providers/{provider}/test")
def test_provider(provider: str, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.test_provider(ctx, provider)


@router.delete("/providers/{provider}", status_code=204)
def delete_provider(provider: str, ctx: Ctx = Depends(get_ctx)) -> Response:
    service.delete_provider(ctx, provider)
    return Response(status_code=204)


@router.post("", status_code=201)
def create_signature(body: service.SignatureIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.create_signature(ctx, body)


@router.get("")
def list_signatures(
    job_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: Ctx = Depends(get_ctx),
) -> dict[str, Any]:
    return service.list_signatures(ctx, job_id=job_id, page=page, page_size=page_size)


@router.get("/{request_id}")
def get_signature(request_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.get_signature(ctx, request_id)


@router.post("/{request_id}/cancel")
def cancel_signature(request_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.cancel_signature(ctx, request_id)


@router.post("/{request_id}/refresh")
def refresh_signature(request_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.refresh_signature(ctx, request_id)


@router.post("/{request_id}/upload")
async def upload_signed(request_id: uuid.UUID, request: Request, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    """gov.br/ICP-Brasil: o PDF assinado fora do app (multipart `file`). Tamanho conferido antes de ler o corpo."""
    max_bytes = get_settings().signature_max_pdf_mb * 1024 * 1024
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise AppError("Envie o arquivo pelo formulário.", code="LENGTH_REQUIRED", status_code=411)
    if int(length) > max_bytes + 64 * 1024:
        raise AppError("O arquivo passa do tamanho permitido.", code="FILE_TOO_LARGE", status_code=413)
    try:
        form = await request.form(max_files=1, max_fields=1, max_part_size=1024)
    except (HTTPException, ValueError) as exc:  # MultipartParseError é ValueError; o Starlette embrulha em 400
        raise AppError("Não foi possível ler o envio. Tente de novo.", code="FORM_INVALID", status_code=400) from exc
    try:
        upload = form.get("file")
        if not isinstance(upload, StarletteUpload):
            raise ValidationFailed("Envie o PDF assinado.", code="NOT_A_PDF")
        data = await upload.read(max_bytes + 1)
    finally:
        await form.close()
    if len(data) > max_bytes:
        raise AppError("O arquivo passa do tamanho permitido.", code="FILE_TOO_LARGE", status_code=413)
    return await run_in_threadpool(service.upload_signed, ctx, request_id, data)


@router.post("/webhook/{provider}/{key}", include_in_schema=False)
async def webhook(provider: str, key: str, request: Request) -> dict[str, Any]:
    body = await read_body_capped(request, service.WEBHOOK_MAX_BYTES)
    headers = dict(request.headers)
    ip = client_ip(request)

    def run() -> dict[str, Any]:
        with get_factory()() as db:
            return service.handle_webhook(db, provider, key, headers, body, ip)

    return await run_in_threadpool(run)
