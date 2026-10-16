"""Métricas de ativação AGREGADAS (item 9a do backlog, D32).

Uma linha = um contador de um período (dia ou semana de coorte). Sem workspace_id, user_id, IP, horário
exato, texto livre ou chave estrangeira: só data, nome da métrica (lista fechada) e contagem. Contagens
abaixo de 5 não são gravadas (value NULL + suppressed). Retenção máxima de 30 dias.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, check_in

PERIOD_KINDS = ("day", "cohort_week")
METRICS = (
    # por dia (UTC)
    "workspaces_novos",
    "modelos_enviados",
    "primeiro_documento",
    "primeiro_documento_ate_5min",
    "lotes_concluidos",
    # por semana de coorte (semana de criação do workspace)
    "coorte_tamanho",
    "coorte_retorno_d7",
)


class ActivationMetric(Base):
    __tablename__ = "activation_metrics"
    __table_args__ = (
        check_in("period_kind", PERIOD_KINDS, "period_kind"),
        check_in("metric", METRICS, "metric"),
        sa.CheckConstraint("value IS NULL OR value >= 5", name="value_min_5"),
    )

    # chave natural (período + métrica): nem UUID de linha, para não haver identificador algum na tabela
    period_kind: Mapped[str] = mapped_column(sa.String(20), primary_key=True)
    period_start: Mapped[date] = mapped_column(sa.Date, primary_key=True)
    metric: Mapped[str] = mapped_column(sa.String(40), primary_key=True)
    value: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)  # NULL = suprimido (< 5)
    suppressed: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    computed_on: Mapped[date] = mapped_column(sa.Date)  # só o dia do cálculo, nunca hora
