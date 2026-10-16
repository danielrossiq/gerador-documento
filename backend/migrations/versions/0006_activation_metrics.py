"""métricas de ativação agregadas (sem FK, sem identificadores; D32)

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

METRICS = (
    "workspaces_novos", "modelos_enviados", "primeiro_documento", "primeiro_documento_ate_5min",
    "lotes_concluidos", "coorte_tamanho", "coorte_retorno_d7",
)  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "activation_metrics",
        sa.Column("period_kind", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Integer(), nullable=True),
        sa.Column("suppressed", sa.Boolean(), nullable=False),
        sa.Column("computed_on", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "period_kind IN ('day', 'cohort_week')", name=op.f("ck_activation_metrics_period_kind")
        ),
        sa.CheckConstraint(
            "metric IN (" + ", ".join(f"'{m}'" for m in METRICS) + ")",
            name=op.f("ck_activation_metrics_metric"),
        ),
        sa.CheckConstraint("value IS NULL OR value >= 5", name=op.f("ck_activation_metrics_value_min_5")),
        sa.PrimaryKeyConstraint("period_kind", "period_start", "metric", name=op.f("pk_activation_metrics")),
    )


def downgrade() -> None:
    op.drop_table("activation_metrics")
