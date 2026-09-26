"""Usuários, workspaces (tenants), membros, sessões e tokens de recuperação."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime, check_in, utcnow

ROLES = ("owner", "member")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    password_hash: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # nulo = só login social
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    memberships: Mapped[list[WorkspaceMember]] = relationship(back_populates="user")


class AuthIdentity(IdMixin, Base):
    """Ponto de extensão para login social (Google/Microsoft): (provider, subject) → usuário."""

    __tablename__ = "auth_identities"
    __table_args__ = (sa.UniqueConstraint("provider", "subject"),)

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(sa.String(40))
    subject: Mapped[str] = mapped_column(sa.String(255))


class Workspace(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(sa.String(200))
    slug: Mapped[str] = mapped_column(sa.String(120), unique=True)
    limits: Mapped[dict[str, Any] | None] = mapped_column(
        JSONType, nullable=True
    )  # sobrescreve limites padrão
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    members: Mapped[list[WorkspaceMember]] = relationship(back_populates="workspace")


class WorkspaceMember(IdMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "user_id"),
        check_in("role", ROLES, "role"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(sa.String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class UserSession(IdMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("workspaces.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)


class PasswordResetToken(IdMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
