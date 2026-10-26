"""teste grátis na landing (D38): tabela trials e finalidade 'trial' na razão de custo da IA

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

OLD_PURPOSES = "purpose IN ('analysis', 'fill', 'review', 'mapping', 'eval')"
NEW_PURPOSES = "purpose IN ('analysis', 'fill', 'review', 'mapping', 'eval', 'trial')"


def upgrade() -> None:
    op.create_table(
        "trials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_format", sa.String(length=10), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=True),
        sa.Column("result", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=True),
        sa.Column("ai_mode", sa.String(length=20), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_workspace_id", sa.Uuid(), nullable=True),
        sa.Column("claimed_generator_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'processing', 'done', 'failed')", name=op.f("ck_trials_status")),
        sa.CheckConstraint("source_format IN ('docx', 'pdf')", name=op.f("ck_trials_source_format")),
        sa.ForeignKeyConstraint(
            ["claimed_workspace_id"], ["workspaces.id"], name=op.f("fk_trials_claimed_workspace_id_workspaces"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["claimed_generator_id"],
            ["document_generators.id"],
            name=op.f("fk_trials_claimed_generator_id_document_generators"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trials")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_trials_token_hash")),
    )
    op.create_index(op.f("ix_trials_expires_at"), "trials", ["expires_at"], unique=False)
    op.create_index("ix_trials_status_created", "trials", ["status", "created_at"], unique=False)
    with op.batch_alter_table("ai_spend") as batch:
        batch.drop_constraint(op.f("ck_ai_spend_purpose"), type_="check")
        batch.create_check_constraint(op.f("ck_ai_spend_purpose"), NEW_PURPOSES)


def downgrade() -> None:
    op.execute("DELETE FROM ai_spend WHERE purpose = 'trial'")
    with op.batch_alter_table("ai_spend") as batch:
        batch.drop_constraint(op.f("ck_ai_spend_purpose"), type_="check")
        batch.create_check_constraint(op.f("ck_ai_spend_purpose"), OLD_PURPOSES)
    op.drop_index("ix_trials_status_created", table_name="trials")
    op.drop_index(op.f("ix_trials_expires_at"), table_name="trials")
    op.drop_table("trials")
