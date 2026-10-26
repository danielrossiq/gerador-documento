"""Assinatura eletrônica (D40): provedor configurado por espaço, pedidos de assinatura e eventos de webhook.

Credenciais e segredo de webhook ficam cifrados (Fernet, `app.core.crypto`); a chave da URL do webhook fica só como
SHA-256, como o token do link do cliente. O PDF assinado volta como arquivo da geração (`generated_files.kind =
'signed'`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime, check_in, utcnow

# provedores com API (os outros da spec entram aqui: d4sign, autentique, docusign, adobe_sign)
API_PROVIDERS = ("zapsign", "clicksign")
# gov.br e certificado ICP-Brasil feitos fora do app: fluxo assistido com verificação PAdES
SIGNATURE_PROVIDERS = (*API_PROVIDERS, "govbr")
ENVIRONMENTS = ("sandbox", "production")
SIGNATURE_STATUS = ("awaiting_upload", "sent", "signed", "refused", "cancelled", "expired", "error")
FINAL_STATUS = ("signed", "refused", "cancelled", "expired")


class SignatureProviderConfig(IdMixin, TimestampMixin, Base):
    __tablename__ = "signature_providers"
    __table_args__ = (
        check_in("provider", API_PROVIDERS, "provider"),
        check_in("environment", ENVIRONMENTS, "environment"),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_signature_providers_workspace_provider"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(sa.String(20))
    environment: Mapped[str] = mapped_column(sa.String(20), default="sandbox")
    credentials_enc: Mapped[str] = mapped_column(sa.Text)  # Fernet de {"api_token": ...}
    webhook_secret_enc: Mapped[str | None] = mapped_column(sa.Text, nullable=True)  # Fernet
    webhook_key_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    credential_hint: Mapped[str] = mapped_column(sa.String(12), default="")  # "…a1b2", para a tela
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)


class SignatureRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "signature_requests"
    __table_args__ = (
        check_in("provider", SIGNATURE_PROVIDERS, "provider"),
        check_in("status", SIGNATURE_STATUS, "status"),
        sa.Index("ix_signature_requests_external", "provider", "external_id"),
        sa.Index("ix_signature_requests_workspace_created", "workspace_id", "created_at"),
        sa.Index("ix_signature_requests_status_synced", "status", "last_synced_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("workspaces.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(sa.String(20))
    provider_config_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("signature_providers.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("generation_jobs.id", ondelete="CASCADE"), index=True
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("generated_files.id", ondelete="SET NULL"), nullable=True
    )
    signed_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("generated_files.id", ondelete="SET NULL"), nullable=True
    )
    # id do envelope/documento no provedor (ZapSign: token do documento; Clicksign: id do envelope)
    external_id: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20))
    provider_status: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    # nome, e-mail, celular, CPF (opcional), ordem, autenticação, link de assinatura e situação de cada um
    signers: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)
    message: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    # gov.br/ICP-Brasil: resultado da verificação PAdES (quem assinou, quando, íntegro), CPF mascarado
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SignatureEvent(IdMixin, Base):
    """Webhooks já recebidos (idempotência: o provedor pode reenviar o mesmo evento). `event_key` é o id do evento
    no provedor ou, sem id, o SHA-256 do corpo."""

    __tablename__ = "signature_events"
    __table_args__ = (sa.UniqueConstraint("provider", "event_key", name="uq_signature_events_provider_key"),)

    provider: Mapped[str] = mapped_column(sa.String(20))
    event_key: Mapped[str] = mapped_column(sa.String(100))
    event_type: Mapped[str] = mapped_column(sa.String(60))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("signature_requests.id", ondelete="SET NULL"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
