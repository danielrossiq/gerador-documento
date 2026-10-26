"""Link para o cliente preencher (D39): o profissional pede dados, o cliente responde pelo celular.

O token do link só existe aqui como SHA-256 (o link é mostrado uma vez). A resposta (`values`) fica guardada até ser
usada para gerar o documento ou até a retenção (`REQUEST_RETENTION_DAYS` depois de respondida) e então é apagada;
a linha continua, sem os dados, para o histórico do pedido.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime, check_in

REQUEST_STATUS = ("open", "answered", "cancelled")  # "expirado" é derivado de expires_at
PREFILL_MODES = ("hidden", "readonly", "editable")


class ClientRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "client_requests"
    __table_args__ = (
        check_in("status", REQUEST_STATUS, "status"),
        check_in("prefill_mode", PREFILL_MODES, "prefill_mode"),
        sa.CheckConstraint("(generator_id IS NULL) != (kit_id IS NULL)", name="one_target"),
        sa.CheckConstraint("photo_reads >= 0 AND photo_reads <= 10", name="photo_reads_range"),
        sa.Index("ix_client_requests_workspace_status", "workspace_id", "status", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("workspaces.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generator_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kit_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("document_kits.id", ondelete="CASCADE"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="open")
    message: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    # códigos dos campos pedidos, na ordem do formulário
    fields: Mapped[list[str]] = mapped_column(JSONType)
    # valores que o profissional já tinha; o cliente vê (readonly/editable) ou não (hidden)
    prefill: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    prefill_mode: Mapped[str] = mapped_column(sa.String(20), default="hidden")
    allow_photos: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    photo_reads: Mapped[int] = mapped_column(sa.Integer, default=0)
    # resposta do cliente (texto de exibição, validado com as mesmas regras do formulário)
    values: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    submissions: Mapped[int] = mapped_column(sa.Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    first_viewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # o profissional abriu a resposta (a partir daí o cliente não altera mais o envio)
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # o profissional gerou com ela: os dados do cliente são apagados daqui
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # retenção venceu
