"""Tetos de custo da IA externa: por chamada, mensal global e cota mensal por workspace (plano).

- Toda chamada paga é RESERVADA pelo custo máximo antes de sair, numa transação com trava (PostgreSQL:
  pg_advisory_xact_lock), então dois workers nunca reservam juntos além do teto.
- Gasto = custo informado pelo provedor quando existe; senão a reserva. Falhas contam (o provedor pode ter cobrado).
- Não sai: chamada com máximo acima de AI_MAX_CALL_USD; chamada que faria o mês passar de AI_MONTHLY_BUDGET_USD;
  workspace que já usou as ações com IA do plano no mês (max_ai_actions_per_month).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models import AISpend
from app.db.session import get_factory

_LOCK_KEY = 0x6D696E7574  # "minut": chave fixa da trava consultiva do teto de IA


class BudgetExceeded(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _lock(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})


def _month_start():  # type: ignore[no-untyped-def]
    now = utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(db: Session) -> Decimal:
    total = db.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(sa.func.coalesce(AISpend.cost_usd, AISpend.reserved_usd)), 0)).where(
            AISpend.created_at >= _month_start()
        )
    )
    return Decimal(str(total))


def actions_this_month(db: Session, workspace_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            sa.select(sa.func.count(AISpend.id)).where(  # chamada que falhou não desconta da cota do cliente
                AISpend.workspace_id == workspace_id,
                AISpend.created_at >= _month_start(),
                AISpend.purpose != "eval",
                AISpend.status != "failed",
            )
        )
        or 0
    )


def reserve(model: str, purpose: str, max_usd: Decimal, *, workspace_id: uuid.UUID | None = None, quota: int | None = None) -> uuid.UUID:
    s = get_settings()
    cap_call, cap_month = Decimal(str(s.ai_max_call_usd)), Decimal(str(s.ai_monthly_budget_usd))
    if max_usd <= 0:
        raise BudgetExceeded("AI_COST_UNKNOWN", "Custo máximo da chamada não pôde ser calculado.")
    if max_usd > cap_call:
        raise BudgetExceeded("AI_CALL_TOO_EXPENSIVE", "O documento é grande demais para a IA nesta operação.")
    with get_factory()() as db, db.begin():
        _lock(db)
        if workspace_id is not None and quota is not None and actions_this_month(db, workspace_id) >= quota:
            raise BudgetExceeded(
                "AI_QUOTA_EXCEEDED",
                f"Você já usou as {quota} ações com IA do seu plano neste mês. Elas voltam no dia 1º, ou mude de plano.",
            )
        if spent_this_month(db) + max_usd > cap_month:
            raise BudgetExceeded("AI_BUDGET_EXHAUSTED", "A IA está temporariamente indisponível. Tente mais tarde.")
        row = AISpend(model=model, purpose=purpose, status="reserved", reserved_usd=max_usd, workspace_id=workspace_id)
        db.add(row)
        db.flush()
        return row.id


def settle(spend_id: uuid.UUID, cost_usd: float | None, tokens_in: int | None, tokens_out: int | None) -> bool:
    """Registra o custo real. Devolve False se veio acima da reserva (o chamador deve registrar o alerta)."""
    with get_factory()() as db, db.begin():
        row = db.get(AISpend, spend_id)
        if row is None:
            return False
        row.status = "settled"
        row.tokens_in, row.tokens_out = tokens_in, tokens_out
        if cost_usd is not None:
            row.cost_usd = Decimal(str(cost_usd))
        return cost_usd is None or row.cost_usd <= row.reserved_usd


def fail(spend_id: uuid.UUID) -> None:
    """Falha: a reserva continua contando no teto (o provedor pode ter cobrado)."""
    with get_factory()() as db, db.begin():
        row = db.get(AISpend, spend_id)
        if row is not None:
            row.status = "failed"
