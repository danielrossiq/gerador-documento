"""Métricas de ativação agregadas (D32): opt-in, só contagens por dia/coorte, supressão < 5, sem identificadores,
sem FK, retenção de 30 dias no rollup e no cleanup."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import select, update

from app import cli
from app.core.config import reset_settings_cache
from app.db.models import ActivationMetric, GenerationJob, Workspace
from app.db.session import get_engine, get_factory
from app.modules.metrics.activation import rollup
from tests.flows import SAMPLE_VALUES, build_generator

TOMORROW = datetime.now(UTC).date() + timedelta(days=1)  # o rollup só conta dias completos (< hoje)
UUID_RE = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.I)


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ACTIVATION_METRICS_ENABLED", "true")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _activated_workspaces(api, demo_docx, n: int) -> None:  # type: ignore[no-untyped-def]
    for _ in range(n):
        api.register()
        gid = build_generator(api, demo_docx)["id"]
        job = api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES, "format": "docx"}).json()
        assert job["status"] == "succeeded"


def _rows() -> dict[tuple[str, date, str], ActivationMetric]:
    with get_factory()() as db:
        return {(r.period_kind, r.period_start, r.metric): r for r in db.scalars(select(ActivationMetric))}


def test_off_by_default_writes_nothing(api, demo_docx):
    _activated_workspaces(api, demo_docx, 1)
    r = rollup(TOMORROW)
    assert r.enabled is False and r.rows_written == 0
    assert _rows() == {}


def test_table_has_no_identifiers_no_fk_and_no_timestamps(api):
    cols = {c.name: c for c in ActivationMetric.__table__.columns}
    assert set(cols) == {"period_kind", "period_start", "metric", "value", "suppressed", "computed_on"}
    assert not ActivationMetric.__table__.foreign_keys
    assert all(
        not isinstance(c.type, (sa.Uuid, sa.DateTime)) for c in cols.values()
    )  # só Date, nunca horário
    insp = sa.inspect(get_engine())
    assert insp.get_foreign_keys("activation_metrics") == []


def test_counts_at_or_above_five_are_kept_smaller_ones_suppressed(api, demo_docx, enabled):
    _activated_workspaces(api, demo_docx, 5)
    today = TOMORROW - timedelta(days=1)
    r = rollup(TOMORROW)
    assert r.enabled and r.rows_written > 0
    rows = _rows()
    for metric in (
        "workspaces_novos",
        "modelos_enviados",
        "primeiro_documento",
        "primeiro_documento_ate_5min",
    ):
        row = rows[("day", today, metric)]
        assert row.value == 5 and not row.suppressed, metric
    lots = rows[("day", today, "lotes_concluidos")]  # nenhum lote: zero também é suprimido
    assert lots.value is None and lots.suppressed
    quiet_day = rows[("day", today - timedelta(days=3), "workspaces_novos")]
    assert quiet_day.value is None and quiet_day.suppressed  # "0" indistinguível de "1–4"


def test_four_activations_are_fully_suppressed(api, demo_docx, enabled):
    _activated_workspaces(api, demo_docx, 4)
    rollup(TOMORROW)
    today = TOMORROW - timedelta(days=1)
    rows = _rows()
    assert all(r.value is None for (k, d, m), r in rows.items() if d == today)


def test_d7_return_by_weekly_cohort(api, demo_docx, enabled):
    _activated_workspaces(api, demo_docx, 5)
    born = datetime.now(UTC) - timedelta(days=16)
    with get_factory()() as db:
        db.execute(update(Workspace).values(created_at=born))
        db.execute(update(GenerationJob).values(created_at=born + timedelta(days=8)))
        db.commit()
    rollup(TOMORROW)
    week = born.date() - timedelta(days=born.date().weekday())
    rows = _rows()
    assert rows[("cohort_week", week, "coorte_tamanho")].value == 5
    assert rows[("cohort_week", week, "coorte_retorno_d7")].value == 5


def test_stored_rows_and_report_carry_no_ids_emails_or_names(api, demo_docx, enabled, capsys):
    _activated_workspaces(api, demo_docx, 5)
    rollup(TOMORROW)
    with get_factory()() as db:
        dump = repr(db.execute(select(ActivationMetric.__table__)).all())
    assert not UUID_RE.search(dump) and "@" not in dump and "Ana Teste" not in dump
    assert cli.main(["metrics-report"]) == 0
    out = capsys.readouterr().out
    assert "primeiro_documento | " in out and "<5" in out
    assert not UUID_RE.search(out) and "@" not in out


def test_retention_30_days_in_rollup_and_cleanup(api):
    old = datetime.now(UTC).date() - timedelta(days=40)
    with get_factory()() as db:
        db.add(ActivationMetric(period_kind="day", period_start=old, metric="workspaces_novos", value=9,
                                suppressed=False, computed_on=old))  # fmt: skip
        db.commit()
    r = rollup()  # desligado: não grava nada, mas aplica a retenção
    assert r.enabled is False and r.rows_expired == 1 and _rows() == {}
    with get_factory()() as db:
        db.add(ActivationMetric(period_kind="day", period_start=old, metric="workspaces_novos", value=9,
                                suppressed=False, computed_on=old))  # fmt: skip
        db.commit()
    assert cli.main(["cleanup"]) == 0
    assert _rows() == {}


def test_value_below_five_is_rejected_by_the_database(api):
    with get_factory()() as db:
        db.add(ActivationMetric(period_kind="day", period_start=date(2026, 10, 1), metric="workspaces_novos",
                                value=3, suppressed=False, computed_on=date(2026, 10, 1)))  # fmt: skip
        with pytest.raises(sa.exc.IntegrityError):
            db.commit()
