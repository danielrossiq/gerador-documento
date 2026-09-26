"""Métricas no formato Prometheus derivadas do banco (consistentes entre múltiplos processos/instâncias).

Worker e API compartilham o banco; por isso agregamos jobs/itens/arquivos no momento da coleta em vez de
manter contadores em memória por processo. O worker Dramatiq expõe, além disso, as métricas de fila
(mensagens, duração, falhas) na porta configurada em WORKER_METRICS_PORT.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import GeneratedFile, GenerationItem, GenerationJob
from app.db.session import get_factory


def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    lab = ""
    if labels:
        lab = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
    return f"{name}{lab} {value}"


def render_metrics() -> str:
    out: list[str] = []
    with get_factory()() as db:
        out.append("# HELP minuta_jobs_total Jobs de geração por tipo e status")
        out.append("# TYPE minuta_jobs_total gauge")
        for kind, status, n in db.execute(
            select(GenerationJob.kind, GenerationJob.status, func.count()).group_by(
                GenerationJob.kind, GenerationJob.status
            )
        ):
            out.append(_line("minuta_jobs_total", n, {"kind": kind, "status": status}))
        out.append("# HELP minuta_items_total Itens (linhas) por status")
        out.append("# TYPE minuta_items_total gauge")
        for status, n in db.execute(
            select(GenerationItem.status, func.count()).group_by(GenerationItem.status)
        ):
            out.append(_line("minuta_items_total", n, {"status": status}))
        out.append("# HELP minuta_items_failed_by_code Itens com falha por código de erro")
        out.append("# TYPE minuta_items_failed_by_code gauge")
        for code, n in db.execute(
            select(GenerationItem.error_code, func.count())
            .where(GenerationItem.status == "failed")
            .group_by(GenerationItem.error_code)
        ):
            out.append(_line("minuta_items_failed_by_code", n, {"code": code or "desconhecido"}))
        avg = (
            db.scalar(
                select(func.avg(GenerationJob.duration_ms)).where(GenerationJob.duration_ms.is_not(None))
            )
            or 0
        )
        out.append("# HELP minuta_job_duration_ms_avg Duração média dos jobs concluídos (ms)")
        out.append("# TYPE minuta_job_duration_ms_avg gauge")
        out.append(_line("minuta_job_duration_ms_avg", float(avg)))
        size = db.scalar(select(func.coalesce(func.sum(GenerationJob.total_items), 0))) or 0
        out.append("# HELP minuta_job_items_sum Soma de itens de todos os jobs (tamanho de trabalho)")
        out.append("# TYPE minuta_job_items_sum counter")
        out.append(_line("minuta_job_items_sum", float(size)))
        total_bytes = (
            db.scalar(
                select(func.coalesce(func.sum(GeneratedFile.size_bytes), 0)).where(
                    GeneratedFile.deleted_at.is_(None)
                )
            )
            or 0
        )
        out.append("# HELP minuta_stored_bytes Bytes de arquivos gerados retidos")
        out.append("# TYPE minuta_stored_bytes gauge")
        out.append(_line("minuta_stored_bytes", float(total_bytes)))
    return "\n".join(out) + "\n"
