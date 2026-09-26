"""Erros de domínio e envelope de erro padronizado da API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, get_request_id

log = get_logger(__name__)


class AppError(Exception):
    """Erro esperado, convertido em resposta HTTP com código estável."""

    status_code = 400
    code = "BAD_REQUEST"

    def __init__(
        self, message: str, *, code: str | None = None, status_code: int | None = None, details: Any = None
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"

    def __init__(self, what: str = "Recurso") -> None:
        super().__init__(f"{what} não encontrado.")


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"

    def __init__(self, message: str = "Autenticação necessária.") -> None:
        super().__init__(message)


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"

    def __init__(self, message: str = "Você não tem permissão para esta ação.") -> None:
        super().__init__(message)


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class LimitExceeded(AppError):
    status_code = 429
    code = "LIMIT_EXCEEDED"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


class TransientError(Exception):
    """Falha temporária: o job pode ser repetido (rede, timeout, storage indisponível)."""


class PermanentError(Exception):
    """Falha definitiva do item: repetir não adianta."""

    def __init__(self, message: str, code: str = "ITEM_FAILED") -> None:
        super().__init__(message)
        self.code = code


def _envelope(code: str, message: str, status: int, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": get_request_id()}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.code, exc.message, exc.status_code, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return _envelope("VALIDATION_ERROR", "Dados inválidos na requisição.", 422, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED", 403: "FORBIDDEN"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return _envelope(code, str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("erro_nao_tratado", extra={"error_type": type(exc).__name__})
        return _envelope("INTERNAL_ERROR", "Erro interno. Tente novamente em instantes.", 500)
