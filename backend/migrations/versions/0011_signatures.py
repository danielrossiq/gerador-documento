"""assinatura eletrônica (D40): provedor por espaço (credenciais cifradas, chave do webhook só como hash), pedidos
de assinatura, eventos de webhook (idempotência) e o tipo de arquivo `signed` nas saídas da geração

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('signature_providers',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('environment', sa.String(length=20), nullable=False),
    sa.Column('credentials_enc', sa.Text(), nullable=False),
    sa.Column('webhook_secret_enc', sa.Text(), nullable=True),
    sa.Column('webhook_key_hash', sa.String(length=64), nullable=False),
    sa.Column('credential_hint', sa.String(length=12), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_test_ok', sa.Boolean(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("environment IN ('sandbox', 'production')", name=op.f('ck_signature_providers_environment')),
    sa.CheckConstraint("provider IN ('zapsign', 'clicksign')", name=op.f('ck_signature_providers_provider')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_signature_providers_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_signature_providers_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signature_providers')),
    sa.UniqueConstraint('webhook_key_hash', name=op.f('uq_signature_providers_webhook_key_hash')),
    sa.UniqueConstraint('workspace_id', 'provider', name='uq_signature_providers_workspace_provider')
    )
    op.create_index(op.f('ix_signature_providers_workspace_id'), 'signature_providers', ['workspace_id'], unique=False)
    op.create_table('signature_requests',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_config_id', sa.Uuid(), nullable=True),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('source_file_id', sa.Uuid(), nullable=True),
    sa.Column('signed_file_id', sa.Uuid(), nullable=True),
    sa.Column('external_id', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('provider_status', sa.String(length=40), nullable=True),
    sa.Column('signers', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('message', sa.String(length=1000), nullable=True),
    sa.Column('error_code', sa.String(length=60), nullable=True),
    sa.Column('verification', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("provider IN ('zapsign', 'clicksign', 'govbr')", name=op.f('ck_signature_requests_provider')),
    sa.CheckConstraint("status IN ('awaiting_upload', 'sent', 'signed', 'refused', 'cancelled', 'expired', 'error')", name=op.f('ck_signature_requests_status')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_signature_requests_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['generation_jobs.id'], name=op.f('fk_signature_requests_job_id_generation_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provider_config_id'], ['signature_providers.id'], name=op.f('fk_signature_requests_provider_config_id_signature_providers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['signed_file_id'], ['generated_files.id'], name=op.f('fk_signature_requests_signed_file_id_generated_files'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_file_id'], ['generated_files.id'], name=op.f('fk_signature_requests_source_file_id_generated_files'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_signature_requests_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signature_requests'))
    )
    op.create_index('ix_signature_requests_external', 'signature_requests', ['provider', 'external_id'], unique=False)
    op.create_index(op.f('ix_signature_requests_job_id'), 'signature_requests', ['job_id'], unique=False)
    op.create_index('ix_signature_requests_status_synced', 'signature_requests', ['status', 'last_synced_at'], unique=False)
    op.create_index('ix_signature_requests_workspace_created', 'signature_requests', ['workspace_id', 'created_at'], unique=False)
    op.create_table('signature_events',
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('event_key', sa.String(length=100), nullable=False),
    sa.Column('event_type', sa.String(length=60), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['request_id'], ['signature_requests.id'], name=op.f('fk_signature_events_request_id_signature_requests'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signature_events')),
    sa.UniqueConstraint('provider', 'event_key', name='uq_signature_events_provider_key')
    )
    # o PDF assinado volta como arquivo da geração
    op.drop_constraint(op.f('ck_generated_files_kind'), 'generated_files', type_='check')
    op.create_check_constraint(
        op.f('ck_generated_files_kind'), 'generated_files', "kind IN ('docx', 'pdf', 'zip', 'report', 'signed')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM generated_files WHERE kind = 'signed'")
    op.drop_constraint(op.f('ck_generated_files_kind'), 'generated_files', type_='check')
    op.create_check_constraint(
        op.f('ck_generated_files_kind'), 'generated_files', "kind IN ('docx', 'pdf', 'zip', 'report')"
    )
    op.drop_table('signature_events')
    op.drop_index('ix_signature_requests_workspace_created', table_name='signature_requests')
    op.drop_index('ix_signature_requests_status_synced', table_name='signature_requests')
    op.drop_index(op.f('ix_signature_requests_job_id'), table_name='signature_requests')
    op.drop_index('ix_signature_requests_external', table_name='signature_requests')
    op.drop_table('signature_requests')
    op.drop_index(op.f('ix_signature_providers_workspace_id'), table_name='signature_providers')
    op.drop_table('signature_providers')
