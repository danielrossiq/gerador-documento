"""Link para o cliente preencher (D39): o profissional pede dados, o cliente preenche (ou manda a foto do documento)
pelo celular, o profissional confere e gera.

Lado público (`/public/requests/{token}`) tratado como hostil:

* token de 32 bytes aleatórios guardado só como SHA-256; token errado, cancelado ou de outro espaço → 404 igual;
* limites por IP (chave HMAC) e por link; o cliente vê só o nome do espaço, o nome do documento, a mensagem e os
  campos pedidos (rótulo, tipo, opções) — nada de exemplo, valor padrão ou dado de outro cliente;
* respostas validadas com as mesmas regras do formulário (normalize_value), só dos campos pedidos;
* leitura de foto/PDF pela IA (D37) na cota do espaço, no máximo REQUEST_PHOTO_READS por link e 3 arquivos por vez;
* auditoria (criação, abertura pelo cliente, envio, abertura pelo profissional, uso, cancelamento) sem os valores e
  sem o IP do cliente. A resposta é apagada quando o profissional gera com ela, ao cancelar, ou na retenção.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
import uuid
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import func, null, select, update
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import Ctx, workspace_limit
from app.core.errors import AppError, Conflict, LimitExceeded, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.security import new_token, token_hash
from app.db.base import utcnow
from app.db.models import ClientRequest, DocumentGenerator, DocumentKit, User, Workspace
from app.db.session import get_factory
from app.modules.audit import service as audit
from app.modules.fields.normalize import normalize_value
from app.modules.fields.types import FieldDef

log = get_logger(__name__)

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
MAX_VALUE_CHARS = 2000
PHOTO_FILES_PER_READ = 3
CREATES_PER_HOUR = 60
VIEWS_PER_MINUTE = 60
SUBMITS_PER_HOUR_IP = 20
SUBMITS_PER_HOUR_LINK = 30
READS_PER_HOUR_IP = 6
_PURGE_EVERY_S = 300
_last_purge = 0.0

GONE_MESSAGE = "Este link não está mais disponível. Peça um novo a quem enviou."


class RequestNotFound(AppError):
    status_code = 404
    code = "REQUEST_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__(GONE_MESSAGE)


class RequestIn(BaseModel):
    fields: list[str] = PField(default_factory=list, max_length=200)
    message: str | None = PField(default=None, max_length=1000)
    expires_days: int = PField(default=7, ge=1, le=30)
    allow_photos: bool = False
    prefill: dict[str, Any] = PField(default_factory=dict)
    prefill_mode: Literal["hidden", "readonly", "editable"] = "hidden"


class SubmitIn(BaseModel):
    values: dict[str, Any] = PField(default_factory=dict)


def _key(value: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()[:24]


def _clean_value(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int | float):
        return str(v)
    if isinstance(v, str):
        return v[:MAX_VALUE_CHARS]
    raise ValidationFailed("Valor inválido.", code="INVALID_VALUE")


# ------------------------------------------------------------------ alvo (modelo ou kit) e seus campos


def _target_defs(db: Session, req: ClientRequest) -> tuple[str, list[FieldDef]]:
    """Nome do documento e campos (todos) do modelo/kit do pedido, na versão atual."""
    from app.modules.fields import service as fields_service
    from app.modules.kits import service as kits_service
    from app.modules.templates import core

    if req.generator_id is not None:
        gen = db.get(DocumentGenerator, req.generator_id)
        if gen is None or gen.deleted_at is not None:
            raise RequestNotFound()
        version = core.current_version_or_none(db, gen)
        return gen.name, (fields_service.field_defs(db, version.id) if version else [])
    kit = db.get(DocumentKit, req.kit_id)
    if kit is None or kit.deleted_at is not None:
        raise RequestNotFound()
    return kit.name, kits_service.kit_field_defs(db, kit.id)


def _defs_for(
    ctx: Ctx, generator_id: uuid.UUID | None, kit_id: uuid.UUID | None
) -> tuple[Any, str, list[FieldDef]]:
    from app.modules.fields import service as fields_service
    from app.modules.kits import service as kits_service
    from app.modules.templates import core

    if generator_id is not None:
        gen = core.get_generator(ctx.db, ctx.workspace_id, generator_id)
        version = core.current_version(ctx.db, gen)
        return gen, gen.name, fields_service.field_defs(ctx.db, version.id)
    kit = kits_service.get_kit(ctx.db, ctx.workspace_id, kit_id)  # type: ignore[arg-type]
    return kit, kit.name, kits_service.kit_field_defs(ctx.db, kit.id)


def _public_field(fd: FieldDef) -> dict[str, Any]:
    """Só o que o cliente precisa para preencher: nada de exemplo/valor padrão (são dados do modelo)."""
    config = {
        k: v
        for k, v in dict(fd.config or {}).items()
        if k != "options" and isinstance(v, bool | int | float | str) and len(str(v)) <= 40
    }
    return {
        "id": fd.id,
        "name": fd.name,
        "label": fd.label,
        "type": fd.type,
        "required": fd.required,
        "description": None,
        "default_value": None,
        "example": None,
        "mask": fd.mask,
        "group_name": None,
        "position": fd.position,
        "include_in_batch": True,
        "config": config,
        "options": [{"id": o.value, "label": o.label, "value": o.value} for o in fd.options],
        "occurrences": 1,
        "missing_in_document": False,
    }


def state_of(req: ClientRequest) -> str:
    if req.status == "cancelled":
        return "cancelled"
    if req.used_at is not None:
        return "used"
    if req.status == "answered":
        return "answered"
    if req.expires_at <= utcnow():
        return "expired"
    return "open"


def _share_text(doc_name: str, url: str, expires: Any) -> str:
    return (
        f"Olá! Para preparar o documento “{doc_name}”, preencha seus dados neste link "
        f"(vale até {expires:%d/%m/%Y}): {url}"
    )


# ------------------------------------------------------------------ lado do profissional


def create_request(
    ctx: Ctx, body: RequestIn, *, generator_id: uuid.UUID | None = None, kit_id: uuid.UUID | None = None
) -> dict[str, Any]:
    s = get_settings()
    db = ctx.db
    ratelimit.check(f"request-create:{ctx.user.id}", CREATES_PER_HOUR, 3600)
    _, doc_name, defs = _defs_for(ctx, generator_id, kit_id)
    by_name = {d.name: d for d in defs}
    if not defs:
        raise ValidationFailed("Este documento ainda não tem campos para pedir.", code="REQUEST_NO_FIELDS")
    names = list(dict.fromkeys(body.fields)) or [
        d.name for d in defs if d.required and d.default in (None, "")
    ]
    if not names:
        names = [d.name for d in defs]
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise ValidationFailed(
            "Campo inexistente no pedido.", code="REQUEST_UNKNOWN_FIELD", details={"fields": unknown[:10]}
        )
    names = [d.name for d in defs if d.name in set(names)]  # ordem do formulário
    if body.expires_days > s.request_max_days:
        raise ValidationFailed(f"A validade máxima é de {s.request_max_days} dias.", code="REQUEST_EXPIRY")
    prefill: dict[str, Any] = {}
    if body.prefill_mode != "hidden":
        for k, v in body.prefill.items():
            if k in names and v not in (None, ""):
                prefill[k] = _clean_value(v)
    open_count = db.scalar(
        select(func.count(ClientRequest.id)).where(
            ClientRequest.workspace_id == ctx.workspace_id,
            ClientRequest.status == "open",
            ClientRequest.expires_at > utcnow(),
        )
    )
    if (open_count or 0) >= s.request_max_open:
        raise LimitExceeded("Há links demais em aberto. Cancele os que não usa mais.", code="REQUEST_LIMIT")
    token = new_token(32)
    expires = utcnow() + timedelta(days=body.expires_days)
    req = ClientRequest(
        workspace_id=ctx.workspace_id,
        created_by=ctx.user.id,
        generator_id=generator_id,
        kit_id=kit_id,
        token_hash=token_hash(token),
        status="open",
        message=(body.message or "").strip()[:1000] or None,
        fields=names,
        prefill=prefill or null(),  # SQL NULL (e não o JSON null), para as consultas de limpeza
        prefill_mode=body.prefill_mode if prefill else "hidden",
        allow_photos=body.allow_photos,
        photo_reads=0,
        submissions=0,
        expires_at=expires,
    )
    db.add(req)
    db.flush()
    audit.record(
        db,
        "client_request.create",
        ctx=ctx,
        entity_type="client_request",
        entity_id=req.id,
        meta={
            "fields": len(names),
            "days": body.expires_days,
            "photos": body.allow_photos,
            "prefill": len(prefill),
        },
    )
    db.commit()
    url = f"{s.public_web_url.rstrip('/')}/r/{token}"
    return {**request_out(db, req, doc_name), "url": url, "share_text": _share_text(doc_name, url, expires)}


def _get(ctx: Ctx, request_id: uuid.UUID) -> ClientRequest:
    req = ctx.db.scalar(
        select(ClientRequest).where(
            ClientRequest.id == request_id, ClientRequest.workspace_id == ctx.workspace_id
        )
    )
    if req is None:
        raise NotFound("Pedido")
    return req


def request_out(db: Session, req: ClientRequest, doc_name: str | None = None) -> dict[str, Any]:
    if doc_name is None:
        target = (
            db.get(DocumentGenerator, req.generator_id)
            if req.generator_id
            else db.get(DocumentKit, req.kit_id)
        )
        doc_name = target.name if target else "(documento removido)"
    return {
        "id": str(req.id),
        "target": {
            "type": "generator" if req.generator_id else "kit",
            "id": str(req.generator_id or req.kit_id),
            "name": doc_name,
        },
        "state": state_of(req),
        "fields": list(req.fields or []),
        "message": req.message,
        "allow_photos": req.allow_photos,
        "photo_reads": req.photo_reads,
        "prefill_mode": req.prefill_mode,
        "submissions": req.submissions,
        "created_at": req.created_at.isoformat(),
        "expires_at": req.expires_at.isoformat(),
        "answered_at": req.answered_at.isoformat() if req.answered_at else None,
        "opened_at": req.opened_at.isoformat() if req.opened_at else None,
        "used_at": req.used_at.isoformat() if req.used_at else None,
        "has_values": req.values is not None,
    }


def list_requests(
    ctx: Ctx,
    *,
    generator_id: uuid.UUID | None = None,
    kit_id: uuid.UUID | None = None,
    state: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    q = select(ClientRequest).where(ClientRequest.workspace_id == ctx.workspace_id)
    if generator_id:
        q = q.where(ClientRequest.generator_id == generator_id)
    if kit_id:
        q = q.where(ClientRequest.kit_id == kit_id)
    now = utcnow()
    if state == "answered":
        q = q.where(ClientRequest.status == "answered", ClientRequest.used_at.is_(None))
    elif state == "open":
        q = q.where(ClientRequest.status == "open", ClientRequest.expires_at > now)
    elif state == "expired":
        q = q.where(ClientRequest.status == "open", ClientRequest.expires_at <= now)
    elif state == "cancelled":
        q = q.where(ClientRequest.status == "cancelled")
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = ctx.db.scalars(
        q.order_by(ClientRequest.answered_at.desc().nulls_last(), ClientRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [request_out(ctx.db, r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def summary(ctx: Ctx) -> dict[str, int]:
    """Contador do aviso no app: respostas que chegaram e ainda não foram abertas."""
    n = ctx.db.scalar(
        select(func.count(ClientRequest.id)).where(
            ClientRequest.workspace_id == ctx.workspace_id,
            ClientRequest.status == "answered",
            ClientRequest.opened_at.is_(None),
            ClientRequest.values.is_not(None),
        )
    )
    return {"new_answers": int(n or 0)}


def open_request(ctx: Ctx, request_id: uuid.UUID) -> dict[str, Any]:
    """Abre a resposta para conferir e gerar. A partir daqui o cliente não pode mais alterar o que enviou."""
    req = _get(ctx, request_id)
    if req.status == "answered" and req.opened_at is None:
        req.opened_at = utcnow()
        audit.record(ctx.db, "client_request.opened", ctx=ctx, entity_type="client_request", entity_id=req.id)
        ctx.db.commit()
    out = request_out(ctx.db, req)
    out["values"] = dict(req.values or {}) if req.status == "answered" else {}
    out["prefill"] = dict(req.prefill or {})
    return out


def cancel_request(ctx: Ctx, request_id: uuid.UUID) -> dict[str, Any]:
    req = _get(ctx, request_id)
    if req.status != "cancelled":
        req.status, req.cancelled_at = "cancelled", utcnow()
        req.values, req.prefill = null(), null()  # cancelar descarta o que o cliente mandou
        audit.record(ctx.db, "client_request.cancel", ctx=ctx, entity_type="client_request", entity_id=req.id)
        ctx.db.commit()
    return request_out(ctx.db, req)


def mark_used(ctx: Ctx, request_id: uuid.UUID) -> dict[str, Any]:
    """O documento foi gerado com a resposta: os dados do cliente saem daqui (ficam só no histórico da geração)."""
    req = _get(ctx, request_id)
    if req.status != "answered":
        raise Conflict("Este pedido não tem resposta para usar.", code="REQUEST_NOT_ANSWERED")
    if req.used_at is None:
        req.used_at = utcnow()
        req.values, req.prefill = null(), null()
        audit.record(ctx.db, "client_request.used", ctx=ctx, entity_type="client_request", entity_id=req.id)
        ctx.db.commit()
    return request_out(ctx.db, req)


# ------------------------------------------------------------------ lado público (o cliente)


def _find(db: Session, token: str) -> ClientRequest:
    if not TOKEN_RE.match(token or ""):
        raise RequestNotFound()
    req = db.scalar(select(ClientRequest).where(ClientRequest.token_hash == token_hash(token)))
    if req is None or req.status == "cancelled":
        raise RequestNotFound()
    ws = db.get(Workspace, req.workspace_id)
    if ws is None or ws.deleted_at is not None:
        raise RequestNotFound()
    return req


def _editable(req: ClientRequest) -> bool:
    return state_of(req) in ("open", "answered") and req.opened_at is None and req.expires_at > utcnow()


def public_view(db: Session, token: str, ip: str | None) -> dict[str, Any]:
    ratelimit.check(f"request-view:{_key(ip or 'na')}", VIEWS_PER_MINUTE, 60)
    req = _find(db, token)
    state = state_of(req)
    if state in ("expired", "used") or (state == "answered" and not _editable(req)):
        # sem dados: só o recado (o profissional já recebeu, ou o link venceu)
        return {"state": "closed" if state != "expired" else "expired"}
    ws = db.get(Workspace, req.workspace_id)
    doc_name, defs = _target_defs(db, req)
    wanted = set(req.fields or [])
    fields = [_public_field(d) for d in defs if d.name in wanted]
    if req.first_viewed_at is None:
        req.first_viewed_at = utcnow()
        audit.record(
            db,
            "client_request.viewed",
            workspace_id=req.workspace_id,
            entity_type="client_request",
            entity_id=req.id,
        )
        db.commit()
    reads_left = max(0, get_settings().request_photo_reads - req.photo_reads) if req.allow_photos else 0
    from app.modules.assist import ai

    return {
        "state": state,
        "workspace": ws.name if ws else "",
        "document": doc_name,
        "message": req.message,
        "fields": fields,
        "prefill_mode": req.prefill_mode,
        "prefill": dict(req.prefill or {}) if req.prefill_mode != "hidden" else {},
        "values": dict(req.values or {})
        if state == "answered"
        else {},  # o próprio cliente corrigindo o envio
        "photos": {"allowed": bool(req.allow_photos and ai.enabled()), "reads_left": reads_left},
        "expires_at": req.expires_at.isoformat(),
    }


def _check_open(req: ClientRequest) -> None:
    if not _editable(req):
        raise AppError(
            "Este link já foi usado ou venceu. Se precisar mudar algo, fale com quem enviou.",
            code="REQUEST_CLOSED",
            status_code=409,
        )


def public_submit(db: Session, token: str, ip: str | None, body: SubmitIn) -> dict[str, Any]:
    ratelimit.check(f"request-submit:{_key(ip or 'na')}", SUBMITS_PER_HOUR_IP, 3600)
    req = _find(db, token)
    ratelimit.check(f"request-submit-link:{req.id}", SUBMITS_PER_HOUR_LINK, 3600)
    _check_open(req)
    _, defs = _target_defs(db, req)
    wanted = [d for d in defs if d.name in set(req.fields or [])]
    fixed = dict(req.prefill or {}) if req.prefill_mode == "readonly" else {}
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for fd in wanted:
        raw = fixed[fd.name] if fd.name in fixed else body.values.get(fd.name)
        raw = _clean_value(raw)
        _, err = normalize_value(fd, raw)
        if err:
            errors[fd.name] = err
        if raw not in (None, ""):
            values[fd.name] = raw
    if errors:
        raise ValidationFailed(
            "Confira os campos destacados.", code="REQUEST_INVALID_VALUES", details={"field_errors": errors}
        )
    first = req.answered_at is None
    req.values = values
    req.status = "answered"
    req.answered_at = utcnow()
    req.submissions += 1
    audit.record(
        db,
        "client_request.submitted",
        workspace_id=req.workspace_id,
        entity_type="client_request",
        entity_id=req.id,
        meta={"fields": len(values), "submissions": req.submissions},
    )
    db.commit()
    if first:
        _notify_answer(req.id)
    return {"state": "answered", "submissions": req.submissions}


def public_read_files(db: Session, token: str, ip: str | None, files: list[bytes]) -> dict[str, Any]:
    """Foto/PDF do documento do cliente → valores (IA da D37, na cota do espaço; no máximo N leituras por link)."""
    from app.modules.assist import ai
    from app.modules.assist import service as assist

    ratelimit.check(f"request-read:{_key(ip or 'na')}", READS_PER_HOUR_IP, 3600)
    req = _find(db, token)
    _check_open(req)
    if not req.allow_photos or not ai.enabled():
        raise Conflict("Este link não aceita fotos de documentos.", code="REQUEST_PHOTOS_DISABLED")
    if len(files) > PHOTO_FILES_PER_READ:
        raise ValidationFailed(
            f"Envie no máximo {PHOTO_FILES_PER_READ} arquivos por vez.", code="AI_TOO_MANY_FILES"
        )
    limit = get_settings().request_photo_reads
    taken = db.execute(
        update(ClientRequest)
        .where(ClientRequest.id == req.id, ClientRequest.photo_reads < limit)
        .values(photo_reads=ClientRequest.photo_reads + 1)
    ).rowcount
    db.commit()
    if not taken:
        raise LimitExceeded(
            "Você já usou as leituras de documento deste link. Preencha os campos à mão.",
            code="REQUEST_READS_USED",
        )
    _, defs = _target_defs(db, req)
    fixed = set((req.prefill or {}).keys()) if req.prefill_mode == "readonly" else set()
    wanted = [d for d in defs if d.name in set(req.fields or []) and d.name not in fixed]
    ws = db.get(Workspace, req.workspace_id)
    quota = workspace_limit(db, ws, "max_ai_actions_per_month") if ws else 0
    try:
        result, meta = assist.read_files(
            db, wanted, files, workspace_id=req.workspace_id, quota=quota, max_files=PHOTO_FILES_PER_READ
        )
    except ValidationFailed:
        # arquivo recusado antes de chegar à IA (tipo, tamanho, PDF longo): não gasta a leitura do cliente
        db.execute(
            update(ClientRequest)
            .where(ClientRequest.id == req.id, ClientRequest.photo_reads > 0)
            .values(photo_reads=ClientRequest.photo_reads - 1)
        )
        db.commit()
        raise
    audit.record(
        db,
        "client_request.photo_read",
        workspace_id=req.workspace_id,
        entity_type="client_request",
        entity_id=req.id,
        meta=meta,
    )
    db.commit()
    db.refresh(req)
    result["reads_left"] = max(0, limit - req.photo_reads)
    return result


# ------------------------------------------------------------------ aviso por e-mail e limpeza


def _notify_answer(request_id: uuid.UUID) -> None:
    """E-mail para quem criou o link (se houver SMTP). Em segundo plano: o cliente não espera o envio."""

    def run() -> None:
        try:
            from app.adapters.notify import get_notifier

            with get_factory()() as db:
                req = db.get(ClientRequest, request_id)
                user = db.get(User, req.created_by) if req and req.created_by else None
                if req is None or user is None:
                    return
                doc_name, _ = _target_defs(db, req)
                path = (
                    f"/generators/{req.generator_id}/use?request={req.id}"
                    if req.generator_id
                    else f"/kits/{req.kit_id}/use?request={req.id}"
                )
                get_notifier().send_client_answer(
                    user.email, doc_name, f"{get_settings().public_web_url.rstrip('/')}{path}"
                )
        except Exception as exc:
            log.warning("aviso_resposta_cliente_falhou", extra={"error_type": type(exc).__name__})

    threading.Thread(target=run, daemon=True, name="aviso-resposta").start()


def purge_requests() -> dict[str, int]:
    """Apaga respostas e pré-preenchimentos vencidos (retenção) — a linha fica, sem dados, para o histórico."""
    s = get_settings()
    now = utcnow()
    with get_factory()() as db:
        answered = db.execute(
            update(ClientRequest)
            .where(
                ClientRequest.answered_at <= now - timedelta(days=s.request_retention_days),
                ClientRequest.values.is_not(None),
            )
            .values(values=null(), prefill=null(), purged_at=now)
        ).rowcount
        stale = db.execute(
            update(ClientRequest)
            .where(
                ClientRequest.expires_at <= now - timedelta(days=s.request_retention_days),
                ClientRequest.prefill.is_not(None),
            )
            .values(prefill=null(), purged_at=now)
        ).rowcount
        db.commit()
    if answered or stale:
        log.info("respostas_de_cliente_apagadas", extra={"respostas": answered, "pedidos": stale})
    return {"respostas": int(answered or 0), "pedidos": int(stale or 0)}


def purge_requests_throttled() -> None:
    global _last_purge
    if time.monotonic() - _last_purge < _PURGE_EVERY_S:
        return
    _last_purge = time.monotonic()
    purge_requests()
