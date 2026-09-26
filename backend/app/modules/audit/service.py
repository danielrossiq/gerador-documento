"""Registro de auditoria. Nunca grava conteúdo de documentos nem valores de campos."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.deps import Ctx
from app.core.logging import get_request_id
from app.db.models import AuditEvent

FORBIDDEN_META_KEYS = {"values", "content", "text", "password", "token", "cpf", "cnpj", "email"}


def record(
    db: Session,
    action: str,
    *,
    ctx: Ctx | None = None,
    workspace_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Adiciona o evento à sessão (o chamador faz commit junto da operação principal)."""
    safe = {k: v for k, v in (meta or {}).items() if k.lower() not in FORBIDDEN_META_KEYS}
    db.add(
        AuditEvent(
            workspace_id=ctx.workspace_id if ctx else workspace_id,
            user_id=ctx.user.id if ctx else user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            meta=safe or None,
            ip=(ctx.ip if ctx else ip),
            request_id=get_request_id(),
        )
    )
