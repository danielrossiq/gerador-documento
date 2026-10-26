"""Atores Dramatiq. Iniciar com: `dramatiq app.worker.tasks --processes 2 --threads 4`.

Retry só para falhas transitórias (`TransientError`); erros permanentes de item são tratados dentro do
runner (o item vira `failed`, o lote segue). Após esgotar as tentativas a mensagem vai para a dead-letter
queue do broker e o job é marcado como `failed` (ver `on_retry_exhausted`). Se o próprio worker morrer, o
watchdog (heartbeat no banco) reenfileira o job e o runner idempotente retoma de onde parou.
"""

from __future__ import annotations

import os

from app.core.config import get_settings
from app.core.errors import PermanentError, TransientError
from app.core.logging import configure_logging, get_logger

settings = get_settings()
# O middleware Prometheus do Dramatiq (ativo por padrão) lê a porta do exportador desta variável ao ser importado.
os.environ.setdefault("dramatiq_prom_port", str(settings.worker_metrics_port))

import dramatiq  # noqa: E402
from dramatiq.brokers.redis import RedisBroker  # noqa: E402

configure_logging(settings.log_level, settings.log_json)
log = get_logger(__name__)

broker = RedisBroker(url=settings.redis_url or "redis://localhost:6379/0")
dramatiq.set_broker(broker)

MAX_RETRIES = settings.job_max_retries


def _start_capability_heartbeat(interval: float = 30.0) -> None:
    """Publica no Redis, a cada 30 s, que este worker sabe converter PDF (a API consulta antes de aceitar `format=pdf`)."""
    import threading
    import time

    from app.adapters.pdf import publish_capability

    def loop() -> None:
        while True:
            try:
                publish_capability()
            except Exception:
                log.warning("heartbeat_pdf_falhou")
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="pdf-capability").start()


_start_capability_heartbeat()


def _start_job_watchdog() -> None:
    """Reenfileira jobs abandonados por um worker que morreu (SIGKILL/OOM/host). Não depende do redelivery do
    Dramatiq, que só roda "manutenção" com probabilidade de 1 em 1000 por consulta ociosa (recuperação lenta e
    imprevisível). Vários processos podem rodar isto: o UPDATE condicional garante um único vencedor por job."""
    from app.modules.generation.runner import start_watchdog

    start_watchdog()


_start_job_watchdog()


def _retry_when(retries: int, exc: BaseException) -> bool:
    return isinstance(exc, TransientError) and retries < MAX_RETRIES


@dramatiq.actor(
    queue_name="generation",
    retry_when=_retry_when,
    min_backoff=5_000,
    max_backoff=120_000,
    time_limit=settings.job_time_limit_ms,
    throws=(PermanentError,),
    on_retry_exhausted="generation_exhausted",
)
def generation_task(job_id: str) -> None:
    from app.modules.generation.runner import run_generation_job

    run_generation_job(job_id)


@dramatiq.actor(queue_name="generation")
def generation_exhausted(message_data: dict, retry_info: dict) -> None:
    """Sem mais tentativas: estado terminal explícito (não fica 'processando' para sempre)."""
    from app.modules.generation.runner import mark_job_failed

    mark_job_failed(
        message_data.get("kwargs", {}).get("job_id", ""),
        "RETRIES_EXHAUSTED",
        "O processamento falhou repetidamente por instabilidade temporária. Tente novamente mais tarde.",
    )


@dramatiq.actor(queue_name="analysis", max_retries=2, min_backoff=3_000, time_limit=5 * 60 * 1000)
def analysis_task(version_id: str, force: bool = False) -> None:
    from app.modules.suggestions.service import run_analysis_job

    run_analysis_job(version_id, force)


# Teste grátis da landing (D38): sem retry (o status já impede trabalho em dobro e uma nova tentativa gastaria IA
# de novo); fila própria para não disputar ordem com as análises das contas.
@dramatiq.actor(queue_name="trial", max_retries=0, time_limit=3 * 60 * 1000)
def trial_task(trial_id: str) -> None:
    from app.modules.trials.service import run_trial_job

    run_trial_job(trial_id)


ACTORS = {"generation": generation_task, "analysis": analysis_task, "trial": trial_task}
