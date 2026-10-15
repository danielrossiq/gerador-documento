"""Kit de documentos: vários geradores diferentes preenchidos de uma vez com as mesmas variáveis
compartilhadas (ex.: nome, CPF, endereço) — ver docs/DECISIONS.md D24."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime, check_in, utcnow
from app.modules.fields.types import FIELD_TYPES

KIT_STATUS = ("active", "archived")


class DocumentKit(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_kits"
    __table_args__ = (
        check_in("status", KIT_STATUS, "status"),
        sa.Index("ix_kits_ws_status", "workspace_id", "status", "deleted_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="active")
    is_pinned: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    filename_pattern: Mapped[str] = mapped_column(sa.String(200), default="{modelo}_{hoje}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # soft delete


class DocumentKitItem(IdMixin, Base):
    """Um documento (gerador existente) dentro do kit, com o mapeamento dos campos compartilhados do kit para
    os campos daquele gerador. Campos do gerador que não aparecem em `field_mapping` continuam preenchíveis
    no formulário do kit, agrupados por documento (como campos "só deste documento")."""

    __tablename__ = "document_kit_items"
    __table_args__ = (
        sa.UniqueConstraint("kit_id", "generator_id"),
        sa.Index("ix_kit_items_kit_position", "kit_id", "position"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kit_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_kits.id", ondelete="CASCADE"), index=True
    )
    generator_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_generators.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(sa.Integer, default=0)
    field_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict
    )  # {campo_do_kit: campo_do_gerador}
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class KitField(IdMixin, Base):
    """Campo compartilhado do kit (ex.: nome, CPF, endereço): preenchido uma vez e distribuído para todo
    documento membro cujo mapeamento o usa. Mesmo vocabulário de tipos de `fields` (`FIELD_TYPES`)."""

    __tablename__ = "kit_fields"
    __table_args__ = (
        sa.UniqueConstraint("kit_id", "name"),
        check_in("type", FIELD_TYPES, "type"),
        sa.Index("ix_kit_fields_kit_position", "kit_id", "position"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kit_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_kits.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(64))  # nome técnico snake_case
    label: Mapped[str] = mapped_column(sa.String(200))
    type: Mapped[str] = mapped_column(sa.String(30))
    description: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    required: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    default_value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    example: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    mask: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    position: Mapped[int] = mapped_column(sa.Integer, default=0)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


class KitFieldOption(IdMixin, Base):
    __tablename__ = "kit_field_options"
    __table_args__ = (sa.UniqueConstraint("kit_field_id", "value"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kit_field_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("kit_fields.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(sa.String(200))
    value: Mapped[str] = mapped_column(sa.String(200))
    position: Mapped[int] = mapped_column(sa.Integer, default=0)


class KitRun(IdMixin, Base):
    """Uma geração do kit: cria um `GenerationJob` comum (kind='single') por documento membro, todos marcados
    com este `kit_run_id`. Reaproveita toda a fila/retentativa/idempotência/watchdog dos jobs normais — o
    status do kit é sempre derivado dos jobs (`app.modules.kits.service.aggregate_status`), nunca guardado
    aqui, para não duplicar a máquina de estados já testada de `GenerationJob`."""

    __tablename__ = "kit_runs"
    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_kit_runs_idempotency"),
        sa.Index("ix_kit_runs_ws_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kit_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_kits.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    output_format: Mapped[str] = mapped_column(sa.String(10), default="docx")
    filename_pattern: Mapped[str] = mapped_column(sa.String(200))
    values_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONType
    )  # o que foi preenchido (compartilhado + por documento)
    total_members: Mapped[int] = mapped_column(sa.Integer, default=0)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("kit_runs.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
