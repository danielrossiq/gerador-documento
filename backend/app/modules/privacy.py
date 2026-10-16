"""Eliminação de workspace (LGPD) em duas fases, sem deixar arquivo órfão no storage.

1. Marca o workspace como "eliminação pendente" (`workspaces.deleted_at`): a partir daí ninguém mais acessa
   (deps.get_ctx recusa workspace com deleted_at) e o estado sobrevive a uma falha no meio do caminho.
2. Apaga do storage TODOS os arquivos do workspace (modelos enviados/compilados e documentos gerados).
3. Só se o storage confirmou todas as remoções, apaga os registros do banco (cascata a partir do workspace).

Se alguma remoção falhar, os registros ficam no banco (com as chaves dos arquivos que faltam) e a eliminação
continua pendente: basta rodar de novo (`python -m app.cli purge-workspace ID --yes`), que é idempotente —
remover de novo uma chave já apagada não é erro no S3 nem no storage local.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select

from app.adapters.storage import StorageAdapter, get_storage
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import GeneratedFile, TemplateFile, Workspace
from app.db.session import get_factory

log = get_logger(__name__)


@dataclass
class PurgeResult:
    found: bool
    removed_files: int = 0
    failed_keys: list[str] = field(default_factory=list)
    records_deleted: bool = False

    @property
    def pending(self) -> bool:
        return self.found and not self.records_deleted


def workspace_storage_keys(db, ws_id: uuid.UUID) -> list[str]:  # type: ignore[no-untyped-def]
    keys = list(db.scalars(select(TemplateFile.storage_key).where(TemplateFile.workspace_id == ws_id)))
    keys += list(db.scalars(select(GeneratedFile.storage_key).where(GeneratedFile.workspace_id == ws_id)))
    return keys


def purge_workspace(ws_id: uuid.UUID, storage: StorageAdapter | None = None) -> PurgeResult:
    storage = storage or get_storage()
    factory = get_factory()
    with factory() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            return PurgeResult(found=False)
        if ws.deleted_at is None:
            ws.deleted_at = utcnow()  # eliminação pendente: bloqueia acesso já
            db.commit()
        keys = workspace_storage_keys(db, ws_id)

    result = PurgeResult(found=True)
    for key in keys:
        try:
            storage.delete(key)
            result.removed_files += 1
        except Exception as exc:  # qualquer falha mantém os registros para tentar de novo
            result.failed_keys.append(key)
            log.warning("purge_falhou_para_arquivo", extra={"error": type(exc).__name__})

    if result.failed_keys:
        log.warning(
            "purge_pendente",
            extra={"workspace_id": str(ws_id), "falhas": len(result.failed_keys)},
        )
        return result

    with factory() as db:
        # DELETE direto: as FKs com ON DELETE CASCADE removem membros, geradores, versões, campos, jobs, itens,
        # arquivos… (db.delete(ws) pelo ORM tentava anular workspace_members.workspace_id e falhava)
        db.execute(delete(Workspace).where(Workspace.id == ws_id))
        db.commit()
    result.records_deleted = True
    return result
