from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

# Configuração de teste antes de qualquer import da aplicação.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JOB_BACKEND", "sync")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("AI_PROVIDER", "local")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("PDF_CONVERTER", "none")
os.environ.setdefault(
    "PDF_IMPORT_ENABLED", "true"
)  # a suíte testa o importador; o padrão do produto é desligado

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.samples.documents import build_demo_contract  # noqa: E402


@pytest.fixture(scope="session")
def demo_docx() -> bytes:
    return build_demo_contract()


def _reset_everything() -> None:
    from app.adapters.pdf import reset_pdf_converter
    from app.adapters.storage import reset_storage
    from app.core import ratelimit
    from app.core.config import reset_settings_cache
    from app.db.session import reset_engine

    reset_settings_cache()
    reset_engine()
    reset_storage()
    reset_pdf_converter()
    ratelimit.reset_for_tests()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Banco SQLite e storage locais, isolados por teste. Com TEST_DATABASE_URL usa PostgreSQL."""
    db_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("JOB_BACKEND", "sync")
    monkeypatch.setenv("PDF_CONVERTER", "none")
    _reset_everything()
    if db_url.startswith("postgresql"):
        from app.db.models import Base
        from app.db.session import get_engine

        Base.metadata.drop_all(get_engine())
        Base.metadata.create_all(get_engine())
    yield tmp_path
    _reset_everything()


@pytest.fixture()
def app(env: Path):  # type: ignore[no-untyped-def]
    from app.main import create_app

    return create_app()


class Api:
    """Cliente de teste que envia o CSRF automaticamente, como o navegador faz."""

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        from fastapi.testclient import TestClient

        self.tc = TestClient(app)
        self.tc.__enter__()

    def close(self) -> None:
        self.tc.__exit__(None, None, None)

    def _kw(self, kw: dict) -> dict:
        headers = dict(kw.pop("headers", {}) or {})
        if csrf := self.tc.cookies.get("minuta_csrf"):
            headers.setdefault("X-CSRF-Token", csrf)
        return {**kw, "headers": headers}

    def get(self, path: str, **kw):  # type: ignore[no-untyped-def]
        return self.tc.get(f"/api/v1{path}", **self._kw(kw))

    def post(self, path: str, **kw):  # type: ignore[no-untyped-def]
        return self.tc.post(f"/api/v1{path}", **self._kw(kw))

    def put(self, path: str, **kw):  # type: ignore[no-untyped-def]
        return self.tc.put(f"/api/v1{path}", **self._kw(kw))

    def patch(self, path: str, **kw):  # type: ignore[no-untyped-def]
        return self.tc.patch(f"/api/v1{path}", **self._kw(kw))

    def delete(self, path: str, **kw):  # type: ignore[no-untyped-def]
        return self.tc.delete(f"/api/v1{path}", **self._kw(kw))

    def register(
        self, email: str | None = None, name: str = "Ana Teste", password: str = "senha-forte-123"
    ) -> dict:
        email = email or f"user-{uuid.uuid4().hex[:8]}@exemplo.test"
        r = self.post("/auth/register", json={"name": name, "email": email, "password": password})
        assert r.status_code == 201, r.text
        return {**r.json(), "email": email, "password": password}


@pytest.fixture()
def api(app) -> Iterator[Api]:  # type: ignore[no-untyped-def]
    a = Api(app)
    yield a
    a.close()


@pytest.fixture()
def api2(app) -> Iterator[Api]:  # type: ignore[no-untyped-def]
    """Segundo cliente (cookies separados) — outro usuário/workspace."""
    a = Api(app)
    yield a
    a.close()


class FakePdfConverter:
    """Dublê de teste do adaptador de PDF (produz PDF mínimo válido). O fluxo real usa LibreOffice."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.calls = 0

    def available(self) -> bool:
        return True

    def convert(self, docx: bytes) -> bytes:
        return self._pdf(docx)

    def _pdf(self, docx: bytes) -> bytes:
        return b"%PDF-1.4\n" + b"%" + docx[:200].hex().encode() + b"\n" + b"0" * 300 + b"\n%%EOF"

    def convert_many(self, items):  # type: ignore[no-untyped-def]
        from app.adapters.pdf import PdfConversionError

        self.calls += 1
        out = {}
        for key, data in items:
            out[key] = (
                PdfConversionError() if any(f in self._text(data) for f in self.fail_for) else self._pdf(data)
            )
        return out

    @staticmethod
    def _text(docx: bytes) -> str:
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(docx)) as z:
            return z.read("word/document.xml").decode("utf-8")


@pytest.fixture()
def fake_pdf(monkeypatch: pytest.MonkeyPatch) -> FakePdfConverter:
    fake = FakePdfConverter()
    monkeypatch.setattr(
        "app.adapters.pdf.get_pdf_converter", lambda: fake
    )  # também usado por pdf_available()
    monkeypatch.setattr("app.modules.generation.runner.get_pdf_converter", lambda: fake)
    monkeypatch.setenv("PDF_CONVERTER", "libreoffice")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    return fake
