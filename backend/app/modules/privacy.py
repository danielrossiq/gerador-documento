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

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.adapters.storage import StorageAdapter, get_storage
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import AuthIdentity, Base, GeneratedFile, TemplateFile, User, Workspace, WorkspaceMember
from app.db.session import get_factory

log = get_logger(__name__)


@dataclass
class PurgeResult:
    found: bool
    removed_files: int = 0
    failed_keys: list[str] = field(default_factory=list)
    records_deleted: bool = False
    users_deleted: int = 0

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
        member_ids = list(
            db.scalars(select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == ws_id))
        )
        # DELETE direto: as FKs com ON DELETE CASCADE removem membros, sessões, geradores, versões, campos, jobs,
        # itens, arquivos… (db.delete(ws) pelo ORM tentava anular workspace_members.workspace_id e falhava)
        db.execute(delete(Workspace).where(Workspace.id == ws_id))
        # contas que ficaram sem nenhum workspace saem junto (nome, e-mail, hash de senha; sessões, tokens de
        # recuperação e identidades caem em cascata). Quem é membro de outro workspace continua.
        orphans = [
            uid
            for uid in member_ids
            if not db.scalar(
                select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.user_id == uid)
            )
        ]
        if orphans:
            db.execute(delete(User).where(User.id.in_(orphans)))
        db.commit()  # workspace e contas órfãs na MESMA transação: uma nova tentativa nunca deixa conta sobrando
    result.records_deleted = True
    result.users_deleted = len(orphans)
    return result


# ------------------------------------------------------------------ exportação (portabilidade)

# nunca exportados: segredos e identificadores técnicos que não são dados do titular
_SECRET_COLUMNS = {"password_hash", "token_hash", "csrf_token", "idempotency_key"}
_SKIP_TABLES = {"user_sessions"}  # sessões de login: segredo operacional, não dado do titular


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool, dict, list)):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (uuid.UUID, Decimal)):
        return str(v)
    if isinstance(v, bytes):
        return None  # nenhuma coluna binária hoje; por garantia, nunca embute bytes no JSON
    return str(v)


def _row(table: Any, row: Any) -> dict[str, Any]:
    return {c.name: _jsonable(row._mapping[c]) for c in table.columns if c.name not in _SECRET_COLUMNS}


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:120] or "arquivo"


def export_workspace(ws_id: uuid.UUID, out: Path, files_dir: Path | None = None) -> dict[str, Any]:
    """JSON com TODAS as tabelas do workspace (exceto sessões) e os dados de conta dos membros, sem segredos.
    Com `files_dir`, copia também os arquivos do storage (modelos enviados/compilados e documentos gerados) e
    registra no JSON onde cada um foi salvo. Devolve um resumo (contagens e falhas)."""
    storage = get_storage() if files_dir else None
    data: dict[str, Any] = {"formato": "minuta-export-v2", "gerado_em": utcnow().isoformat(), "tabelas": {}}
    summary: dict[str, Any] = {"tabelas": {}, "arquivos": 0, "falhas_arquivo": 0}
    with get_factory()() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            raise LookupError("workspace não encontrado")
        data["workspace"] = _row(
            Workspace.__table__, db.execute(select(Workspace.__table__).where(Workspace.id == ws_id)).one()
        )
        for table in Base.metadata.sorted_tables:
            if "workspace_id" not in table.columns or table.name in _SKIP_TABLES:
                continue
            rows = [_row(table, r) for r in db.execute(select(table).where(table.c.workspace_id == ws_id))]
            data["tabelas"][table.name] = rows
            summary["tabelas"][table.name] = len(rows)
        member_ids = [m["user_id"] for m in data["tabelas"].get("workspace_members", [])]
        users = db.execute(
            select(User.__table__).where(User.id.in_([uuid.UUID(u) for u in member_ids]))
        ).all()
        data["usuarios"] = [_row(User.__table__, u) for u in users]
        idents = db.execute(
            select(AuthIdentity.user_id, AuthIdentity.provider).where(
                AuthIdentity.user_id.in_([uuid.UUID(u) for u in member_ids])
            )
        ).all()
        data["identidades_login"] = [{"user_id": str(i.user_id), "provider": i.provider} for i in idents]

    if files_dir is not None and storage is not None:
        files_dir.mkdir(parents=True, exist_ok=True)
        for tname in ("template_files", "generated_files"):
            for rec in data["tabelas"].get(tname, []):
                name = rec.get("original_filename") or rec.get("filename") or Path(rec["storage_key"]).name
                dest = files_dir / tname / f"{rec['id']}_{_safe_name(str(name))}"
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(storage.get(rec["storage_key"]))
                    rec["arquivo_exportado"] = dest.relative_to(files_dir).as_posix()
                    summary["arquivos"] += 1
                except Exception as exc:  # expirado/apagado ou storage fora: registra, não interrompe
                    rec["arquivo_exportado"] = None
                    rec["falha_exportacao"] = type(exc).__name__
                    summary["falhas_arquivo"] += 1
    data["observacao"] = (
        "Exportação do workspace: todas as tabelas do espaço de trabalho (exceto sessões de login) e os dados de "
        "conta dos membros, sem hashes de senha, tokens nem chaves de idempotência. Valores preenchidos estão em "
        "generation_items.values e batch_imports. Arquivos só vêm junto quando exportados com --files."
    )
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
