"""Razão de custo da IA externa: teto por chamada, teto mensal global e cota mensal por workspace.

Uma linha = uma tentativa de chamada paga. É reservada com o custo MÁXIMO antes de sair e acertada com o custo
informado pelo provedor depois. Falha ou queda mantém a reserva (conta no teto). Sem conteúdo do documento nem
texto livre: só workspace (para a cota do plano), modelo, finalidade, situação, valores e tokens. Se o workspace
for eliminado, a linha fica (sem vínculo) para o teto global continuar correto.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, UTCDateTime, check_in, utcnow

SPEND_STATUS = ("reserved", "settled", "failed")
# analysis = marcar campos no documento enviado; fill = preencher a partir de texto colado; review = revisar
# antes de gerar; mapping = mapear colunas de planilha; eval = avaliação de modelos (sem workspace);
# trial = teste grátis da landing (sem workspace, com orçamento diário próprio: TRIAL_AI_DAILY_BUDGET_USD)
SPEND_PURPOSE = ("analysis", "fill", "review", "mapping", "eval", "trial")


class AISpend(IdMixin, Base):
    __tablename__ = "ai_spend"
    __table_args__ = (
        check_in("status", SPEND_STATUS, "status"),
        check_in("purpose", SPEND_PURPOSE, "purpose"),
        sa.CheckConstraint("reserved_usd > 0", name="reserved_positive"),
        sa.Index("ix_ai_spend_workspace_created", "workspace_id", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(sa.String(100))
    purpose: Mapped[str] = mapped_column(sa.String(20))
    status: Mapped[str] = mapped_column(sa.String(20), default="reserved")
    reserved_usd: Mapped[Decimal] = mapped_column(sa.Numeric(10, 6))
    cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
