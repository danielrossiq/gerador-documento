"""Teste grátis na landing (D38): documento de um visitante sem conta, analisado e apagado em 1 hora.

Uma linha por envio. O token que o navegador guarda só existe aqui como SHA-256. Não guardamos IP (os limites por IP
ficam no limitador, com chave em HMAC). O arquivo e o resultado somem no `claim` (vira modelo da conta) ou na limpeza
depois de `expires_at`; a linha também é apagada na limpeza.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, UTCDateTime, check_in, utcnow

TRIAL_STATUS = ("queued", "processing", "done", "failed")
TRIAL_FORMATS = ("docx", "pdf")


class Trial(IdMixin, Base):
    __tablename__ = "trials"
    __table_args__ = (
        check_in("status", TRIAL_STATUS, "status"),
        check_in("source_format", TRIAL_FORMATS, "source_format"),
        sa.Index("ix_trials_status_created", "status", "created_at"),
    )

    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="queued")
    source_format: Mapped[str] = mapped_column(sa.String(10))
    filename: Mapped[str] = mapped_column(sa.String(200))
    size_bytes: Mapped[int] = mapped_column(sa.Integer)
    # .docx a analisar (o PDF é trocado pelo .docx convertido assim que o worker o converte); nulo depois de apagado
    storage_key: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    # prévia (documento com os campos), campos encontrados e os achados brutos que viram sugestões no `claim`
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # como os campos foram achados: ai | local (sem IA externa) | budget (orçamento diário da IA esgotado)
    ai_mode: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # sinal de vida do processamento (a cada poucos segundos): sem ele, o teste órfão não ocupa vaga (QA-6)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    claimed_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    claimed_generator_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="SET NULL"), nullable=True
    )
