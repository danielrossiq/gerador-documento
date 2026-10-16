"""Geradores, versões do modelo, arquivos, blocos, campos, opções, ocorrências e sugestões."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime, check_in, utcnow

GENERATOR_STATUS = ("active", "archived")
ANALYSIS_STATUS = ("pending", "running", "done", "failed", "skipped")
FIELD_TYPES = (
    "text_short",
    "text_long",
    "number",
    "currency",
    "date",
    "cpf",
    "cnpj",
    "cep",
    "email",
    "phone",
    "oab",
    "select",
    "yes_no",
    "checkbox",
)
BLOCK_KINDS = ("paragraph", "table", "opaque")
SUGGESTION_STATUS = ("pending", "accepted", "ignored")


class DocumentGenerator(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_generators"
    __table_args__ = (
        check_in("status", GENERATOR_STATUS, "status"),
        sa.Index("ix_generators_ws_status", "workspace_id", "status", "deleted_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="active")
    is_pinned: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    # A versão que o gerador usa agora (editor, formulário, lote). Sem estados de rascunho/publicação: salvar já
    # deixa o gerador pronto para uso; enviar um novo arquivo ou restaurar uma versão antiga troca este ponteiro.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(
            "template_versions.id", ondelete="SET NULL", use_alter=True, name="fk_generators_current_version"
        ),
        nullable=True,
    )
    filename_pattern: Mapped[str] = mapped_column(sa.String(200), default="{modelo}_{linha}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # soft delete


class TemplateFile(IdMixin, Base):
    """Arquivo imutável (original enviado ou gabarito compilado)."""

    __tablename__ = "template_files"
    __table_args__ = (check_in("role", ("source", "compiled"), "role"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    generator_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="CASCADE"), index=True, nullable=True
    )
    role: Mapped[str] = mapped_column(sa.String(20))
    storage_key: Mapped[str] = mapped_column(sa.String(300), unique=True)
    original_filename: Mapped[str] = mapped_column(sa.String(300))
    content_type: Mapped[str] = mapped_column(sa.String(150))
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    sha256: Mapped[str] = mapped_column(sa.String(64), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TemplateVersion(IdMixin, TimestampMixin, Base):
    """Uma versão do modelo (arquivo de origem + blocos + campos). Histórico imutável: cada envio de um novo

    arquivo ou restauração cria uma linha nova; qual delas está em uso é `DocumentGenerator.current_version_id`.
    """

    __tablename__ = "template_versions"
    __table_args__ = (
        sa.UniqueConstraint("generator_id", "version_number"),
        check_in("analysis_status", ANALYSIS_STATUS, "analysis_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    generator_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(sa.Integer)
    revision: Mapped[int] = mapped_column(sa.Integer, default=1)  # concorrência otimista do editor
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("template_files.id"), nullable=True
    )
    # Cache do gabarito compilado: evita recompilar (e regravar no storage) a cada geração. Só é reaproveitado
    # enquanto `compiled_revision == revision`; qualquer alteração de conteúdo invalida o cache automaticamente.
    compiled_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("template_files.id"), nullable=True
    )
    compiled_revision: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    based_on_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("template_versions.id"), nullable=True
    )
    analysis_status: Mapped[str] = mapped_column(sa.String(20), default="pending")
    analysis_error: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSONType, nullable=True
    )  # partes, estatísticas e avisos do parse
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TemplateBlock(IdMixin, Base):
    """Bloco do documento (parágrafo, tabela ou elemento opaco) com chave estável no DOCX original."""

    __tablename__ = "template_blocks"
    __table_args__ = (
        sa.UniqueConstraint("version_id", "key"),
        sa.Index("ix_blocks_version_container", "version_id", "container_key", "ordinal"),
        check_in("kind", BLOCK_KINDS, "kind"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("template_versions.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(sa.String(200))
    part: Mapped[str] = mapped_column(sa.String(60))  # body, header1, footer1…
    container_key: Mapped[str] = mapped_column(sa.String(200))  # body | header1 | body/t1/r1/c1
    ordinal: Mapped[int] = mapped_column(sa.Integer)
    kind: Mapped[str] = mapped_column(sa.String(20), default="paragraph")
    origin: Mapped[str] = mapped_column(sa.String(20), default="original")  # original | inserted
    content: Mapped[Any] = mapped_column(JSONType)  # inline nodes (parágrafo) ou grade (tabela)
    attrs: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    text: Mapped[str] = mapped_column(sa.Text, default="")  # texto plano com campos expandidos ao `sample`
    source_text: Mapped[str] = mapped_column(sa.Text, default="")  # texto original do DOCX


class Field(IdMixin, TimestampMixin, Base):
    __tablename__ = "fields"
    __table_args__ = (
        sa.UniqueConstraint("version_id", "name"),
        check_in("type", FIELD_TYPES, "type"),
        sa.Index("ix_fields_version_position", "version_id", "position"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("template_versions.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(sa.String(64))  # nome técnico snake_case
    label: Mapped[str] = mapped_column(sa.String(200))
    type: Mapped[str] = mapped_column(sa.String(30))
    description: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    required: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    default_value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    example: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    mask: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    group_name: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    position: Mapped[int] = mapped_column(sa.Integer, default=0)
    include_in_batch: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)  # min/max/casas/formato


class FieldOption(IdMixin, Base):
    __tablename__ = "field_options"
    __table_args__ = (sa.UniqueConstraint("field_id", "value"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    field_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("fields.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(sa.String(200))
    value: Mapped[str] = mapped_column(sa.String(200))
    position: Mapped[int] = mapped_column(sa.Integer, default=0)


class FieldOccurrence(IdMixin, Base):
    """Âncora de um campo no documento: bloco + offsets + trecho original + contexto."""

    __tablename__ = "field_occurrences"
    __table_args__ = (
        sa.Index("ix_occurrences_field", "field_id"),
        sa.Index("ix_occurrences_version", "version_id", "ordinal"),
        check_in("status", ("ok", "orphaned"), "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("template_versions.id", ondelete="CASCADE"))
    field_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("fields.id", ondelete="CASCADE"))
    block_key: Mapped[str] = mapped_column(sa.String(200))
    ordinal: Mapped[int] = mapped_column(sa.Integer)
    start_offset: Mapped[int] = mapped_column(sa.Integer)
    end_offset: Mapped[int] = mapped_column(sa.Integer)
    sample: Mapped[str] = mapped_column(sa.Text)
    context_before: Mapped[str] = mapped_column(sa.String(80), default="")
    context_after: Mapped[str] = mapped_column(sa.String(80), default="")
    status: Mapped[str] = mapped_column(sa.String(20), default="ok")


class AIAnalysisRun(IdMixin, Base):
    """Uma análise (regras + IA/local) de um arquivo. Reutilizada quando o hash não muda."""

    __tablename__ = "ai_analysis_runs"
    __table_args__ = (
        sa.Index("ix_analysis_cache", "workspace_id", "file_sha256", "provider", "prompt_version", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    generator_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="SET NULL"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("template_versions.id", ondelete="SET NULL"), nullable=True
    )
    file_sha256: Mapped[str] = mapped_column(sa.String(64))
    provider: Mapped[str] = mapped_column(sa.String(40))
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(sa.String(40))
    status: Mapped[str] = mapped_column(sa.String(20), default="running")
    reused_from_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("ai_analysis_runs.id"), nullable=True
    )
    result: Mapped[Any] = mapped_column(JSONType, nullable=True)  # sugestões brutas (estrutura variável)
    chars_sent: Mapped[int] = mapped_column(sa.Integer, default=0)
    tokens_in: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class FieldSuggestion(IdMixin, Base):
    __tablename__ = "field_suggestions"
    __table_args__ = (
        sa.Index("ix_suggestions_version", "version_id", "status"),
        check_in("status", SUGGESTION_STATUS, "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("template_versions.id", ondelete="CASCADE"))
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("ai_analysis_runs.id"), nullable=True
    )
    block_key: Mapped[str] = mapped_column(sa.String(200))
    start_offset: Mapped[int] = mapped_column(sa.Integer)
    end_offset: Mapped[int] = mapped_column(sa.Integer)
    text: Mapped[str] = mapped_column(sa.Text)
    context_before: Mapped[str] = mapped_column(sa.String(80), default="")
    context_after: Mapped[str] = mapped_column(sa.String(80), default="")
    suggested_name: Mapped[str] = mapped_column(sa.String(64))
    suggested_label: Mapped[str] = mapped_column(sa.String(200))
    suggested_type: Mapped[str] = mapped_column(sa.String(30))
    suggested_config: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    confidence: Mapped[float] = mapped_column(sa.Float)
    source: Mapped[str] = mapped_column(sa.String(20))  # rule | ai | local
    reason: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    location: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="pending")
    field_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("fields.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
