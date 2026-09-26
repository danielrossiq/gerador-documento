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
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactFilter())
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "botocore", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
