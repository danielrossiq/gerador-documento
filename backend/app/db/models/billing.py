"""Assinatura do workspace (Stripe). Uma linha por workspace; sem linha = plano Grátis.

Cartão: assinatura recorrente da Stripe (renova sozinha; o cliente gerencia no portal da Stripe).
Pix: pagamento avulso do período (mês ou ano); a renovação é um novo Pix (a Stripe não oferece Pix recorrente
para empresas no Brasil). Dados de cartão nunca passam pelo DocFeito: ficam na Stripe.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime, check_in

PLAN_IDS = ("gratis", "profissional", "escritorio")
CYCLES = ("mensal", "anual")
SUB_STATUS = ("active", "past_due", "canceled", "incomplete", "expired")
METHODS = ("card", "pix")


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        check_in("plan_id", PLAN_IDS, "plan_id"),
        check_in("cycle", CYCLES, "cycle"),
        check_in("status", SUB_STATUS, "status"),
        check_in("method", METHODS, "method"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, index=True
    )
    plan_id: Mapped[str] = mapped_column(sa.String(20))
    cycle: Mapped[str] = mapped_column(sa.String(10))
    status: Mapped[str] = mapped_column(sa.String(20))
    method: Mapped[str] = mapped_column(sa.String(10))
    current_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True, unique=True)
    last_event_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)


class BillingEvent(IdMixin, Base):
    """Eventos de webhook já processados (idempotência: a Stripe pode reenviar o mesmo evento)."""

    __tablename__ = "billing_events"

    stripe_event_id: Mapped[str] = mapped_column(sa.String(100), unique=True)
    type: Mapped[str] = mapped_column(sa.String(80))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
