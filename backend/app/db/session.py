"""Engine e sessões. Sessões são criadas por requisição/job; nada é compartilhado entre threads."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

_engine: sa.Engine | None = None
_factory: sessionmaker[Session] | None = None


def _make_engine(url: str) -> sa.Engine:
    settings = get_settings()
    if url.startswith("sqlite"):
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            return sa.create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
        path = url.split("///", 1)[-1]
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = sa.create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @sa.event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return sa.create_engine(url, pool_size=settings.db_pool_size, max_overflow=10, pool_pre_ping=True)


def get_engine() -> sa.Engine:
    global _engine, _factory
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
        _factory = sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_factory() -> sessionmaker[Session]:
    get_engine()
    assert _factory is not None
    return _factory


def reset_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def get_db() -> Generator[Session, None, None]:
    """Dependência FastAPI. Os serviços fazem commit explícito ao concluir cada operação."""
    with get_factory()() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Uso em workers/CLI: commit ao final, rollback em erro."""
    with get_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def ensure_data_dirs() -> None:
    if get_settings().database_url.startswith("sqlite") and os.name:
        Path("data").mkdir(exist_ok=True)
