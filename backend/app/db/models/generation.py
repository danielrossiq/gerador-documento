"""Jobs de geração, itens (linhas), arquivos gerados, importações e auditoria."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, UTCDateTime, check_in, utcnow

JOB_KINDS = ("single", "batch")
JOB_STATUS = ("queued", "processing", "succeeded", "partial", "failed", "cancelled")
ITEM_STATUS = ("pending", "processing", "succeeded", "failed", "skipped")
OUTPUT_FORMATS = ("docx", "pdf", "both")
FILE_KINDS = ("docx", "pdf", "zip", "report", "signed")  # signed: PDF assinado que voltou (D40)


class GenerationJob(IdMixin, Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_jobs_idempotency"),
        sa.Index("ix_jobs_ws_created", "workspace_id", "created_at"),
        sa.Index("ix_jobs_ws_status", "workspace_id", "status"),
        sa.Index("ix_jobs_status_heartbeat", "status", "heartbeat_at"),
        check_in("kind", JOB_KINDS, "kind"),
        check_in("status", JOB_STATUS, "status"),
        check_in("output_format", OUTPUT_FORMATS, "output_format"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("workspaces.id", ondelete="CASCADE"))
    generator_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="CASCADE"), index=True
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("template_versions.id"))
    compiled_file_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("template_files.id"))
    kind: Mapped[str] = mapped_column(sa.String(20))
    status: Mapped[str] = mapped_column(sa.String(20), default="queued")
    output_format: Mapped[str] = mapped_column(sa.String(10), default="docx")
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    filename_pattern: Mapped[str] = mapped_column(sa.String(200))
    fields_snapshot: Mapped[Any] = mapped_column(JSONType)  # definição dos campos usada nesta geração
    total_items: Mapped[int] = mapped_column(sa.Integer, default=0)
    succeeded_items: Mapped[int] = mapped_column(sa.Integer, default=0)
    failed_items: Mapped[int] = mapped_column(sa.Integer, default=0)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("generation_jobs.id"), nullable=True
    )
    # Preenchido quando este job é um dos documentos de um kit (ver app.db.models.kits.KitRun); o job em si
    # é um job comum (kind='single'), sem nenhuma regra especial no runner/worker.
    kit_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("kit_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    bytes_total: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Último sinal de vida do executor. Job 'processing' sem heartbeat recente é considerado abandonado
    # (worker morto) e retomado pelo watchdog; o runner é idempotente, então a retomada não duplica arquivos.
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class GenerationItem(IdMixin, Base):
    __tablename__ = "generation_items"
    __table_args__ = (
        sa.UniqueConstraint("job_id", "row_index"),
        sa.Index("ix_items_job_status", "job_id", "status"),
        check_in("status", ITEM_STATUS, "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("generation_jobs.id", ondelete="CASCADE"))
    row_index: Mapped[int] = mapped_column(sa.Integer)  # 1-based, como na grade
    status: Mapped[str] = mapped_column(sa.String(20), default="pending")
    values: Mapped[Any] = mapped_column(JSONType)  # valores canônicos por nome do campo
    filename: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class GeneratedFile(IdMixin, Base):
    """Arquivo de saída (docx/pdf de um item, ou zip/report de um lote). Sempre pertence a exatamente um job
    OU a um kit_run (o zip/relatório consolidado do kit — ver `app.modules.kits.service.build_bundle`); nunca
    aos dois nem a nenhum. Isso deixa o restante do sistema (link assinado, expiração/retenção, streaming)
    igual para os três, sem precisar saber a origem do arquivo."""

    __tablename__ = "generated_files"
    __table_args__ = (
        sa.Index("ix_generated_job", "job_id"),
        sa.Index("ix_generated_kit_run", "kit_run_id"),
        sa.Index("ix_generated_expires", "expires_at"),
        check_in("kind", FILE_KINDS, "kind"),
        sa.CheckConstraint(
            "(job_id IS NULL) != (kit_run_id IS NULL)", name="ck_generated_files_job_xor_kit_run"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=True
    )
    kit_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("kit_runs.id", ondelete="CASCADE"), nullable=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("generation_items.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(sa.String(20))
    filename: Mapped[str] = mapped_column(sa.String(255))
    storage_key: Mapped[str] = mapped_column(sa.String(300), unique=True)
    content_type: Mapped[str] = mapped_column(sa.String(150))
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    sha256: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BatchImport(IdMixin, Base):
    """Planilha enviada para importação (linhas brutas ficam aqui até o mapeamento ser aplicado)."""

    __tablename__ = "batch_imports"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    generator_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(sa.String(300))
    columns: Mapped[Any] = mapped_column(JSONType)  # cabeçalhos detectados
    rows: Mapped[Any] = mapped_column(JSONType)  # matriz de strings
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuditEvent(IdMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (sa.Index("ix_audit_ws_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(sa.String(80))
    entity_type: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    meta: Mapped[Any] = mapped_column("metadata", JSONType, nullable=True)  # nunca conteúdo sensível
    ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
