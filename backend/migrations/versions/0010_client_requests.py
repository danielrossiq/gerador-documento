"""link para o cliente preencher (D39): pedidos de dados com token (só o hash), campos pedidos e a resposta;
sinal de vida do teste grátis (trials.heartbeat_at, achado QA-6)

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.create_table('client_requests',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('generator_id', sa.Uuid(), nullable=True),
    sa.Column('kit_id', sa.Uuid(), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('message', sa.String(length=1000), nullable=True),
    sa.Column('fields', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('prefill', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('prefill_mode', sa.String(length=20), nullable=False),
    sa.Column('allow_photos', sa.Boolean(), nullable=False),
    sa.Column('photo_reads', sa.Integer(), nullable=False),
    sa.Column('values', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('submissions', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("prefill_mode IN ('hidden', 'readonly', 'editable')", name=op.f('ck_client_requests_prefill_mode')),
    sa.CheckConstraint("status IN ('open', 'answered', 'cancelled')", name=op.f('ck_client_requests_status')),
    sa.CheckConstraint('(generator_id IS NULL) != (kit_id IS NULL)', name=op.f('ck_client_requests_one_target')),
    sa.CheckConstraint('photo_reads >= 0 AND photo_reads <= 10', name=op.f('ck_client_requests_photo_reads_range')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_client_requests_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['generator_id'], ['document_generators.id'], name=op.f('fk_client_requests_generator_id_document_generators'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['kit_id'], ['document_kits.id'], name=op.f('fk_client_requests_kit_id_document_kits'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_client_requests_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_requests')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_client_requests_token_hash'))
    )
    op.create_index(op.f('ix_client_requests_generator_id'), 'client_requests', ['generator_id'], unique=False)
    op.create_index(op.f('ix_client_requests_kit_id'), 'client_requests', ['kit_id'], unique=False)
    op.create_index('ix_client_requests_workspace_status', 'client_requests', ['workspace_id', 'status', 'created_at'], unique=False)
    op.add_column('trials', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))



def downgrade() -> None:
    op.drop_column('trials', 'heartbeat_at')

    op.drop_index('ix_client_requests_workspace_status', table_name='client_requests')
    op.drop_index(op.f('ix_client_requests_kit_id'), table_name='client_requests')
    op.drop_index(op.f('ix_client_requests_generator_id'), table_name='client_requests')
    op.drop_table('client_requests')

