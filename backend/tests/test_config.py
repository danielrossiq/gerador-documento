"""Configuração por variáveis de ambiente (o formato do docker-compose e do .env.example)."""

from __future__ import annotations

import pytest

from app.core.config import Settings, reset_settings_cache


def test_allowed_origins_accepts_comma_separated_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000 ,https://app.exemplo.com"
    )
    reset_settings_cache()
    assert Settings().allowed_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://app.exemplo.com",
    ]
    reset_settings_cache()


def test_production_refuses_insecure_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings().validate_for_production()
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("COOKIE_SECURE", "true")
    Settings().validate_for_production()  # não levanta
