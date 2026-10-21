"""assinaturas (Stripe: cartão recorrente ou Pix por período) e eventos de webhook processados

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.String(length=20), nullable=False),
        sa.Column("cycle", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=100), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=100), nullable=True),
        sa.Column("last_event_id", sa.String(length=100), nullable=True),
        sa.CheckConstraint("plan_id IN ('gratis', 'profissional', 'escritorio')", name=op.f("ck_subscriptions_plan_id")),
        sa.CheckConstraint("cycle IN ('mensal', 'anual')", name=op.f("ck_subscriptions_cycle")),
        sa.CheckConstraint(
            "status IN ('active', 'past_due', 'canceled', 'incomplete', 'expired')", name=op.f("ck_subscriptions_status")
        ),
        sa.CheckConstraint("method IN ('card', 'pix')", name=op.f("ck_subscriptions_method")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_subscriptions_workspace_id_workspaces"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint("stripe_subscription_id", name=op.f("uq_subscriptions_stripe_subscription_id")),
    )
    op.create_index(op.f("ix_subscriptions_workspace_id"), "subscriptions", ["workspace_id"], unique=True)
    op.create_index(op.f("ix_subscriptions_stripe_customer_id"), "subscriptions", ["stripe_customer_id"], unique=False)
    op.create_table(
        "billing_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stripe_event_id", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_events")),
        sa.UniqueConstraint("stripe_event_id", name=op.f("uq_billing_events_stripe_event_id")),
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_index(op.f("ix_subscriptions_stripe_customer_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_workspace_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
