"""Execução de jobs de geração (worker/thread/sync). Idempotente e com isolamento por item.

* cada linha é gerada isoladamente: falha em um item não invalida o lote;
* itens já `succeeded` são pulados (reexecução/retry retoma de onde parou);
* falha transitória (storage/rede) interrompe a execução para o broker repetir; permanente marca só o item;
* ao final: ZIP + relatório CSV (lote) e status terminal explícito (succeeded | partial | failed | cancelled).
"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.adapters.pdf import (
    PdfConversionError,
    PdfConversionTimeout,
    PdfConverterUnavailable,
    get_pdf_converter,
)
from app.adapters.storage import StorageAdapter, get_storage
from app.core.config import get_settings
from app.core.errors import PermanentError, TransientError
from app.core.logging import get_logger, set_job_id
from app.db.base import utcnow
from app.db.models import GeneratedFile, GenerationItem, GenerationJob, TemplateFile
from app.db.session import get_factory
from app.docx_engine.render import CompiledTemplate
from app.modules.fields.normalize import format_value
from app.modules.fields.types import FieldDef

log = get_logger(__name__)
CHUNK = 20
TERMINAL = ("succeeded", "partial", "failed", "cancelled")
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CT = {
    "docx": DOCX_CT,
    "pdf": "application/pdf",
    "zip": "application/zip",
    "report": "text/csv; charset=utf-8",
}


def _retry[T](fn: Callable[[], T], tries: int = 3, base: float = 0.2) -> T:
    for attempt in range(tries):
        try:
            return fn()
        except TransientError:
            if attempt == tries - 1:
                raise
            time.sleep(base * (3**attempt))
    raise RuntimeError("inalcançável")


def mark_job_failed(job_id: str, code: str, message: str) -> None:
    if not job_id:
        return
    with get_factory()() as db:
        job = db.get(GenerationJob, uuid.UUID(job_id))
        if job is not None and job.status not in TERMINAL:
            job.status, job.error_code, job.error_message, job.finished_at = (
                "failed",
                code,
                message[:500],
                utcnow(),
            )
            db.commit()


class _LostOwnership(Exception):
    """Outro executor assumiu o job (o watchdog o considerou abandonado): este deve parar sem tocar em mais nada."""


class _Heartbeat:
    """Sinal de vida do executor: renova `heartbeat_at` numa thread própria enquanto o job roda.

    Independe do ritmo dos blocos (uma conversão de PDF lenta não faz o job parecer morto). Se o processo cair
    (SIGKILL, OOM, host reiniciado) a thread morre junto, o sinal para e o watchdog retoma o job.
    """

    def __init__(self, job_id: uuid.UUID, attempt: int, interval: float) -> None:
        self._job_id, self._attempt, self._interval = job_id, attempt, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="job-heartbeat")

    def __enter__(self) -> _Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                with get_factory()() as db:
                    res = db.execute(
                        update(GenerationJob)
                        .where(
                            GenerationJob.id == self._job_id,
                            GenerationJob.status == "processing",
                            GenerationJob.attempts == self._attempt,
                        )
                        .values(heartbeat_at=utcnow())
                        .execution_options(synchronize_session=False)
                    )
                    db.commit()
                    if res.rowcount != 1:  # type: ignore[attr-defined]
                        return  # posse perdida; o executor principal percebe no próximo bloco
            except Exception:
                log.warning("heartbeat_do_job_falhou", extra={"job_id": str(self._job_id)})


def claim_job(db: Session, job_id: uuid.UUID, stale_seconds: int) -> int | None:
    """Assume a execução do job de forma atômica (um único executor por vez). Devolve o nº da tentativa ou None.

    Só vale para job `queued`, ou `processing` cujo heartbeat está velho (executor morto). Assim, mensagens
    duplicadas (redelivery do broker + watchdog) nunca geram duas execuções simultâneas.
    """
    now = utcnow()
    res = db.execute(
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            or_(
                GenerationJob.status == "queued",
                and_(
                    GenerationJob.status == "processing",
                    or_(
                        GenerationJob.heartbeat_at.is_(None),
                        GenerationJob.heartbeat_at < now - timedelta(seconds=stale_seconds),
                    ),
                ),
            ),
        )
        .values(
            status="processing",
            heartbeat_at=now,
            attempts=GenerationJob.attempts + 1,
            started_at=func.coalesce(GenerationJob.started_at, now),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if res.rowcount != 1:  # type: ignore[attr-defined]
        return None
    return db.scalar(select(GenerationJob.attempts).where(GenerationJob.id == job_id))


def _release_claim(db: Session, job_id: uuid.UUID, attempt: int) -> None:
    """Devolve o job à fila (falha transitória): o retry do broker precisa conseguir assumi-lo de novo."""
    db.execute(
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.status == "processing",
            GenerationJob.attempts == attempt,
        )
        .values(status="queued", heartbeat_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    db.commit()


def run_generation_job(job_id: str) -> None:
    set_job_id(job_id)
    settings = get_settings()
    with get_factory()() as db:
        job = db.get(GenerationJob, uuid.UUID(job_id))
        if job is None:
            log.warning("job_inexistente")
            return
        if job.status in TERMINAL:
            return  # idempotente: já finalizado
        attempt = claim_job(db, job.id, settings.job_stale_seconds)
        if attempt is None:
            log.info("job_em_execucao_por_outro_worker")
            return
        db.refresh(job)
        started = time.monotonic()
        try:
            with _Heartbeat(job.id, attempt, settings.job_heartbeat_seconds):
                _execute(db, job, get_storage(), settings.file_retention_days, attempt)
        except _LostOwnership:
            db.rollback()
            log.warning("job_perdeu_a_posse_para_outro_executor", extra={"attempt": attempt})
        except TransientError as exc:
            db.rollback()
            log.warning("job_falha_transitoria", extra={"error_type": type(exc).__name__, "attempt": attempt})
            if settings.job_backend == "dramatiq":
                _release_claim(db, job.id, attempt)
                raise  # o broker repete (backoff); o runner retoma os itens pendentes
            _finish_failed(
                db, job, "TRANSIENT_ERROR", "Instabilidade temporária no armazenamento. Tente novamente."
            )
        except Exception as exc:
            db.rollback()
            log.exception("job_falhou", extra={"error_type": type(exc).__name__})
            _finish_failed(db, job, "JOB_CRASHED", "Erro inesperado ao processar a geração.")
        finally:
            log.info(
                "job_execucao_finalizada", extra={"duration_ms": int((time.monotonic() - started) * 1000)}
            )


def _stuck(now: Any, stale_seconds: int, queue_grace_seconds: int) -> Any:
    """Jobs abandonados: `processing` sem heartbeat recente, ou `queued` há tempo demais (mensagem perdida)."""
    return or_(
        and_(
            GenerationJob.status == "processing",
            or_(
                GenerationJob.heartbeat_at.is_(None),
                GenerationJob.heartbeat_at < now - timedelta(seconds=stale_seconds),
            ),
        ),
        and_(
            GenerationJob.status == "queued",
            func.coalesce(GenerationJob.heartbeat_at, GenerationJob.created_at)
            < now - timedelta(seconds=queue_grace_seconds),
        ),
    )


def requeue_stuck_jobs(stale_seconds: int | None = None, queue_grace_seconds: int | None = None) -> int:
    """Reenfileira jobs abandonados (worker morto, mensagem perdida). Seguro repetir e rodar em vários processos.

    O direito de reenfileirar é reservado por um UPDATE condicional (só um watchdog vence cada job) e a execução
    é protegida por `claim_job`; o runner é idempotente, então a retomada não duplica arquivos.
    """
    from app.adapters.queue import enqueue

    settings = get_settings()
    stale = settings.job_stale_seconds if stale_seconds is None else stale_seconds
    grace = settings.job_queue_grace_seconds if queue_grace_seconds is None else queue_grace_seconds
    now = utcnow()
    won: list[uuid.UUID] = []
    with get_factory()() as db:
        ids = list(db.scalars(select(GenerationJob.id).where(_stuck(now, stale, grace)).limit(50)))
        for jid in ids:
            res = db.execute(
                update(GenerationJob)
                .where(GenerationJob.id == jid, _stuck(now, stale, grace))
                .values(status="queued", heartbeat_at=now)
                .execution_options(synchronize_session=False)
            )
            db.commit()
            if res.rowcount == 1:  # type: ignore[attr-defined]
                won.append(jid)
    for jid in won:
        log.warning("job_abandonado_reenfileirado", extra={"job_id": str(jid)})
        try:
            enqueue("generation", job_id=str(jid))
        except Exception:
            log.exception("reenfileirar_job_falhou", extra={"job_id": str(jid)})
    return len(won)


def start_watchdog(interval: float | None = None) -> threading.Event:
    """Thread que reenfileira jobs abandonados a cada `interval` s. Devolve o evento que a encerra."""
    stop = threading.Event()
    every = get_settings().watchdog_interval_seconds if interval is None else interval

    def loop() -> None:
        while not stop.wait(every):
            try:
                requeue_stuck_jobs()
            except Exception:
                log.warning("watchdog_de_jobs_falhou", exc_info=True)

    threading.Thread(target=loop, daemon=True, name="job-watchdog").start()
    return stop


def _finish_failed(db: Session, job: GenerationJob, code: str, message: str) -> None:
    job = db.get(GenerationJob, job.id)  # type: ignore[assignment]
    assert job is not None
    if job.status not in TERMINAL:
        job.status, job.error_code, job.error_message, job.finished_at = "failed", code, message, utcnow()
        db.commit()


def _store(
    db: Session,
    storage: StorageAdapter,
    job: GenerationJob,
    item: GenerationItem | None,
    kind: str,
    filename: str,
    data: bytes,
    retention_days: int,
) -> GeneratedFile:
    import hashlib

    key = f"w/{job.workspace_id}/gen/{job.id}/{uuid.uuid4().hex}.{'csv' if kind == 'report' else kind}"
    _retry(lambda: storage.put(key, data, CT[kind]))
    gf = GeneratedFile(
        workspace_id=job.workspace_id,
        job_id=job.id,
        item_id=item.id if item else None,
        kind=kind,
        filename=filename[:255],
        storage_key=key,
        content_type=CT[kind],
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        expires_at=utcnow() + timedelta(days=retention_days),
    )
    db.add(gf)
    return gf


def _purge_item_files(db: Session, storage: StorageAdapter, item: GenerationItem) -> None:
    """Idempotência: se o item foi parcialmente processado antes, remove saídas antigas antes de refazer."""
    for f in db.scalars(select(GeneratedFile).where(GeneratedFile.item_id == item.id)):
        with contextlib.suppress(TransientError):
            storage.delete(f.storage_key)
        db.delete(f)


def _check_ownership(job: GenerationJob, attempt: int) -> None:
    if job.attempts != attempt or job.status not in ("processing", "cancelled"):
        raise _LostOwnership


def _execute(
    db: Session, job: GenerationJob, storage: StorageAdapter, retention_days: int, attempt: int
) -> None:
    compiled_row = db.get(TemplateFile, job.compiled_file_id)
    assert compiled_row is not None
    template = CompiledTemplate(_retry(lambda: storage.get(compiled_row.storage_key)))
    defs = [FieldDef.from_snapshot(s) for s in job.fields_snapshot]
    want_docx = job.output_format in ("docx", "both")
    want_pdf = job.output_format in ("pdf", "both")
    converter = get_pdf_converter()

    pending = list(
        db.scalars(
            select(GenerationItem)
            .where(GenerationItem.job_id == job.id, GenerationItem.status.in_(("pending", "processing")))
            .order_by(GenerationItem.row_index)
        )
    )
    for i in range(0, len(pending), CHUNK):
        db.refresh(job)
        _check_ownership(job, attempt)
        if job.status == "cancelled":
            break
        chunk = pending[i : i + CHUNK]
        rendered: dict[uuid.UUID, bytes] = {}
        for item in chunk:
            _purge_item_files(db, storage, item)
            item.status, item.attempts, item.started_at = "processing", item.attempts + 1, utcnow()
            try:
                text_values = {d.name: format_value(d, (item.values or {}).get(d.name)) for d in defs}
                rendered[item.id] = template.render(text_values)
            except Exception:
                item.status, item.error_code = "failed", "RENDER_FAILED"
                item.error_message, item.finished_at = (
                    "Não foi possível montar o documento desta linha.",
                    utcnow(),
                )
                log.warning("item_render_falhou", extra={"row": item.row_index})
        pdfs: dict[str, bytes | Exception] = {}
        if want_pdf and rendered:
            pdfs = converter.convert_many([(str(k), v) for k, v in rendered.items()])
        for item in chunk:
            if item.id not in rendered:
                continue
            errors: list[tuple[str, str]] = []
            if want_docx:
                _store(
                    db, storage, job, item, "docx", f"{item.filename}.docx", rendered[item.id], retention_days
                )
            if want_pdf:
                res = pdfs.get(str(item.id))
                if isinstance(res, bytes):
                    _store(db, storage, job, item, "pdf", f"{item.filename}.pdf", res, retention_days)
                else:
                    errors.append(_pdf_error(res))
            if errors:
                item.status, (item.error_code, item.error_message) = "failed", errors[0]
            else:
                item.status, item.error_code, item.error_message = "succeeded", None, None
            item.finished_at = utcnow()
        db.flush()
        _refresh_counters(db, job)
        db.commit()  # progresso visível a quem acompanha

    db.refresh(job)
    _check_ownership(job, attempt)
    if job.status == "cancelled":
        return
    _refresh_counters(db, job)
    if job.kind == "batch":
        _build_artifacts(db, storage, job, retention_days)
    _finalize(db, job)
    db.commit()


def _pdf_error(res: Any) -> tuple[str, str]:
    if isinstance(res, PdfConverterUnavailable):
        return "PDF_CONVERTER_UNAVAILABLE", "Conversão para PDF indisponível neste ambiente."
    if isinstance(res, PdfConversionTimeout):
        return "PDF_TIMEOUT", "A conversão para PDF demorou demais e foi cancelada."
    if isinstance(res, PdfConversionError):
        return "PDF_CONVERSION_FAILED", "Falha ao converter este documento para PDF."
    if isinstance(res, PermanentError):
        return res.code, str(res)
    return "PDF_CONVERSION_FAILED", "Falha ao converter este documento para PDF."


def _refresh_counters(db: Session, job: GenerationJob) -> None:
    counts = dict(
        db.execute(
            select(GenerationItem.status, func.count())
            .where(GenerationItem.job_id == job.id)
            .group_by(GenerationItem.status)
        ).all()
    )
    job.succeeded_items = counts.get("succeeded", 0)
    job.failed_items = counts.get("failed", 0)
    total_bytes = db.scalar(
        select(func.coalesce(func.sum(GeneratedFile.size_bytes), 0)).where(
            GeneratedFile.job_id == job.id, GeneratedFile.kind.in_(("docx", "pdf"))
        )
    )
    job.bytes_total = int(total_bytes or 0)


def _finalize(db: Session, job: GenerationJob) -> None:
    skipped = (
        db.scalar(
            select(func.count(GenerationItem.id)).where(
                GenerationItem.job_id == job.id, GenerationItem.status == "skipped"
            )
        )
        or 0
    )
    if job.total_items and job.succeeded_items == job.total_items and skipped == 0:
        job.status = "succeeded"
    elif job.succeeded_items == 0:
        job.status, job.error_code = "failed", job.error_code or "ALL_ITEMS_FAILED"
        job.error_message = job.error_message or "Nenhum documento foi gerado. Consulte os erros por linha."
    else:
        job.status = "partial"
    job.finished_at = utcnow()
    job.duration_ms = int((job.finished_at - (job.started_at or job.created_at)).total_seconds() * 1000)


def _csv_safe(v: str) -> str:
    """Evita injeção de fórmula ao abrir o CSV no Excel."""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _build_artifacts(db: Session, storage: StorageAdapter, job: GenerationJob, retention_days: int) -> None:
    for old in db.scalars(
        select(GeneratedFile).where(GeneratedFile.job_id == job.id, GeneratedFile.kind.in_(("zip", "report")))
    ):
        with contextlib.suppress(TransientError):
            storage.delete(old.storage_key)
        db.delete(old)
    db.flush()

    items = list(
        db.scalars(
            select(GenerationItem).where(GenerationItem.job_id == job.id).order_by(GenerationItem.row_index)
        )
    )
    files_by_item: dict[uuid.UUID, list[GeneratedFile]] = {}
    for f in db.scalars(
        select(GeneratedFile).where(GeneratedFile.job_id == job.id, GeneratedFile.kind.in_(("docx", "pdf")))
    ):
        files_by_item.setdefault(f.item_id, []).append(f)  # type: ignore[arg-type]

    out = io.StringIO(newline="")
    w = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["linha", "status", "arquivos", "codigo_erro", "mensagem"])
    label = {
        "succeeded": "gerado",
        "failed": "falhou",
        "skipped": "ignorada (dados inválidos)",
        "pending": "não processada",
        "processing": "não processada",
    }
    for it in items:
        names = "; ".join(sorted(f.filename for f in files_by_item.get(it.id, [])))
        w.writerow(
            [
                it.row_index,
                label.get(it.status, it.status),
                _csv_safe(names),
                it.error_code or "",
                _csv_safe(it.error_message or ""),
            ]
        )
    report_bytes = b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")  # BOM: o Excel abre acentos corretamente

    fd, tmp_name = tempfile.mkstemp(suffix=".zip", prefix="minuta_")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        both = job.output_format == "both"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                for f in files_by_item.get(it.id, []):
                    arc = f"{f.kind}/{f.filename}" if both else f.filename
                    zf.writestr(arc, _retry(lambda key=f.storage_key: storage.get(key)))
            zf.writestr("relatorio.csv", report_bytes)
        key = f"w/{job.workspace_id}/gen/{job.id}/{uuid.uuid4().hex}.zip"
        _retry(lambda: storage.put_file(key, tmp, CT["zip"]))
        size = tmp.stat().st_size
        import hashlib

        db.add(
            GeneratedFile(
                workspace_id=job.workspace_id,
                job_id=job.id,
                item_id=None,
                kind="zip",
                filename=f"lote_{str(job.id)[:8]}.zip",
                storage_key=key,
                content_type=CT["zip"],
                size_bytes=size,
                sha256=hashlib.sha256(tmp.read_bytes()).hexdigest(),
                expires_at=utcnow() + timedelta(days=retention_days),
            )
        )
    finally:
        tmp.unlink(missing_ok=True)
    _store(db, storage, job, None, "report", f"relatorio_{str(job.id)[:8]}.csv", report_bytes, retention_days)


def cleanup_expired(batch: int = 500) -> int:
    """Remove do storage os arquivos gerados expirados e marca o registro (agendar via `python -m app.cli cleanup`)."""
    return cleanup_expired_report(batch)["removidos"]


def cleanup_expired_report(batch: int = 500, max_batches: int = 1000) -> dict[str, int]:
    """Remove TODOS os arquivos gerados expirados, em lotes, até não sobrar nenhum ou só sobrarem falhas.
    Devolve contadores para monitoração: removidos, falhas e ainda pendentes (expirados e não removidos —
    diferente de zero só quando o storage falhou ou o limite de lotes foi atingido)."""
    storage = get_storage()
    removed = 0
    failed_ids: set[uuid.UUID] = set()
    for _ in range(max_batches):
        with get_factory()() as db:
            q = select(GeneratedFile).where(
                GeneratedFile.deleted_at.is_(None), GeneratedFile.expires_at <= utcnow()
            )
            if failed_ids:
                q = q.where(GeneratedFile.id.not_in(failed_ids))  # não insiste no mesmo arquivo nesta rodada
            rows = db.scalars(q.limit(batch)).all()
            if not rows:
                break
            for f in rows:
                try:
                    storage.delete(f.storage_key)
                    f.deleted_at = utcnow()
                    removed += 1
                except TransientError:
                    failed_ids.add(f.id)
                    log.warning("cleanup_falhou_para_arquivo", extra={"file_id": str(f.id)})
            db.commit()
    with get_factory()() as db:
        db.execute(
            delete(GeneratedFile).where(
                GeneratedFile.deleted_at.is_not(None),
                GeneratedFile.deleted_at <= utcnow() - timedelta(days=30),
            )
        )
        db.commit()
        pending = db.scalar(
            select(func.count())
            .select_from(GeneratedFile)
            .where(GeneratedFile.deleted_at.is_(None), GeneratedFile.expires_at <= utcnow())
        )
    report = {"removidos": removed, "falhas": len(failed_ids), "pendentes": int(pending or 0)}
    log.info("cleanup_concluido", extra=report)
    return report
