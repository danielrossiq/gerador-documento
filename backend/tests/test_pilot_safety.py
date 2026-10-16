"""Travas do piloto: PDF desligado e nenhuma IA externa por padrão, mesmo com chaves configuradas."""

from __future__ import annotations

import pytest

from app.adapters.ai import LocalHeuristicProvider, get_ai_provider, get_role_classifier
from app.core.config import Settings, reset_settings_cache
from tests.flows import upload
from tests.pdf_samples import typed_pdf


@pytest.fixture
def pilot(monkeypatch: pytest.MonkeyPatch):
    """Ambiente do piloto: flags no padrão do produto (sem PDF_IMPORT_ENABLED/EXTERNAL_AI_ENABLED)."""
    monkeypatch.delenv("PDF_IMPORT_ENABLED", raising=False)
    monkeypatch.delenv("EXTERNAL_AI_ENABLED", raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_product_defaults_are_safe():
    fields = Settings.model_fields
    assert fields["pdf_import_enabled"].default is False
    assert fields["external_ai_enabled"].default is False


def test_pdf_upload_is_refused_and_audited_when_disabled(api, pilot):
    api.register()
    gid = api.post("/generators", json={"name": "Contrato"}).json()["id"]
    r = upload(api, gid, typed_pdf(), "contrato.pdf")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PDF_IMPORT_DISABLED"
    assert api.get(f"/generators/{gid}").json()["has_template"] is False
    me = api.get("/auth/me").json()
    assert me["features"] == {"pdf_import": False, "external_ai": False}


def test_docx_upload_still_works_when_pdf_is_disabled(api, pilot, demo_docx):
    api.register()
    gid = api.post("/generators", json={"name": "Contrato"}).json()["id"]
    assert upload(api, gid, demo_docx).status_code in (200, 201)


def test_external_ai_is_blocked_even_with_keys(monkeypatch: pytest.MonkeyPatch, pilot):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("AI_API_KEY", "sk-teste-nao-usada")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-teste-nao-usada")
    reset_settings_cache()
    assert isinstance(get_ai_provider(), LocalHeuristicProvider)
    assert get_role_classifier() is None


def test_external_ai_needs_the_explicit_switch(monkeypatch: pytest.MonkeyPatch, pilot):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("AI_API_KEY", "sk-teste-nao-usada")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-teste-nao-usada")
    monkeypatch.setenv("EXTERNAL_AI_ENABLED", "true")
    reset_settings_cache()
    assert not isinstance(get_ai_provider(), LocalHeuristicProvider)  # só construído; nenhuma chamada feita
    assert get_role_classifier() is not None


def test_ai_provider_none_still_means_rules_only(monkeypatch: pytest.MonkeyPatch, pilot):
    monkeypatch.setenv("AI_PROVIDER", "none")
    reset_settings_cache()
    assert get_ai_provider() is None
