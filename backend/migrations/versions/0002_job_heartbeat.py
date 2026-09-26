"""heartbeat de jobs de geração (recuperação automática após queda do worker)

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_status_heartbeat", "generation_jobs", ["status", "heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_heartbeat", table_name="generation_jobs")
    op.drop_column("generation_jobs", "heartbeat_at")
