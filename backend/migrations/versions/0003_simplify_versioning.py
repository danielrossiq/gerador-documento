"""simplifica geradores: sem rascunho/publicado, versão atual única, fixar geradores

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- document_generators: fixar + ponteiro para a versão em uso
    op.add_column("document_generators", sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("document_generators", sa.Column("current_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_generators_current_version"),
        "document_generators",
        "template_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # current_version_id = o rascunho em edição (reflete melhor o que o usuário via por último no editor),
    # senão a versão publicada, senão a mais recente
    op.execute(
        """
        UPDATE document_generators g SET current_version_id = (
            SELECT v.id FROM template_versions v WHERE v.generator_id = g.id
            ORDER BY (v.status = 'draft') DESC, (v.status = 'published') DESC, v.version_number DESC
            LIMIT 1
        )
        """
    )

    # status: sem rascunho/publicado — todo gerador não arquivado vira "active"
    op.execute("UPDATE document_generators SET status = 'active' WHERE status IN ('draft', 'published')")
    op.drop_constraint(op.f("ck_document_generators_status"), "document_generators", type_="check")
    op.create_check_constraint(
        op.f("ck_document_generators_status"), "document_generators", "status IN ('active', 'archived')"
    )

    # ---- template_versions: remove o estado de rascunho/publicação; `compiled_file_id` deixa de marcar "a
    # versão publicada" e passa a ser só um cache (válido enquanto compiled_revision == revision)
    op.drop_index("uq_versions_one_draft", table_name="template_versions")
    op.drop_index("uq_versions_one_published", table_name="template_versions")
    op.drop_constraint(op.f("ck_template_versions_status"), "template_versions", type_="check")
    op.add_column("template_versions", sa.Column("compiled_revision", sa.Integer(), nullable=True))
    op.execute("UPDATE template_versions SET compiled_revision = revision WHERE compiled_file_id IS NOT NULL")
    op.drop_column("template_versions", "status")
    op.drop_column("template_versions", "content_hash")
    op.drop_column("template_versions", "published_at")

    # ---- generation_jobs: sem geração de teste (não havia mais rascunho para testar)
    op.drop_column("generation_jobs", "is_test")


def downgrade() -> None:
    op.add_column("generation_jobs", sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.add_column("template_versions", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("template_versions", sa.Column("content_hash", sa.String(length=64), nullable=True))
    # `compiled_file_id` nunca foi removido (virou cache); só o status volta
    op.add_column("template_versions", sa.Column("status", sa.String(length=20), nullable=False, server_default="published"))
    op.create_check_constraint(
        op.f("ck_template_versions_status"), "template_versions", "status IN ('draft', 'published', 'superseded')"
    )
    op.create_index(
        "uq_versions_one_draft", "template_versions", ["generator_id"], unique=True,
        postgresql_where=sa.text("status = 'draft'"), sqlite_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "uq_versions_one_published", "template_versions", ["generator_id"], unique=True,
        postgresql_where=sa.text("status = 'published'"), sqlite_where=sa.text("status = 'published'"),
    )
    op.execute(
        """
        UPDATE template_versions v SET status = 'published'
        WHERE v.id = (SELECT g.current_version_id FROM document_generators g WHERE g.id = v.generator_id)
        """
    )

    op.drop_constraint(op.f("ck_document_generators_status"), "document_generators", type_="check")
    op.create_check_constraint(
        op.f("ck_document_generators_status"), "document_generators", "status IN ('draft', 'published', 'archived')"
    )
    op.execute(
        """
        UPDATE document_generators g SET status = CASE
            WHEN g.status = 'archived' THEN 'archived'
            WHEN EXISTS (SELECT 1 FROM template_versions v WHERE v.generator_id = g.id AND v.status = 'published')
                THEN 'published'
            ELSE 'draft'
        END
        """
    )
    op.drop_constraint(op.f("fk_generators_current_version"), "document_generators", type_="foreignkey")
    op.drop_column("document_generators", "current_version_id")
    op.drop_column("document_generators", "is_pinned")
    op.drop_column("template_versions", "compiled_revision")
