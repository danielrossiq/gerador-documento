"""O módulo do worker precisa ser importável e registrar os atores (falhas de import só apareciam em produção)."""

from __future__ import annotations

import importlib


def test_worker_module_imports_and_registers_actors(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    tasks = importlib.import_module("app.worker.tasks")
    assert set(tasks.ACTORS) == {"generation", "analysis"}
    gen = tasks.ACTORS["generation"]
    assert gen.queue_name == "generation"
    assert gen.options["on_retry_exhausted"] == "generation_exhausted"
    # só falhas transitórias são repetidas
    from app.core.errors import PermanentError, TransientError

    assert tasks._retry_when(0, TransientError("x")) is True
    assert tasks._retry_when(0, PermanentError("x")) is False
    assert tasks._retry_when(tasks.MAX_RETRIES, TransientError("x")) is False
    reset_settings_cache()


def test_pdf_capability_is_published_by_worker_and_read_by_api(monkeypatch):
    """A API não tem LibreOffice: com fila externa, `pdf_available` depende da capacidade que o worker publica no Redis."""
    import app.adapters.pdf as pdf
    from app.core.config import reset_settings_cache

    store: dict[str, str] = {}

    class FakeRedis:
        def setex(self, k, ttl, v):
            store[k] = v

        def exists(self, k):
            return k in store

    monkeypatch.setenv("JOB_BACKEND", "dramatiq")
    monkeypatch.setenv("PDF_CONVERTER", "libreoffice")
    monkeypatch.setenv("REDIS_URL", "redis://x")
    reset_settings_cache()
    monkeypatch.setattr(pdf, "_redis_client", lambda: FakeRedis())
    assert pdf.pdf_available() is False  # nenhum worker publicou ainda

    class LO:
        def available(self):
            return True

    monkeypatch.setattr(pdf, "get_pdf_converter", lambda: LO())
    assert pdf.publish_capability() is True
    assert pdf.pdf_available() is True  # a API enxerga o worker
    monkeypatch.setenv("PDF_CONVERTER", "none")
    reset_settings_cache()
    assert pdf.pdf_available() is False
    reset_settings_cache()
