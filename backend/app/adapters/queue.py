"""Fila de jobs. Três backends com a MESMA função de execução (idempotente):

* dramatiq (compose/produção): Redis + workers separados (horizontalmente escaláveis);
* thread   (dev sem Docker): pool de threads no próprio processo da API;
* sync     (testes): executa na hora, para asserções determinísticas.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
_executor: ThreadPoolExecutor | None = None


def resolve_task(name: str) -> Callable[..., Any]:
    """Importação tardia: evita ciclos e mantém a API leve quando usa Dramatiq."""
    if name == "generation":
        from app.modules.generation.runner import run_generation_job

        return lambda job_id: run_generation_job(job_id)
    if name == "analysis":
        from app.modules.suggestions.service import run_analysis_job

        return lambda version_id, force=False: run_analysis_job(version_id, force)
    raise ValueError(f"Tarefa desconhecida: {name}")


def _run_safely(name: str, kwargs: dict[str, Any]) -> None:
    try:
        resolve_task(name)(**kwargs)
    except Exception:
        log.exception("tarefa_em_thread_falhou", extra={"task": name})


def enqueue(name: str, **kwargs: Any) -> None:
    backend = get_settings().job_backend
    if backend == "dramatiq":
        from app.worker.tasks import ACTORS

        ACTORS[name].send(**kwargs)
    elif backend == "thread":
        global _executor
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="minuta-job")
        _executor.submit(_run_safely, name, kwargs)
    else:
        resolve_task(name)(**kwargs)


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=False)
        _executor = None
