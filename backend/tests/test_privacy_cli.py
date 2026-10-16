"""Eliminação (purge-workspace) em duas fases, exportação (export-workspace) e cleanup monitorado."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app import cli
from app.adapters.storage import StorageError, get_storage
from app.db.base import utcnow
from app.db.models import GeneratedFile, TemplateFile, User, Workspace, WorkspaceMember
from app.db.session import get_factory
from app.modules.generation.runner import cleanup_expired_report
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


def test_export_covers_every_workspace_table_without_secrets(api, demo_docx, tmp_path):
    ws_id = _workspace_with_files(api, demo_docx)
    api.post("/samples/kit")  # kits também entram na exportação
    out = tmp_path / "export.json"
    assert cli.main(["export-workspace", str(ws_id), str(out)]) == 0
    raw = out.read_text(encoding="utf-8")
    data = json.loads(raw)
    tables = data["tabelas"]
    expected = {
        "document_generators", "template_versions", "template_blocks", "fields", "field_options",
        "field_occurrences", "field_suggestions", "template_files", "generation_jobs", "generation_items",
        "generated_files", "audit_events", "workspace_members", "document_kits", "document_kit_items",
        "kit_fields", "batch_imports", "kit_runs", "ai_analysis_runs", "kit_field_options",
    }  # fmt: skip
    assert expected <= set(tables)
    assert "user_sessions" not in tables
    assert tables["template_blocks"] and tables["generation_items"] and tables["document_kits"]
    assert "Maria Souza" in json.dumps(tables["generation_items"], ensure_ascii=False)  # valores preenchidos
    assert data["usuarios"] and all("password_hash" not in u for u in data["usuarios"])
    for secret in ("password_hash", "token_hash", "csrf_token", "idempotency_key", "argon2"):
        assert secret not in raw
    assert "PK" not in raw  # sem --files, nenhum binário
    assert all("arquivo_exportado" not in f for f in tables["generated_files"])


def test_export_with_files_copies_the_binaries(api, demo_docx, tmp_path):
    ws_id = _workspace_with_files(api, demo_docx)
    out, files = tmp_path / "export.json", tmp_path / "arquivos"
    assert cli.main(["export-workspace", str(ws_id), str(out), "--files", str(files)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    recs = data["tabelas"]["template_files"] + data["tabelas"]["generated_files"]
    assert recs and all(r["arquivo_exportado"] for r in recs)
    storage = get_storage()
    for r in recs:
        assert (files / r["arquivo_exportado"]).read_bytes() == storage.get(r["storage_key"])


def test_purge_removes_accounts_left_without_workspace_but_keeps_shared_ones(api, api2, demo_docx):
    ws_id = _workspace_with_files(api, demo_docx)
    owner_email = api.get("/auth/me").json()["user"]["email"]
    other = api2.register()
    other_ws = uuid.UUID(api2.get("/auth/me").json()["workspace"]["id"])
    with get_factory()() as db:  # a segunda pessoa também é membro do workspace eliminado
        uid = db.scalar(select(User.id).where(User.email == other["email"]))
        db.add(WorkspaceMember(workspace_id=ws_id, user_id=uid, role="member"))
        db.commit()
    r = purge_workspace(ws_id)
    assert r.records_deleted and r.users_deleted == 1
    with get_factory()() as db:
        assert (
            db.scalar(select(User).where(User.email == owner_email)) is None
        )  # sem outro workspace: removida
        kept = db.scalar(select(User).where(User.email == other["email"]))
        assert kept is not None  # continua: ainda é membro do próprio workspace
        assert (
            db.scalar(
                select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.user_id == kept.id)
            )
            == 1
        )
        assert db.get(Workspace, other_ws) is not None


def _expire_all(ws_id: uuid.UUID) -> int:
    with get_factory()() as db:
        files = db.scalars(select(GeneratedFile).where(GeneratedFile.workspace_id == ws_id)).all()
        for f in files:
            f.expires_at = utcnow() - timedelta(days=1)
        db.commit()
        return len(files)


def test_cleanup_removes_every_expired_file_in_batches(api, demo_docx):
    ws_id = _workspace_with_files(api, demo_docx)
    gid = api.get("/generators").json()["items"][0]["id"]
    for _ in range(2):
        api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES, "format": "docx"})
    n = _expire_all(ws_id)
    assert n >= 3
    report = cleanup_expired_report(batch=1)  # lote de 1: precisa repetir até zerar
    assert report == {"removidos": n, "falhas": 0, "pendentes": 0}
    with get_factory()() as db:
        left = db.scalars(select(GeneratedFile).where(GeneratedFile.workspace_id == ws_id)).all()
        assert all(f.deleted_at is not None for f in left)
        assert not any(get_storage().exists(f.storage_key) for f in left)


def test_cleanup_with_storage_failure_reports_pending_and_exits_1(api, demo_docx, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    ws_id = _workspace_with_files(api, demo_docx)
    n = _expire_all(ws_id)

    class Down:
        def delete(self, key: str) -> None:
            raise StorageError("S3 indisponível")

    monkeypatch.setattr("app.modules.generation.runner.get_storage", lambda: Down())
    assert cli.main(["cleanup"]) == 1
    out = capsys.readouterr().out
    assert f"falhas: {n}" in out and f"ainda pendentes: {n}" in out


def test_cleanup_exit_code_reports_failures(monkeypatch, capsys):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "app.modules.generation.runner.cleanup_expired_report",
        lambda batch=500: {"removidos": 3, "falhas": 1, "pendentes": 1},
    )
    assert cli.main(["cleanup"]) == 1
    assert "falhas: 1" in capsys.readouterr().out
    monkeypatch.setattr(
        "app.modules.generation.runner.cleanup_expired_report",
        lambda batch=500: {"removidos": 0, "falhas": 0, "pendentes": 2},
    )
    assert cli.main(["cleanup"]) == 1  # pendentes sem falha (ex.: limite de lotes) também alerta
    monkeypatch.setattr(
        "app.modules.generation.runner.cleanup_expired_report",
        lambda batch=500: {"removidos": 0, "falhas": 0, "pendentes": 0},
    )
    assert cli.main(["cleanup"]) == 0
