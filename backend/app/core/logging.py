"""Logs estruturados com correlation ID / job ID e redação de dados pessoais.

Nunca registramos conteúdo de contratos nem valores de campos. Além de não passar esses dados aos
logs, o filtro `RedactFilter` mascara padrões de CPF, CNPJ, e-mail e telefone como rede de segurança.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import sys
import time
import traceback
from typing import Any

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)

_PATTERNS = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[cpf]"),
    (re.compile(r"\b[0-9A-Z]{2}\.?[0-9A-Z]{3}\.?[0-9A-Z]{3}/?[0-9A-Z]{4}-?\d{2}\b"), "[cnpj]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[tel]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def set_request_id(value: str | None) -> contextvars.Token[str | None]:
    return _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def set_job_id(value: str | None) -> contextvars.Token[str | None]:
    return _job_id.set(value)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        with contextlib.suppress(Exception):  # logging nunca pode quebrar a aplicação
            record.msg = redact(record.getMessage())
            record.args = None
        return True


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}

# Campos estruturados aceitos no log (extra=…). Tudo fora desta lista é descartado e só o NOME da chave é
# registrado em "omitted_keys" — um extra novo com conteúdo de documento não vaza por engano. Valores: só
# tipos simples; textos passam pela máscara e são cortados em 200 caracteres.
SAFE_EXTRA_KEYS = frozenset(
    {
        # requisição
        "method", "path", "status", "duration_ms", "request_id",
        # identificadores (UUID) e contadores
        "workspace_id", "generator_id", "version_id", "job_id", "kit_id", "kit_run_id", "file_id",
        "row", "attempt", "n", "n_valid", "n_dropped", "n_candidates", "n_answered", "chars", "bytes",
        "removidos", "falhas", "pendentes",
        # erros: só tipo/código, nunca mensagem
        "error_type", "error", "code", "task", "template", "provider",
    }
)  # fmt: skip
_DOWNLOAD_TOKEN = re.compile(r"(/downloads/)[^/?#]+")


def _safe_extra(key: str, value: Any) -> Any:
    if isinstance(value, (bool, int, float, type(None))):
        return value
    text = redact(str(value))[:200]
    return _DOWNLOAD_TOKEN.sub(r"\1[token]", text) if key == "path" else text


def safe_exception_text(exc_info: Any) -> str:
    """Traceback SEM a mensagem das exceções: só arquivo/linha/função e o tipo. Mensagens de exceção de
    bibliotecas (lxml, python-docx, pdfplumber, SQLAlchemy…) podem citar trechos do documento ou valores
    preenchidos; o tipo e o ponto do código bastam para diagnosticar."""
    _, exc, _ = exc_info
    parts: list[str] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        frames = "".join(traceback.format_tb(exc.__traceback__)) if exc.__traceback__ else ""
        parts.append(f"{frames}{type(exc).__module__}.{type(exc).__qualname__}")
        exc = exc.__cause__ or exc.__context__
    return redact("\n--- causa/contexto ---\n".join(parts))


class SafeTextFormatter(logging.Formatter):
    """Formato de texto (desenvolvimento) com a mesma regra de exceções do JSON."""

    def formatException(self, ei: Any) -> str:
        return safe_exception_text(ei)

    def format(self, record: logging.LogRecord) -> str:
        # outro handler pode ter guardado em exc_text o traceback COM a mensagem; nunca reaproveita esse texto
        cached, record.exc_text = record.exc_text, None
        try:
            return super().format(record)
        finally:
            record.exc_text = cached


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if (rid := _request_id.get()) is not None:
            payload["request_id"] = rid
        if (jid := _job_id.get()) is not None:
            payload["job_id"] = jid
        omitted = []
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in SAFE_EXTRA_KEYS:
                payload[key] = _safe_extra(key, value)
            else:
                omitted.append(key)
        if omitted:
            payload["omitted_keys"] = sorted(omitted)
        if record.exc_info:
            payload["exc"] = safe_exception_text(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactFilter())
    handler.setFormatter(
        JsonFormatter() if json_logs else SafeTextFormatter("%(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "botocore", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
