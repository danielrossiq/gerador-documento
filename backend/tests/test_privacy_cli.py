"""Eliminação (purge-workspace) em duas fases, exportação (export-workspace) e cleanup monitorado."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select

from app import cli
from app.adapters.storage import StorageError, get_storage
from app.db.models import GeneratedFile, TemplateFile, Workspace
from app.db.session import get_factory
from app.modules.privacy import purge_workspace
from tests.flows import SAMPLE_VALUES, build_generator


def _workspace_with_files(api, demo_docx) -> uuid.UUID:  # type: ignore[no-untyped-def]
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    job = api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES, "format": "docx"}).json()
    assert job["status"] == "succeeded"
    return uuid.UUID(api.get("/auth/me").json()["workspace"]["id"])


def _keys(ws_id: uuid.UUID) -> list[str]:
    with get_factory()() as db:
        keys = list(db.scalars(select(TemplateFile.storage_key).where(TemplateFile.workspace_id == ws_id)))
        keys += list(db.scalars(select(GeneratedFile.storage_key).where(GeneratedFile.workspace_id == ws_id)))
    return keys


class FlakyStorage:
    """Storage que falha ao apagar a primeira chave — simula S3 fora do ar no meio da eliminação."""

    def __init__(self, fail_key: str) -> None:
        self.real, self.fail_key = get_storage(), fail_key

    def delete(self, key: str) -> None:
        if key == self.fail_key:
            raise StorageError("S3 indisponível")
        self.real.delete(key)


def test_purge_keeps_records_when_storage_fails_and_finishes_on_retry(api, demo_docx):
    ws_id = _workspace_with_files(api, demo_docx)
    keys = _keys(ws_id)
    assert len(keys) >= 3  # original, compilado e documento gerado
    storage = get_storage()
    assert all(storage.exists(k) for k in keys)

    r1 = purge_workspace(ws_id, storage=FlakyStorage(keys[0]))  # type: ignore[arg-type]
    assert r1.pending and r1.failed_keys == [keys[0]] and r1.removed_files == len(keys) - 1
    with get_factory()() as db:
        ws = db.get(Workspace, ws_id)
        assert ws is not None and ws.deleted_at is not None  # pendente: registros mantidos, acesso bloqueado
        assert db.scalar(
            select(func.count()).select_from(TemplateFile).where(TemplateFile.workspace_id == ws_id)
        )
    assert storage.exists(keys[0])
    assert api.get("/auth/me").status_code == 401  # ninguém usa um workspace em eliminação

    r2 = purge_workspace(ws_id)  # nova tentativa: idempotente
    assert r2.records_deleted and not r2.pending and not r2.failed_keys
    assert not any(storage.exists(k) for k in keys)
    with get_factory()() as db:
        assert db.get(Workspace, ws_id) is None
        assert not db.scalar(
            select(func.count()).select_from(TemplateFile).where(TemplateFile.workspace_id == ws_id)
        )


def test_purge_cli_exit_codes(api, demo_docx, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    ws_id = _workspace_with_files(api, demo_docx)
    assert cli.main(["purge-workspace", str(ws_id)]) == 2  # sem --yes não faz nada
    first = _keys(ws_id)[0]
    real = purge_workspace
    monkeypatch.setattr(
        "app.modules.privacy.purge_workspace",
        lambda w: real(w, storage=FlakyStorage(first)),  # type: ignore[arg-type]
    )
    assert cli.main(["purge-workspace", str(ws_id), "--yes"]) == 1
    assert "ELIMINAÇÃO PENDENTE" in capsys.readouterr().err
    monkeypatch.setattr("app.modules.privacy.purge_workspace", real)
    assert cli.main(["purge-workspace", str(ws_id), "--yes"]) == 0
    assert cli.main(["purge-workspace", str(ws_id), "--yes"]) == 0  # já eliminado: nada a fazer


def test_export_has_metadata_and_values_but_no_file_contents(api, demo_docx, tmp_path):
    ws_id = _workspace_with_files(api, demo_docx)
    out = tmp_path / "export.json"
    assert cli.main(["export-workspace", str(ws_id), str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert {"generators", "versions", "fields", "jobs", "items", "files", "audit_events"} <= set(data)
    assert data["generators"] and data["fields"] and data["files"]
    assert "Maria Souza" in json.dumps(data["items"], ensure_ascii=False)  # valores preenchidos vão no export
    raw = out.read_text(encoding="utf-8")
    assert "PK\u0003\u0004" not in raw and "word/document.xml" not in raw  # nenhum .docx embutido
    assert all("storage_key" in f for f in data["files"])  # só a referência ao arquivo


def test_cleanup_exit_code_reports_failures(monkeypatch, capsys):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "app.modules.generation.runner.cleanup_expired_report",
        lambda batch=500: {"removidos": 3, "falhas": 1, "pendentes": 1},
    )
    assert cli.main(["cleanup"]) == 1
    assert "falhas: 1" in capsys.readouterr().out
    monkeypatch.setattr(
        "app.modules.generation.runner.cleanup_expired_report",
        lambda batch=500: {"removidos": 0, "falhas": 0, "pendentes": 0},
    )
    assert cli.main(["cleanup"]) == 0
