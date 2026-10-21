"""Conjunto ouro da IA integrada e baseline das regras locais (sem rede)."""

from __future__ import annotations

import socket

import pytest

from app.cli import main as cli
from app.eval import baseline
from app.eval.gold import CATEGORIES, GOLD, cnpj, cpf, validate
from app.modules.fields.validators import is_valid_cnpj, is_valid_cpf


def test_gold_set_is_consistent_and_covers_the_plan_categories():
    assert validate() == []
    assert len(GOLD) == 15
    assert {d.category for d in GOLD} == set(CATEGORIES)
    assert all(d.occurrences for d in GOLD)


def test_generated_documents_are_fictitious_with_valid_check_digits():
    assert is_valid_cpf(cpf("418226305")) and is_valid_cnpj(cnpj("318540920001"))
    text = " ".join(t for d in GOLD for _, t in d.render())
    assert "@exemplo.test" in text  # e-mails só em domínio reservado para testes
    assert "@gmail" not in text and "@hotmail" not in text


def test_parser_keys_match_the_annotations():
    from app.docx_engine.parse import parse_docx

    for d in GOLD:
        rendered = dict(d.render())
        parsed = {
            b.key: b.text for b in parse_docx(d.docx()).blocks if b.kind == "paragraph" and b.text.strip()
        }
        assert parsed == rendered, d.id


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("o baseline não pode acessar a rede")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_baseline_runs_offline_and_reports_every_metric(no_network, tmp_path):
    data = baseline.run()
    s = data["summary"]
    assert s["documents"] == 15
    for k in (
        "recall_occurrences_pct",
        "precision_pct",
        "recall_fields_pct",
        "type_accuracy_pct",
        "grouping_pct",
    ):
        assert 0 <= s[k] <= 100
    # as regras determinísticas já cobrem CPF, CNPJ e CEP: o baseline precisa reconhecer isso
    assert data["recall_by_type_pct"]["cpf"] >= 90
    assert data["recall_by_type_pct"]["cnpj"] >= 90
    assert (
        cli(["ai-eval", "baseline", "--json", str(tmp_path / "b.json"), "--md", str(tmp_path / "b.md")]) == 0
    )
    assert "Recall de ocorrências" in (tmp_path / "b.md").read_text(encoding="utf-8")
