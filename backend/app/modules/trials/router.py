"""Rotas do teste grátis (D38). Públicas (sem sessão) sob /public/trials; o `claim` exige sessão."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.deps import Ctx, client_ip, get_ctx, require_same_origin
from app.core.errors import AppError, ServiceUnavailable, ValidationFailed
from app.db.session import get_db, get_factory
from app.modules.trials import service

public = APIRouter(prefix="/public/trials", tags=["public"])
private = APIRouter(tags=["trials"])

FORM_OVERHEAD = 64 * 1024  # cabeçalhos do multipart + token do Turnstile + campos pequenos


@public.get("/config")
def trial_config() -> dict[str, Any]:
    return service.public_config()


@public.post("", status_code=202, dependencies=[Depends(require_same_origin)])
async def create_trial(request: Request) -> dict[str, Any]:
    """multipart: `file` (.docx ou PDF digitado), `turnstile_token` (se o Turnstile estiver ligado) e `website`
    (campo-armadilha: fica vazio para pessoas). O tamanho é conferido ANTES de ler o corpo."""
    s = get_settings()
    if not s.trials_on:
        raise ServiceUnavailable("O teste grátis está desligado no momento.", code="TRIAL_DISABLED")
    max_bytes = s.trial_max_mb * 1024 * 1024
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise AppError("Envie o arquivo pelo formulário da página.", code="LENGTH_REQUIRED", status_code=411)
    if int(length) > max_bytes + FORM_OVERHEAD:
        raise AppError(
            f"O teste aceita arquivos de até {s.trial_max_mb} MB.", code="FILE_TOO_LARGE", status_code=413
        )
    form = await request.form(max_files=1, max_fields=4, max_part_size=16 * 1024)
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ValidationFailed("Escolha o documento para testar.", code="TRIAL_FILE_MISSING")
        data = await upload.read(max_bytes + 1)
        filename = upload.filename or ""
        token = form.get("turnstile_token")
        honeypot = form.get("website")
    finally:
        await form.close()
    ip = client_ip(request)

    def run() -> dict[str, Any]:
        with get_factory()() as db:
            return service.create_trial(
                db,
                ip=ip,
                filename=filename,
                data=data,
                turnstile_token=token if isinstance(token, str) else None,
                honeypot=honeypot if isinstance(honeypot, str) else None,
            )

    return await run_in_threadpool(run)


@public.get("/{token}")
def trial_status(token: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_status(db, token, client_ip(request))


@private.post("/trials/{token}/claim", status_code=201)
def claim_trial(token: str, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    """Depois do cadastro/login: o documento do teste vira um modelo da conta, já com as sugestões."""
    return service.claim(ctx, token)
