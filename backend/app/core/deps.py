"""Dependências de requisição: contexto autenticado (usuário + workspace), CSRF e checagem de origem."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def limit(self, name: str) -> int:
        override: dict[str, Any] = self.workspace.limits or {}
        base = {**DEFAULT_LIMITS, **get_settings().default_limits}
        return int(override.get(name, base.get(name, 0)))


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


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
