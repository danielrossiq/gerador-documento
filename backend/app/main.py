"""Aplicação FastAPI: middleware de correlação, cabeçalhos de segurança, health e métricas."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.adapters import queue
from app.adapters.pdf import pdf_available
from app.api import api
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger, set_request_id
from app.core.metrics import render_metrics
from app.db.session import ensure_data_dirs, get_engine

log = get_logger("app.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
        token = set_request_id(rid)
        started = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            set_request_id(None)
            del token
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/v1/downloads"):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.url.path not in ("/health", "/ready", "/metrics"):
            log.info(
                "http",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "request_id": rid,
                },
            )
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    settings.validate_for_production()
    configure_logging(settings.log_level, settings.log_json)
    ensure_data_dirs()
    if settings.app_env != "production" and settings.database_url.startswith("sqlite"):
        # desenvolvimento/testes em SQLite: cria as tabelas. Em PostgreSQL o esquema vem das migrations Alembic.
        from app.db.models import Base

        Base.metadata.create_all(get_engine())
    stop_watchdog = None
    if settings.job_backend == "thread":
        # Sem worker separado, os jobs rodam em threads deste processo: após reiniciar a API, retoma os abandonados.
        from app.modules.generation.runner import start_watchdog
        from app.modules.trials.service import fail_orphaned_trials

        fail_orphaned_trials(startup_thread_mode=True)  # testes grátis que morreram com o processo anterior (QA-6)
        stop_watchdog = start_watchdog()
    yield
    if stop_watchdog is not None:
        stop_watchdog.set()
    queue.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(api)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "erro"
        checks["pdf_converter"] = "ok" if pdf_available() else "indisponivel"
        code = 200 if checks["database"] == "ok" else 503
        return JSONResponse(checks, status_code=code)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")

    return app


app = create_app()
