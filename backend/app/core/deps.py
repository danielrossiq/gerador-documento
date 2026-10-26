"""Dependências de requisição: contexto autenticado (usuário + workspace), CSRF e checagem de origem."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_LIMITS, get_settings
from app.core.errors import Forbidden, Unauthorized
from app.core.logging import get_request_id
from app.core.security import constant_time_equals, token_hash
from app.db.base import utcnow
from app.db.models import User, UserSession, Workspace, WorkspaceMember
from app.db.session import get_db

SESSION_COOKIE = "minuta_session"
CSRF_COOKIE = "minuta_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SLIDE_AFTER = timedelta(minutes=5)


@dataclass
class Ctx:
    db: Session
    user: User
    workspace: Workspace
    role: str
    session: UserSession
    ip: str | None
    request_id: str | None
    _plan_limits: dict[str, int] | None = field(default=None, repr=False)  # cache por requisição

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def limit(self, name: str) -> int:
        """Override do workspace > limites do plano (só com cobrança ligada) > padrão do ambiente."""
        if self._plan_limits is None:
            from app.modules.billing.service import workspace_plan_limits

            self._plan_limits = workspace_plan_limits(self.db, self.workspace.id) or {}
        return _resolve_limit(self.workspace, self._plan_limits, name)


def _resolve_limit(workspace: Workspace, plan_limits: dict[str, int], name: str) -> int:
    override: dict[str, Any] = workspace.limits or {}
    if name in override:
        return int(override[name])
    if name in plan_limits:
        return int(plan_limits[name])
    base = {**DEFAULT_LIMITS, **get_settings().default_limits}
    return int(base.get(name, 0))


def workspace_limit(db: Session, workspace: Workspace, name: str) -> int:
    """O mesmo que Ctx.limit, fora de uma requisição (ex.: análise no worker)."""
    from app.modules.billing.service import workspace_plan_limits

    return _resolve_limit(workspace, workspace_plan_limits(db, workspace.id) or {}, name)


def client_ip(request: Request) -> str | None:
    """IP real de quem chamou: o X-Forwarded-For só vale se veio de um proxy em TRUSTED_PROXIES (ver app.core.net).
    Única fonte do IP para limites, sessões e auditoria."""
    from app.core.net import parse_networks, resolve_client_ip

    s = get_settings()
    peer = request.client.host if request.client else None
    # vários cabeçalhos X-Forwarded-For valem como um só, na ordem (proxy que acrescenta uma linha em vez de anexar)
    forwarded = ", ".join(request.headers.getlist("x-forwarded-for")) or None
    return resolve_client_ip(peer, forwarded, parse_networks(tuple(s.trusted_proxies)), s.trusted_proxy_hops)


def check_origin(request: Request) -> None:
    """Rejeita requisições inseguras cujo Origin/Referer não pertença à aplicação."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if not origin:
        return  # clientes não-navegador (curl, testes) não enviam Origin; CSRF depende de cookie de navegador
    allowed = set(get_settings().allowed_origins)
    host_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
    if origin not in allowed and origin != host_origin:
        raise Forbidden("Origem não permitida.")


async def read_body_capped(request: Request, max_bytes: int) -> bytes:
    """Corpo da requisição com teto, para rotas públicas: o Content-Length é conferido antes e a leitura para no
    limite (corpo sem Content-Length ou maior que o declarado não passa)."""
    from app.core.errors import AppError

    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise AppError("Envie pelo formulário da página.", code="LENGTH_REQUIRED", status_code=411)
    if int(length) > max_bytes:
        raise AppError("O envio passa do tamanho permitido.", code="FILE_TOO_LARGE", status_code=413)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > max_bytes:
            raise AppError("O envio passa do tamanho permitido.", code="FILE_TOO_LARGE", status_code=413)
    return bytes(body)


def require_same_origin(request: Request) -> None:
    check_origin(request)


def get_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    check_origin(request)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized()
    now = utcnow()
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise Unauthorized("Sessão expirada. Entre novamente.")

    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not constant_time_equals(sent, session.csrf_token):
            raise Forbidden("Token CSRF ausente ou inválido.")

    user = db.get(User, session.user_id)
    workspace = db.get(Workspace, session.workspace_id)
    if user is None or not user.is_active or workspace is None or workspace.deleted_at is not None:
        raise Unauthorized()
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id
        )
    )
    if member is None:
        raise Unauthorized("Você não pertence a este workspace.")

    if now - session.last_seen_at > SLIDE_AFTER:  # expiração deslizante sem escrever a cada requisição
        session.last_seen_at = now
        session.expires_at = now + timedelta(hours=get_settings().session_ttl_hours)
        db.commit()
    return Ctx(db, user, workspace, member.role, session, client_ip(request), get_request_id())
