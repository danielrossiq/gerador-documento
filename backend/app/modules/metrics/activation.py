"""Métricas de ativação do piloto — só agregados diários/por coorte (item 9a do backlog, D32).

**Opt-in:** nada é calculado nem gravado sem `ACTIVATION_METRICS_ENABLED=true`.

**Sem coleta de eventos:** os números são DERIVADOS, uma vez por dia (`python -m app.cli metrics-rollup`),
das tabelas operacionais que já existem (workspaces, template_files, generation_jobs). Não há tabela de eventos,
identificador pseudônimo, horário exato, IP, conteúdo ou atributo livre. Os identificadores ficam só em memória
durante o cálculo e nunca são gravados. A tabela `activation_metrics` guarda apenas:
período (dia ou semana de coorte) × métrica (lista fechada) × contagem.

**Supressão:** contagem menor que 5 não é gravada (`value` NULL, `suppressed`), inclusive o zero.
**Sem detalhamento:** nada é por workspace ou por usuário, e não existe rota de API.
**Retenção:** no máximo 30 dias — linhas mais antigas saem em todo rollup e em todo `cleanup` (monitorado).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import ActivationMetric, GenerationJob, TemplateFile, Workspace
from app.db.session import get_factory

log = get_logger(__name__)

MIN_GROUP = 5
RETENTION_DAYS = 30
ACTIVATION_WINDOW = timedelta(minutes=5)
DONE = ("succeeded", "partial")


@dataclass
class RollupResult:
    enabled: bool
    rows_written: int = 0
    rows_suppressed: int = 0
    rows_expired: int = 0


def _today() -> date:
    return datetime.now(UTC).date()


def _day(ts: datetime) -> date:
    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(UTC).date()


def _week(d: date) -> date:
    return d - timedelta(days=d.weekday())  # segunda-feira da semana ISO


def purge_expired(db, today: date | None = None) -> int:  # type: ignore[no-untyped-def]
    """Apaga agregados com mais de 30 dias. Roda sempre, mesmo com as métricas desligadas."""
    cutoff = (today or _today()) - timedelta(days=RETENTION_DAYS)
    res = db.execute(delete(ActivationMetric).where(ActivationMetric.period_start < cutoff))
    return int(res.rowcount or 0)


def compute(db, today: date | None = None) -> dict[tuple[str, date, str], int]:  # type: ignore[no-untyped-def]
    """Contagens brutas (antes da supressão) dos últimos 30 dias completos. Identificadores só em memória."""
    today = today or _today()
    start = today - timedelta(days=RETENTION_DAYS)
    since = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    out: Counter[tuple[str, date, str]] = Counter()

    created = dict(db.execute(select(Workspace.id, Workspace.created_at)).all())
    for ts in created.values():
        if start <= _day(ts) < today:
            out[("day", _day(ts), "workspaces_novos")] += 1

    for (ts,) in db.execute(
        select(TemplateFile.created_at).where(TemplateFile.role == "source", TemplateFile.created_at >= since)
    ):
        if _day(ts) < today:
            out[("day", _day(ts), "modelos_enviados")] += 1

    first_done = dict(
        db.execute(
            select(GenerationJob.workspace_id, func.min(GenerationJob.finished_at))
            .where(GenerationJob.status.in_(DONE), GenerationJob.finished_at.is_not(None))
            .group_by(GenerationJob.workspace_id)
        ).all()
    )
    for wid, ts in first_done.items():
        d = _day(ts)
        if start <= d < today:
            out[("day", d, "primeiro_documento")] += 1
            born = created.get(wid)
            if born is not None and _as_utc(ts) - _as_utc(born) <= ACTIVATION_WINDOW:
                out[("day", d, "primeiro_documento_ate_5min")] += 1

    for (ts,) in db.execute(
        select(GenerationJob.finished_at).where(
            GenerationJob.kind == "batch", GenerationJob.status.in_(DONE), GenerationJob.finished_at >= since
        )
    ):
        if _day(ts) < today:
            out[("day", _day(ts), "lotes_concluidos")] += 1

    # coortes: semana de criação do workspace; retorno D7 = alguma geração entre o 7º e o 14º dia depois da
    # criação. Só entram coortes cuja janela de 14 dias já terminou (número final, não parcial).
    jobs_by_ws: dict[object, list[datetime]] = {}
    for wid, ts in db.execute(
        select(GenerationJob.workspace_id, GenerationJob.created_at).where(GenerationJob.created_at >= since)
    ):
        jobs_by_ws.setdefault(wid, []).append(_as_utc(ts))
    for wid, born in created.items():
        b = _as_utc(born)
        week = _week(b.date())
        if week < start or b.date() + timedelta(days=14) > today:
            continue
        out[("cohort_week", week, "coorte_tamanho")] += 1
        if any(b + timedelta(days=7) <= t < b + timedelta(days=14) for t in jobs_by_ws.get(wid, [])):
            out[("cohort_week", week, "coorte_retorno_d7")] += 1
    return dict(out)


def _as_utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def rollup(today: date | None = None) -> RollupResult:
    """Recalcula e grava (idempotente) os agregados dos últimos 30 dias e aplica a retenção."""
    today = today or _today()
    with get_factory()() as db:
        expired = purge_expired(db, today)
        if not get_settings().activation_metrics_enabled:
            db.commit()
            return RollupResult(enabled=False, rows_expired=expired)
        counts = compute(db, today)
        start = today - timedelta(days=RETENTION_DAYS)
        db.execute(delete(ActivationMetric).where(ActivationMetric.period_start >= start))
        res = RollupResult(enabled=True, rows_expired=expired)
        keys = set(counts)
        # dias sem nenhum evento também viram linha suprimida: "0" e "1–4" ficam indistinguíveis
        for i in range(RETENTION_DAYS):
            d = start + timedelta(days=i)
            for metric in ("workspaces_novos", "modelos_enviados", "primeiro_documento",
                           "primeiro_documento_ate_5min", "lotes_concluidos"):  # fmt: skip
                keys.add(("day", d, metric))
        for kind, period, metric in sorted(keys):
            n = counts.get((kind, period, metric), 0)
            ok = n >= MIN_GROUP
            db.add(
                ActivationMetric(
                    period_kind=kind, period_start=period, metric=metric,
                    value=n if ok else None, suppressed=not ok, computed_on=today,
                )
            )  # fmt: skip
            res.rows_written += 1
            res.rows_suppressed += 0 if ok else 1
        db.commit()
    log.info("metricas_rollup", extra={"n": res.rows_written, "n_dropped": res.rows_suppressed})
    return res


def report() -> list[ActivationMetric]:
    with get_factory()() as db:
        return list(
            db.scalars(
                select(ActivationMetric).order_by(
                    ActivationMetric.period_kind, ActivationMetric.period_start, ActivationMetric.metric
                )
            )
        )
