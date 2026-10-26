"""Assinatura eletrônica (D40): gerou, mandou assinar, voltou assinado para o histórico.

* Provedor por espaço de trabalho (só o proprietário configura): token da API e segredo de webhook cifrados (Fernet),
  chave aleatória da URL do webhook guardada só como SHA-256 e mostrada uma vez.
* Envio a partir de um PDF gerado: cria o envelope no provedor e guarda o pedido (`signature_requests`).
* Webhook verificado (assinatura/segredo do provedor) e idempotente (`signature_events`). O corpo do webhook só
  dispara a consulta: a situação vem sempre da API do provedor, e um pedido concluído nunca volta atrás.
* Consulta periódica no worker como reserva do webhook.
* Assinado → o PDF é baixado (anti-SSRF, com teto) e guardado como arquivo da geração (tipo `signed`).
* gov.br / ICP-Brasil fora do app: fluxo assistido. O signatário assina no Assinador do ITI, o PDF volta por upload
  e as assinaturas PAdES são verificadas no `pdfconv` (o PDF de fora não é aberto na API).
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import queue
from app.adapters.storage import get_storage
from app.core import crypto, ratelimit
from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.errors import (
    AppError,
    Conflict,
    Forbidden,
    LimitExceeded,
    NotFound,
    Unauthorized,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.security import new_token, token_hash
from app.db.base import utcnow
from app.db.models import GeneratedFile, SignatureEvent, SignatureProviderConfig, SignatureRequest
from app.db.models.signatures import API_PROVIDERS, FINAL_STATUS
from app.db.session import get_factory
from app.modules.audit import service as audit
from app.modules.fields.validators import digits, is_valid_cpf
from app.modules.signatures import pades, providers
from app.modules.signatures.base import EnvelopeOptions, ProviderError, Signer, WebhookRejected
from app.modules.signatures.zapsign import WEBHOOK_HEADER

log = get_logger(__name__)

SIGNERS_MAX = 20
WEBHOOK_MAX_BYTES = 1024 * 1024
WEBHOOKS_PER_MINUTE_IP = 120
CREATES_PER_HOUR = 30
POLL_BATCH = 50
POLL_MAX_AGE_DAYS = 90
_POLL_EVERY_S = 300
_last_poll = 0.0
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PROVIDER_MESSAGES = {
    "SIGNATURE_PROVIDER_AUTH": "O provedor recusou o token. Confira o token e o ambiente (sandbox ou produção).",
    "SIGNATURE_PROVIDER_BUSY": "O provedor está ocupado agora. Tente de novo em instantes.",
    "SIGNATURE_PROVIDER_NOT_FOUND": "O provedor não encontrou este documento.",
}


def _provider_message(code: str) -> str:
    return PROVIDER_MESSAGES.get(code, "O provedor de assinatura não respondeu como esperado. Tente de novo.")


class SignatureProviderFailed(AppError):
    status_code = 502

    def __init__(self, exc: ProviderError) -> None:
        super().__init__(_provider_message(exc.code), code=exc.code)


# ------------------------------------------------------------------ entradas


class SignerIn(BaseModel):
    name: str = PField(min_length=2, max_length=120)
    email: str = PField(min_length=3, max_length=254)
    phone: str | None = PField(default=None, max_length=20)
    cpf: str | None = PField(default=None, max_length=14)
    order: int = PField(default=1, ge=1, le=SIGNERS_MAX)
    auth: Literal["email", "sms", "whatsapp"] = "email"


class SignatureIn(BaseModel):
    file_id: uuid.UUID
    provider: Literal["zapsign", "clicksign", "govbr"]
    signers: list[SignerIn] = PField(default_factory=list, max_length=SIGNERS_MAX)
    message: str | None = PField(default=None, max_length=1000)
    sequential: bool = False


class ProviderIn(BaseModel):
    environment: Literal["sandbox", "production"] = "sandbox"
    api_token: str | None = PField(default=None, min_length=8, max_length=500)
    # Clicksign: o segredo HMAC que a Clicksign mostra ao criar o webhook. ZapSign: gerado aqui.
    webhook_secret: str | None = PField(default=None, min_length=8, max_length=500)
    rotate_webhook: bool = False


def _signer(s: SignerIn) -> Signer:
    name = " ".join(s.name.split())
    email = s.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValidationFailed(f"E-mail inválido para {name}.", code="SIGNATURE_INVALID_SIGNER")
    phone = digits(s.phone or "")
    if phone.startswith("55") and len(phone) in (12, 13):
        phone = phone[2:]
    if phone and len(phone) not in (10, 11):
        raise ValidationFailed(f"Celular inválido para {name} (use DDD + número).", code="SIGNATURE_INVALID_SIGNER")
    if s.auth != "email" and not phone:
        raise ValidationFailed(f"Informe o celular de {name} para o código por SMS/WhatsApp.", code="SIGNATURE_INVALID_SIGNER")
    cpf = digits(s.cpf or "")
    if cpf and not is_valid_cpf(cpf):
        raise ValidationFailed(f"CPF inválido para {name}.", code="SIGNATURE_INVALID_SIGNER")
    return Signer(name=name, email=email, phone=phone or None, cpf=cpf or None, order=s.order, auth=s.auth)


def _mask_cpf(cpf: str | None) -> str | None:
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**" if cpf else None


# ------------------------------------------------------------------ provedores (configuração do espaço)


def _require_owner(ctx: Ctx) -> None:
    if not ctx.is_owner:
        raise Forbidden("Só o proprietário do espaço configura a assinatura eletrônica.")


def _config(db: Session, workspace_id: uuid.UUID, provider: str) -> SignatureProviderConfig | None:
    return db.scalar(
        select(SignatureProviderConfig).where(
            SignatureProviderConfig.workspace_id == workspace_id, SignatureProviderConfig.provider == provider
        )
    )


def webhook_url(provider: str, key: str) -> str:
    base = get_settings().public_web_url.rstrip("/")
    return f"{base}/api/v1/signatures/webhook/{provider}/{key}"


def provider_out(cfg: SignatureProviderConfig) -> dict[str, Any]:
    return {
        "provider": cfg.provider,
        "label": providers.LABELS[cfg.provider],
        "environment": cfg.environment,
        "credential_hint": cfg.credential_hint,
        "webhook_ready": cfg.webhook_secret_enc is not None,
        "last_tested_at": cfg.last_tested_at.isoformat() if cfg.last_tested_at else None,
        "last_test_ok": cfg.last_test_ok,
        "updated_at": cfg.updated_at.isoformat(),
    }


def list_providers(ctx: Ctx) -> dict[str, Any]:
    rows = ctx.db.scalars(
        select(SignatureProviderConfig).where(SignatureProviderConfig.workspace_id == ctx.workspace_id)
    ).all()
    return {
        "configured": [provider_out(c) for c in rows],
        "available": [{"provider": p, "label": providers.LABELS[p], "needs_setup": p in API_PROVIDERS}
                      for p in (*API_PROVIDERS, "govbr")],
        "encryption_ready": crypto.available(),
    }


def configure_provider(ctx: Ctx, provider: str, body: ProviderIn) -> dict[str, Any]:
    """Cria ou atualiza o provedor do espaço. Segredos gerados aqui (chave da URL e, na ZapSign, o segredo do
    cabeçalho) aparecem só nesta resposta."""
    _require_owner(ctx)
    if provider not in API_PROVIDERS:
        raise NotFound("Provedor")
    db = ctx.db
    cfg = _config(db, ctx.workspace_id, provider)
    if cfg is None and not body.api_token:
        raise ValidationFailed("Informe o token da API do provedor.", code="SIGNATURE_TOKEN_REQUIRED")
    out_extra: dict[str, Any] = {}
    new_cfg = cfg is None
    if cfg is None:
        cfg = SignatureProviderConfig(workspace_id=ctx.workspace_id, provider=provider, created_by=ctx.user.id)
        db.add(cfg)
    cfg.environment = body.environment
    if body.api_token:
        token = body.api_token.strip()
        cfg.credentials_enc = crypto.encrypt_json({"api_token": token})
        cfg.credential_hint = f"…{token[-4:]}"
        cfg.last_tested_at, cfg.last_test_ok = None, None
    if new_cfg or body.rotate_webhook:
        key = new_token(32)
        cfg.webhook_key_hash = token_hash(key)
        out_extra["webhook_url"] = webhook_url(provider, key)
        if provider == "zapsign":  # a ZapSign não assina o corpo: o segredo vai num cabeçalho do webhook
            secret = new_token(24)
            cfg.webhook_secret_enc = crypto.encrypt_text(secret)
            out_extra["webhook_header"] = {"name": WEBHOOK_HEADER, "value": secret}
    if body.webhook_secret and provider == "clicksign":
        cfg.webhook_secret_enc = crypto.encrypt_text(body.webhook_secret.strip())
    db.flush()
    audit.record(
        db,
        "signature.provider_configured",
        ctx=ctx,
        entity_type="signature_provider",
        entity_id=cfg.id,
        meta={"provider": provider, "environment": body.environment, "webhook_rotated": "webhook_url" in out_extra},
    )
    db.commit()
    return {**provider_out(cfg), **out_extra}


def _adapter(cfg: SignatureProviderConfig):  # type: ignore[no-untyped-def]
    token = str(crypto.decrypt_json(cfg.credentials_enc).get("api_token") or "")
    return providers.build(cfg.provider, token, cfg.environment)


def test_provider(ctx: Ctx, provider: str) -> dict[str, Any]:
    """"Testar conexão": nunca devolve nem registra a credencial, só se deu certo e o código do erro."""
    _require_owner(ctx)
    cfg = _config(ctx.db, ctx.workspace_id, provider)
    if cfg is None:
        raise NotFound("Provedor")
    ratelimit.check(f"signature-test:{ctx.workspace_id}", 10, 60)
    ok, code = True, None
    try:
        _adapter(cfg).test_connection()
    except ProviderError as exc:
        ok, code = False, exc.code
        log.info("assinatura_teste_falhou", extra={"provider": provider, "code": exc.code})
    cfg.last_tested_at, cfg.last_test_ok = utcnow(), ok
    ctx.db.commit()
    return {"ok": ok, "code": code, "message": "Conexão funcionando." if ok else _provider_message(code or "")}


def delete_provider(ctx: Ctx, provider: str) -> None:
    _require_owner(ctx)
    cfg = _config(ctx.db, ctx.workspace_id, provider)
    if cfg is None:
        raise NotFound("Provedor")
    audit.record(ctx.db, "signature.provider_removed", ctx=ctx, entity_type="signature_provider",
                 entity_id=cfg.id, meta={"provider": provider})
    ctx.db.delete(cfg)
    ctx.db.commit()


# ------------------------------------------------------------------ pedidos de assinatura


def _file_out(f: GeneratedFile | None) -> dict[str, Any] | None:
    if f is None or f.deleted_at is not None:
        return None
    from app.modules.generation.service import file_out

    return file_out(f)


def request_out(db: Session, req: SignatureRequest) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(req.id),
        "provider": req.provider,
        "label": providers.LABELS[req.provider],
        "status": req.status,
        "provider_status": req.provider_status,
        "job_id": str(req.job_id),
        "source_file_id": str(req.source_file_id) if req.source_file_id else None,
        "signed_file": _file_out(db.get(GeneratedFile, req.signed_file_id)) if req.signed_file_id else None,
        "signers": list(req.signers or []),
        "message": req.message,
        "error_code": req.error_code,
        "verification": req.verification,
        "created_at": req.created_at.isoformat(),
        "sent_at": req.sent_at.isoformat() if req.sent_at else None,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
        "last_synced_at": req.last_synced_at.isoformat() if req.last_synced_at else None,
    }
    if req.provider == "govbr":
        out["instructions"] = {"signer_url": pades.SIGNER_URL, "verify_url": pades.VERIFY_URL}
    return out


def _source_file(ctx: Ctx, file_id: uuid.UUID) -> GeneratedFile:
    f = ctx.db.scalar(
        select(GeneratedFile).where(
            GeneratedFile.id == file_id,
            GeneratedFile.workspace_id == ctx.workspace_id,
            GeneratedFile.deleted_at.is_(None),
            GeneratedFile.job_id.is_not(None),
        )
    )
    if f is None or f.expires_at <= utcnow():
        raise NotFound("Arquivo")
    if f.kind != "pdf":
        raise ValidationFailed("Para mandar assinar, gere o documento em PDF.", code="SIGNATURE_NEEDS_PDF")
    return f


def _month_count(db: Session, workspace_id: uuid.UUID) -> int:
    from app.modules.billing.service import month_start

    return int(
        db.scalar(
            select(func.count(SignatureRequest.id)).where(
                SignatureRequest.workspace_id == workspace_id,
                SignatureRequest.created_at >= month_start(),
                SignatureRequest.status != "error",  # envio que o provedor recusou não conta
            )
        )
        or 0
    )


def create_signature(ctx: Ctx, body: SignatureIn) -> dict[str, Any]:
    db = ctx.db
    ratelimit.check(f"signature-create:{ctx.user.id}", CREATES_PER_HOUR, 3600)
    if _month_count(db, ctx.workspace_id) >= ctx.limit("max_signatures_per_month"):
        raise LimitExceeded("O limite de envios para assinatura deste mês acabou.", code="SIGNATURE_LIMIT")
    source = _source_file(ctx, body.file_id)
    signers = [_signer(s) for s in body.signers]
    if len({s.email for s in signers}) != len(signers):
        raise ValidationFailed("Há signatários com o mesmo e-mail.", code="SIGNATURE_INVALID_SIGNER")
    cfg = None
    if body.provider in API_PROVIDERS:
        if not signers:
            raise ValidationFailed("Informe quem vai assinar.", code="SIGNATURE_NO_SIGNERS")
        cfg = _config(db, ctx.workspace_id, body.provider)
        if cfg is None:
            raise Conflict(
                "Configure o provedor em Configurações → Assinatura eletrônica.",
                code="SIGNATURE_PROVIDER_NOT_CONFIGURED",
            )
    req = SignatureRequest(
        workspace_id=ctx.workspace_id,
        provider=body.provider,
        provider_config_id=cfg.id if cfg else None,
        job_id=source.job_id,
        source_file_id=source.id,
        status="awaiting_upload" if cfg is None else "sent",
        signers=[
            {"name": s.name, "email": s.email, "phone": s.phone, "cpf": _mask_cpf(s.cpf), "order": s.order,
             "auth": s.auth, "sign_url": None, "signed": False}
            for s in signers
        ],
        message=(body.message or "").strip() or None,
        created_by=ctx.user.id,
    )
    db.add(req)
    db.flush()
    if cfg is not None:
        pdf = get_storage().get(source.storage_key)
        try:
            env = _adapter(cfg).create_envelope(
                pdf, source.filename, signers,
                EnvelopeOptions(message=req.message, sequential=body.sequential, reference=str(req.id)),
            )
        except ProviderError as exc:
            req.status, req.error_code = "error", exc.code
            log.warning("assinatura_envio_falhou", extra={"provider": body.provider, "code": exc.code})
            audit.record(db, "signature.failed", ctx=ctx, entity_type="signature_request", entity_id=req.id,
                         meta={"provider": body.provider, "code": exc.code})
            db.commit()
            raise SignatureProviderFailed(exc) from exc
        req.external_id = env.external_id
        req.provider_status = env.provider_status
        req.signers = [{**s, "sign_url": link} for s, link in zip(req.signers, env.signer_links, strict=False)]
        req.sent_at = utcnow()
    audit.record(db, "signature.create", ctx=ctx, entity_type="signature_request", entity_id=req.id,
                 meta={"provider": body.provider, "signers": len(signers)})
    db.commit()
    return request_out(db, req)


def _get(ctx: Ctx, request_id: uuid.UUID) -> SignatureRequest:
    req = ctx.db.scalar(
        select(SignatureRequest).where(
            SignatureRequest.id == request_id, SignatureRequest.workspace_id == ctx.workspace_id
        )
    )
    if req is None:
        raise NotFound("Pedido de assinatura")
    return req


def get_signature(ctx: Ctx, request_id: uuid.UUID) -> dict[str, Any]:
    return request_out(ctx.db, _get(ctx, request_id))


def list_signatures(
    ctx: Ctx, *, job_id: uuid.UUID | None = None, page: int = 1, page_size: int = 20
) -> dict[str, Any]:
    q = select(SignatureRequest).where(SignatureRequest.workspace_id == ctx.workspace_id)
    if job_id:
        q = q.where(SignatureRequest.job_id == job_id)
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = ctx.db.scalars(
        q.order_by(SignatureRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [request_out(ctx.db, r) for r in rows], "total": total, "page": page, "page_size": page_size}


def cancel_signature(ctx: Ctx, request_id: uuid.UUID) -> dict[str, Any]:
    req = _get(ctx, request_id)
    if req.status in FINAL_STATUS:
        raise Conflict("Este pedido já foi concluído.", code="SIGNATURE_FINISHED")
    if req.provider in API_PROVIDERS and req.external_id and req.status == "sent":
        cfg = ctx.db.get(SignatureProviderConfig, req.provider_config_id) if req.provider_config_id else None
        if cfg is None:
            raise Conflict("O provedor deste pedido foi removido.", code="SIGNATURE_PROVIDER_NOT_CONFIGURED")
        try:
            _adapter(cfg).cancel(req.external_id)
        except ProviderError as exc:
            raise SignatureProviderFailed(exc) from exc
    req.status, req.completed_at = "cancelled", utcnow()
    audit.record(ctx.db, "signature.cancel", ctx=ctx, entity_type="signature_request", entity_id=req.id,
                 meta={"provider": req.provider})
    ctx.db.commit()
    return request_out(ctx.db, req)


def refresh_signature(ctx: Ctx, request_id: uuid.UUID) -> dict[str, Any]:
    req = _get(ctx, request_id)
    ratelimit.check(f"signature-refresh:{req.id}", 6, 60)
    ctx.db.commit()  # fecha a leitura desta sessão antes da consulta, que grava em outra
    sync_request(req.id)
    ctx.db.expire_all()
    return request_out(ctx.db, _get(ctx, request_id))


# ------------------------------------------------------------------ PDF assinado → arquivo da geração


def _looks_like_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def _store_signed(db: Session, req: SignatureRequest, data: bytes) -> GeneratedFile:
    source = db.get(GeneratedFile, req.source_file_id) if req.source_file_id else None
    stem = (source.filename.rsplit(".", 1)[0] if source else "documento")[:230]
    key = f"w/{req.workspace_id}/sig/{req.id}/{uuid.uuid4().hex}.pdf"
    get_storage().put(key, data, "application/pdf")
    gf = GeneratedFile(
        workspace_id=req.workspace_id,
        job_id=req.job_id,
        item_id=source.item_id if source else None,
        kind="signed",
        filename=f"{stem}-assinado.pdf",
        storage_key=key,
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        expires_at=utcnow() + timedelta(days=get_settings().file_retention_days),
    )
    db.add(gf)
    db.flush()
    return gf


def sync_request(request_id: uuid.UUID | str) -> None:
    """Consulta a situação no provedor e aplica: nunca regride um pedido concluído; assinado → baixa e guarda o PDF.
    Roda no worker (webhook, consulta periódica) ou na hora ("atualizar")."""
    rid = uuid.UUID(str(request_id))
    with get_factory()() as db:
        req = db.get(SignatureRequest, rid)
        if req is None or req.status in FINAL_STATUS or req.provider not in API_PROVIDERS or not req.external_id:
            return
        cfg = db.get(SignatureProviderConfig, req.provider_config_id) if req.provider_config_id else None
        if cfg is None:
            return
        req.last_synced_at = utcnow()
        try:
            adapter = _adapter(cfg)
            st = adapter.status(req.external_id)
            req.provider_status = st.provider_status
            if st.signed_by:
                req.signers = [{**s, "signed": s.get("email") in st.signed_by or s.get("signed", False)}
                               for s in req.signers or []]
            if st.status == "signed":
                doc = adapter.download_signed(req.external_id)
                if not _looks_like_pdf(doc.pdf):
                    raise ProviderError("SIGNATURE_BAD_FILE", 200)
                gf = _store_signed(db, req, doc.pdf)
                # duas consultas ao mesmo tempo: só a primeira grava o arquivo no pedido
                won = db.execute(
                    update(SignatureRequest)
                    .where(SignatureRequest.id == req.id, SignatureRequest.signed_file_id.is_(None))
                    .values(signed_file_id=gf.id, status="signed", completed_at=utcnow())
                ).rowcount
                if not won:
                    db.delete(gf)
                    get_storage().delete(gf.storage_key)
                else:
                    audit.record(db, "signature.signed", workspace_id=req.workspace_id,
                                 entity_type="signature_request", entity_id=req.id, meta={"provider": req.provider})
            elif st.status in FINAL_STATUS:
                req.status, req.completed_at = st.status, utcnow()
                audit.record(db, f"signature.{st.status}", workspace_id=req.workspace_id,
                             entity_type="signature_request", entity_id=req.id, meta={"provider": req.provider})
        except ProviderError as exc:
            log.warning("assinatura_consulta_falhou", extra={"provider": req.provider, "code": exc.code})
        except crypto.EncryptionUnavailable:
            log.error("assinatura_sem_chave_de_criptografia", extra={"provider": req.provider})
        db.commit()


def poll_signatures() -> int:
    """Reserva do webhook: enfileira a consulta dos pedidos em aberto sem notícia há SIGNATURE_POLL_MINUTES."""
    s = get_settings()
    now = utcnow()
    stale = now - timedelta(minutes=s.signature_poll_minutes)
    with get_factory()() as db:
        ids = db.scalars(
            select(SignatureRequest.id)
            .where(
                SignatureRequest.status == "sent",
                SignatureRequest.provider.in_(API_PROVIDERS),
                SignatureRequest.provider_config_id.is_not(None),
                SignatureRequest.created_at >= now - timedelta(days=POLL_MAX_AGE_DAYS),
                (SignatureRequest.last_synced_at.is_(None)) | (SignatureRequest.last_synced_at <= stale),
            )
            .order_by(SignatureRequest.last_synced_at.asc().nulls_first())
            .limit(POLL_BATCH)
        ).all()
    for rid in ids:
        queue.enqueue("signature_sync", request_id=str(rid))
    return len(ids)


def poll_signatures_throttled() -> None:
    global _last_poll
    if time.monotonic() - _last_poll < _POLL_EVERY_S:
        return
    _last_poll = time.monotonic()
    poll_signatures()


# ------------------------------------------------------------------ webhook


def _ip_key(ip: str | None) -> str:
    import hmac

    return hmac.new(get_settings().secret_key.encode(), (ip or "na").encode(), hashlib.sha256).hexdigest()[:24]


def handle_webhook(
    db: Session, provider: str, key: str, headers: dict[str, str], body: bytes, ip: str | None
) -> dict[str, Any]:
    """Webhook do provedor. Chave errada → 404 igual; assinatura errada → 401 (nada é gravado); evento repetido →
    200 sem efeito; o evento só dispara a consulta à API do provedor."""
    ratelimit.check(f"signature-webhook:{_ip_key(ip)}", WEBHOOKS_PER_MINUTE_IP, 60)
    if provider not in API_PROVIDERS or not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", key or ""):
        raise NotFound("Webhook")
    cfg = db.scalar(
        select(SignatureProviderConfig).where(
            SignatureProviderConfig.webhook_key_hash == token_hash(key), SignatureProviderConfig.provider == provider
        )
    )
    if cfg is None:
        raise NotFound("Webhook")
    secret = crypto.decrypt_text(cfg.webhook_secret_enc) if cfg.webhook_secret_enc else None
    try:
        event = providers.ADAPTERS[provider].parse_webhook(headers, body, secret)
    except WebhookRejected as exc:
        log.warning("assinatura_webhook_recusado", extra={"provider": provider})
        raise Unauthorized("Assinatura do webhook inválida.") from exc
    req = None
    if event.external_id:
        req = db.scalar(
            select(SignatureRequest).where(
                SignatureRequest.workspace_id == cfg.workspace_id,
                SignatureRequest.provider == provider,
                SignatureRequest.external_id == event.external_id,
            )
        )
    db.add(SignatureEvent(provider=provider, event_key=event.event_key, event_type=event.event_type,
                          request_id=req.id if req else None))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate"}
    if req is not None:
        req.last_event_at = event.occurred_at or utcnow()
    db.commit()
    if req is not None and req.status not in FINAL_STATUS:
        queue.enqueue("signature_sync", request_id=str(req.id))
    return {"status": "ok"}


# ------------------------------------------------------------------ gov.br / ICP-Brasil: PDF assinado fora do app


def upload_signed(ctx: Ctx, request_id: uuid.UUID, data: bytes) -> dict[str, Any]:
    """O PDF assinado no Assinador do gov.br (ou com certificado ICP-Brasil) volta por aqui. As assinaturas são
    verificadas no pdfconv; o arquivo só entra no histórico se todas estiverem íntegras."""
    req = _get(ctx, request_id)
    if req.provider != "govbr" or req.status != "awaiting_upload":
        raise Conflict("Este pedido não espera um PDF assinado.", code="SIGNATURE_NOT_AWAITING_UPLOAD")
    ratelimit.check(f"signature-upload:{req.id}", 10, 3600)
    if not data or not _looks_like_pdf(data):
        raise ValidationFailed("Envie o PDF assinado.", code="NOT_A_PDF")
    result = pades.verify(data)
    sigs = [s for s in result.get("signatures") or [] if isinstance(s, dict)]
    if not sigs:
        raise ValidationFailed(
            "Este PDF não tem assinatura digital. Assine no Assinador do gov.br e envie o arquivo que ele gerar.",
            code="SIGNATURE_NOT_FOUND",
        )
    if not all(s.get("intact") and s.get("valid") for s in sigs):
        raise ValidationFailed(
            "Uma das assinaturas não confere: o arquivo foi alterado depois de assinado ou a assinatura está corrompida.",
            code="SIGNATURE_INVALID",
        )
    source = ctx.db.get(GeneratedFile, req.source_file_id) if req.source_file_id else None
    matches = None
    if source is not None and source.deleted_at is None:
        # o assinador acrescenta a assinatura ao fim do arquivo (atualização incremental): o original fica intacto
        matches = data.startswith(get_storage().get(source.storage_key))
    gf = _store_signed(ctx.db, req, data)
    req.signed_file_id = gf.id
    req.status, req.completed_at = "signed", utcnow()
    req.verification = {
        "signatures": [{k: s.get(k) for k in ("signer", "cpf", "issuer", "signed_at", "timestamped", "intact", "valid",
                                               "trusted", "covers_whole_file")} for s in sigs],
        "matches_original": matches,
        "chain_checked": bool(result.get("trust_roots")),
        "verified_at": utcnow().isoformat(),
    }
    audit.record(ctx.db, "signature.uploaded", ctx=ctx, entity_type="signature_request", entity_id=req.id,
                 meta={"signatures": len(sigs), "matches_original": matches})
    ctx.db.commit()
    return request_out(ctx.db, req)
