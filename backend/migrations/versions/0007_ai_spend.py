"""razão de custo da IA externa (reserva antes da chamada; teto mensal global e cota mensal por workspace)

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_spend",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('reserved', 'settled', 'failed')", name=op.f("ck_ai_spend_status")),
        sa.CheckConstraint(
            "purpose IN ('analysis', 'fill', 'review', 'mapping', 'eval')", name=op.f("ck_ai_spend_purpose")
        ),
        sa.CheckConstraint("reserved_usd > 0", name=op.f("ck_ai_spend_reserved_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_ai_spend_workspace_id_workspaces"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_spend")),
    )
    op.create_index(op.f("ix_ai_spend_created_at"), "ai_spend", ["created_at"], unique=False)
    op.create_index("ix_ai_spend_workspace_created", "ai_spend", ["workspace_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_spend_workspace_created", table_name="ai_spend")
    op.drop_index(op.f("ix_ai_spend_created_at"), table_name="ai_spend")
    op.drop_table("ai_spend")
