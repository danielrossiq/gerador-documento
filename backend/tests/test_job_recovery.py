"""Recuperação de jobs após queda do worker: claim atômico, heartbeat, watchdog e perda de posse.

Complementa o teste real com SIGKILL no Docker (ver docs/DEMO.md): aqui cobrimos as regras de forma determinística.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.errors import TransientError
from app.db.base import utcnow
from app.db.models import GeneratedFile, GenerationItem, GenerationJob
from app.db.session import get_factory
from app.modules.generation import runner
from tests.test_batch import _ready, _row


def _finished_job(api, demo_docx, n: int = 3) -> uuid.UUID:
    gid = _ready(api, demo_docx)
    job = api.post(f"/generators/{gid}/batches", json={"rows": [_row(i) for i in range(1, n + 1)]}).json()
    assert job["status"] == "succeeded"
    return uuid.UUID(job["id"])


def _simulate(
    jid: uuid.UUID,
    *,
    status: str,
    heartbeat_age: int | None,
    created_age: int | None = None,
    pending_rows: tuple[int, ...] = (3,),
) -> None:
    """Deixa o job como ficaria após uma queda no meio: sem `finished_at` e com alguns itens pendentes."""
    vals: dict = {
        "status": status,
        "finished_at": None,
        "heartbeat_at": None if heartbeat_age is None else utcnow() - timedelta(seconds=heartbeat_age),
    }
    if created_age is not None:
        vals["created_at"] = utcnow() - timedelta(seconds=created_age)
    with get_factory()() as db:
        db.execute(update(GenerationJob).where(GenerationJob.id == jid).values(**vals))
        for item in db.scalars(
            select(GenerationItem).where(
                GenerationItem.job_id == jid, GenerationItem.row_index.in_(pending_rows)
            )
        ):
            item.status = "pending"
        db.commit()


def _job(jid: uuid.UUID) -> GenerationJob:
    with get_factory()() as db:
        job = db.get(GenerationJob, jid)
        db.expunge(job)
        return job


def _docx_per_item(jid: uuid.UUID) -> list[int]:
    with get_factory()() as db:
        return [
            n
            for _, n in db.execute(
                select(GeneratedFile.item_id, func.count())
                .where(GeneratedFile.job_id == jid, GeneratedFile.kind == "docx")
                .group_by(GeneratedFile.item_id)
            ).all()
        ]


def test_job_with_live_heartbeat_is_not_taken_over(api, demo_docx):
    """Mensagem duplicada (redelivery + watchdog) não pode gerar duas execuções simultâneas."""
    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="processing", heartbeat_age=5)  # executor vivo: heartbeat de 5 s atrás
    attempts = _job(jid).attempts

    runner.run_generation_job(str(jid))

    job = _job(jid)
    assert job.status == "processing" and job.attempts == attempts  # ninguém assumiu
    assert runner.requeue_stuck_jobs(stale_seconds=60) == 0  # nem o watchdog mexe


def test_watchdog_resumes_abandoned_job_without_duplicating_files(api, demo_docx):
    jid = _finished_job(api, demo_docx)
    attempts = _job(jid).attempts
    _simulate(jid, status="processing", heartbeat_age=600, pending_rows=(2, 3))  # worker morreu há 10 min

    assert runner.requeue_stuck_jobs(stale_seconds=60) == 1  # backend "sync": retoma na hora

    job = _job(jid)
    assert job.status == "succeeded" and job.succeeded_items == 3 and job.failed_items == 0
    assert job.attempts == attempts + 1
    assert _docx_per_item(jid) == [1, 1, 1]  # exatamente um DOCX por item
    assert runner.requeue_stuck_jobs(stale_seconds=60) == 0  # concluído: nada mais a recuperar
    assert api.get(f"/jobs/{jid}").json()["status"] == "succeeded"


def test_watchdog_ignores_healthy_finished_and_cancelled_jobs(api, demo_docx):
    jid = _finished_job(api, demo_docx)
    assert runner.requeue_stuck_jobs(stale_seconds=0, queue_grace_seconds=0) == 0  # terminal nunca é tocado
    with get_factory()() as db:
        db.execute(update(GenerationJob).where(GenerationJob.id == jid).values(status="cancelled"))
        db.commit()
    assert runner.requeue_stuck_jobs(stale_seconds=0, queue_grace_seconds=0) == 0


def test_queued_job_whose_message_was_lost_is_requeued_after_grace(api, demo_docx):
    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="queued", heartbeat_age=None, created_age=3600, pending_rows=(1, 2, 3))

    assert runner.requeue_stuck_jobs(queue_grace_seconds=300) == 1

    job = _job(jid)
    assert job.status == "succeeded" and job.succeeded_items == 3
    assert _docx_per_item(jid) == [1, 1, 1]


def test_recently_queued_job_is_not_requeued(api, demo_docx):
    """Fila cheia é normal: enquanto dentro da tolerância, o watchdog não reenfileira."""
    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="queued", heartbeat_age=None, created_age=10, pending_rows=(1, 2, 3))
    assert runner.requeue_stuck_jobs(queue_grace_seconds=300) == 0
    assert _job(jid).status == "queued"


def test_only_one_watchdog_wins_each_job(api, demo_docx, monkeypatch):
    """Vários workers rodam o watchdog: cada job abandonado é reenfileirado uma única vez."""
    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="processing", heartbeat_age=600)
    sent: list[dict] = []
    monkeypatch.setattr("app.adapters.queue.enqueue", lambda name, **kw: sent.append({"name": name, **kw}))

    first = runner.requeue_stuck_jobs(stale_seconds=60)
    second = runner.requeue_stuck_jobs(stale_seconds=60)  # outro watchdog logo em seguida

    assert (first, second) == (1, 0)
    assert sent == [{"name": "generation", "job_id": str(jid)}]
    assert _job(jid).status == "queued"  # pronto para o worker assumir


def test_failed_enqueue_does_not_break_watchdog(api, demo_docx, monkeypatch):
    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="processing", heartbeat_age=600)

    def boom(*_a, **_k):
        raise ConnectionError("redis fora")

    monkeypatch.setattr("app.adapters.queue.enqueue", boom)
    assert (
        runner.requeue_stuck_jobs(stale_seconds=60) == 1
    )  # não propaga; fica 'queued' para a próxima rodada
    assert _job(jid).status == "queued"


def test_executor_stops_when_ownership_is_lost(api, demo_docx):
    """Se outro executor assumiu (attempts mudou), o antigo para sem gerar nem finalizar nada."""
    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="processing", heartbeat_age=1, pending_rows=(1, 2, 3))
    with get_factory()() as db:
        db.execute(update(GenerationJob).where(GenerationJob.id == jid).values(attempts=5))
        db.commit()
        job = db.get(GenerationJob, jid)
        from app.adapters.storage import get_storage

        with pytest.raises(runner._LostOwnership):
            runner._execute(db, job, get_storage(), 30, attempt=4)
        db.rollback()
    with get_factory()() as db:
        statuses = set(db.scalars(select(GenerationItem.status).where(GenerationItem.job_id == jid)))
    assert statuses == {"pending"}  # nenhum item foi tocado


def test_transient_failure_releases_claim_so_broker_retry_can_resume(api, demo_docx, monkeypatch):
    """Com Dramatiq, falha transitória re-lança para o broker repetir; o retry precisa conseguir assumir o job."""
    from app.adapters.storage import StorageError, get_storage

    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="queued", heartbeat_age=None, pending_rows=(1, 2, 3))
    settings = runner.get_settings()
    monkeypatch.setattr(
        runner, "get_settings", lambda: settings.model_copy(update={"job_backend": "dramatiq"})
    )
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    storage = get_storage()
    real_put = storage.put
    monkeypatch.setattr(storage, "put", lambda *a, **k: (_ for _ in ()).throw(StorageError("indisponível")))

    with pytest.raises(TransientError):
        runner.run_generation_job(str(jid))
    assert _job(jid).status == "queued"  # claim devolvido: o retry não fica bloqueado por um heartbeat fresco

    monkeypatch.setattr(storage, "put", real_put)  # storage voltou: é o retry do broker
    runner.run_generation_job(str(jid))
    job = _job(jid)
    assert job.status == "succeeded" and job.succeeded_items == 3
    assert _docx_per_item(jid) == [1, 1, 1]


def test_heartbeat_thread_renews_and_stops(api, demo_docx):
    jid = _finished_job(api, demo_docx)
    _simulate(jid, status="processing", heartbeat_age=600)
    attempt = _job(jid).attempts
    with get_factory()() as db:
        db.execute(update(GenerationJob).where(GenerationJob.id == jid).values(status="processing"))
        db.commit()
    with runner._Heartbeat(jid, attempt, interval=0.05):
        import time

        time.sleep(0.4)
    assert _job(jid).heartbeat_at is not None
    assert utcnow() - _job(jid).heartbeat_at < timedelta(seconds=30)  # renovado pela thread
