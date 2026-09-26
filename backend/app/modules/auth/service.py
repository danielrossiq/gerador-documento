"""Cadastro, login, sessões e recuperação de senha."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.notify import get_notifier
from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import Conflict, Unauthorized, ValidationFailed
from app.core.security import hash_password, needs_rehash, new_token, token_hash, verify_password
from app.db.base import utcnow
from app.db.models import PasswordResetToken, User, UserSession, Workspace, WorkspaceMember
from app.modules.audit import service as audit
from app.modules.fields.types import to_snake_case
from app.modules.fields.validators import is_valid_email

MIN_PASSWORD = 8


def _check_password(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValidationFailed(
            f"A senha deve ter pelo menos {MIN_PASSWORD} caracteres.", code="WEAK_PASSWORD"
        )
    if password.lower() == email.lower() or (password.isdigit() and len(set(password)) <= 2):
        raise ValidationFailed("Escolha uma senha menos previsível.", code="WEAK_PASSWORD")


def _unique_slug(db: Session, base: str) -> str:
    slug = re.sub(r"_", "-", to_snake_case(base, fallback="espaco"))[:50]
    while db.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        slug = f"{slug[:44]}-{secrets.token_hex(3)}"
    return slug


def register(
    db: Session, *, name: str, email: str, password: str, workspace_name: str | None, ip: str | None
) -> tuple[User, Workspace]:
    email = email.strip().lower()
    name = name.strip()
    if len(name) < 2:
        raise ValidationFailed("Informe seu nome.", code="INVALID_NAME")
    if not is_valid_email(email):
        raise ValidationFailed("E-mail inválido.", code="INVALID_EMAIL")
    _check_password(password, email)
    ratelimit.check(f"register:{ip or 'na'}", limit=10, window=3600)
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("Já existe uma conta com este e-mail.", code="EMAIL_TAKEN")
    ws_name = (workspace_name or "").strip() or f"Espaço de {name.split()[0]}"
    user = User(email=email, name=name, password_hash=hash_password(password))
    ws = Workspace(name=ws_name[:200], slug=_unique_slug(db, ws_name))
    try:
        db.add_all([user, ws])
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
        audit.record(
            db,
            "auth.register",
            workspace_id=ws.id,
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip=ip,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Já existe uma conta com este e-mail.", code="EMAIL_TAKEN") from exc
    return user, ws


def create_session(
    db: Session, user: User, workspace: Workspace, ip: str | None, user_agent: str | None
) -> tuple[str, str]:
    token, csrf = new_token(32), new_token(24)
    db.add(
        UserSession(
            user_id=user.id,
            workspace_id=workspace.id,
            token_hash=token_hash(token),
            csrf_token=csrf,
            expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours),
            ip=ip,
            user_agent=(user_agent or "")[:300],
        )
    )
    return token, csrf


def login(
    db: Session, *, email: str, password: str, ip: str | None, user_agent: str | None
) -> tuple[User, Workspace, str, str]:
    email = email.strip().lower()
    ratelimit.check(f"login:{ip or 'na'}")
    ratelimit.check(f"login-user:{email}", limit=10)
    user = db.scalar(select(User).where(User.email == email))
    if (
        not verify_password(password, user.password_hash if user else None)
        or user is None
        or not user.is_active
    ):
        audit.record(db, "auth.login_failed", user_id=user.id if user else None, ip=ip)
        db.commit()
        raise Unauthorized("E-mail ou senha incorretos.")
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    membership = db.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at)
    )
    if membership is None:
        raise Unauthorized("Sua conta não pertence a nenhum workspace.")
    workspace = db.get(Workspace, membership.workspace_id)
    assert workspace is not None
    token, csrf = create_session(db, user, workspace, ip, user_agent)
    user.last_login_at = utcnow()
    audit.record(db, "auth.login", workspace_id=workspace.id, user_id=user.id, ip=ip)
    db.commit()
    return user, workspace, token, csrf


def logout(db: Session, session: UserSession) -> None:
    session.revoked_at = utcnow()
    audit.record(db, "auth.logout", workspace_id=session.workspace_id, user_id=session.user_id)
    db.commit()


def forgot_password(db: Session, email: str, ip: str | None) -> None:
    """Sempre responde igual, exista ou não a conta (não vaza cadastro)."""
    ratelimit.check(f"forgot:{ip or 'na'}", limit=5, window=600)
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        return
    token = new_token(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=utcnow() + timedelta(minutes=get_settings().password_reset_ttl_minutes),
        )
    )
    audit.record(db, "auth.password_reset_requested", user_id=user.id, ip=ip)
    db.commit()
    link = f"{get_settings().public_web_url.rstrip('/')}/reset-password?token={token}"
    get_notifier().send_password_reset(user.email, link)


def reset_password(db: Session, token: str, new_password: str, ip: str | None) -> None:
    ratelimit.check(f"reset:{ip or 'na'}", limit=10, window=600)
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash(token)))
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise ValidationFailed("Link de recuperação inválido ou expirado.", code="INVALID_RESET_TOKEN")
    user = db.get(User, row.user_id)
    assert user is not None
    _check_password(new_password, user.email)
    user.password_hash = hash_password(new_password)
    row.used_at = utcnow()
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    audit.record(db, "auth.password_reset", user_id=user.id, ip=ip)
    db.commit()


def workspace_id_of(session: UserSession) -> uuid.UUID:
    return session.workspace_id
