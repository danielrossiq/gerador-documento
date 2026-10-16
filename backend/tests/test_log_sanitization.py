"""Logs nunca levam a MENSAGEM de exceções (pode citar trechos do documento ou valores preenchidos): só o tipo
e o ponto do código. Inclui o caminho de erro da conversão de PDF, que antes registrava repr(exceção)."""

from __future__ import annotations

import json
import logging
import sys

from app.core.logging import JsonFormatter, RedactFilter, SafeTextFormatter, safe_exception_text
from app.docx_engine import pdf_import

SECRET = "Contrato de Maria Souza, valor R$ 1.234,50, cláusula sigilosa"


def _raise():
    try:
        raise KeyError(SECRET)
    except KeyError as inner:
        raise ValueError(f"falhou ao ler: {SECRET}") from inner


def _log_with(formatter: logging.Formatter) -> str:
    """Formata um registro de log.exception() montado à mão (independe dos handlers que o pytest instala)."""
    try:
        _raise()
    except ValueError:
        record = logging.LogRecord(
            "teste.sanitizacao", logging.ERROR, __file__, 1, "algo_falhou", None, sys.exc_info()
        )
    RedactFilter().filter(record)
    return formatter.format(record)


def test_json_log_has_exception_type_and_frames_but_no_message():
    out = _log_with(JsonFormatter())
    payload = json.loads(out)
    assert "ValueError" in payload["exc"] and "KeyError" in payload["exc"]  # tipo e causa encadeada
    assert "test_log_sanitization.py" in payload["exc"]  # ponto do código continua para diagnóstico
    assert "Maria Souza" not in out and "1.234,50" not in out and "sigilosa" not in out


def test_text_log_has_no_message_either():
    out = _log_with(SafeTextFormatter("%(levelname)s %(name)s: %(message)s"))
    assert "ValueError" in out and "Maria Souza" not in out and "sigilosa" not in out


def test_safe_exception_text_handles_no_traceback():
    exc = RuntimeError(SECRET)
    text = safe_exception_text((RuntimeError, exc, None))
    assert text.endswith("RuntimeError") and "Maria" not in text


def test_pdf_child_error_sends_only_the_type(monkeypatch):
    sent: list[tuple] = []

    class Conn:
        def send(self, msg):
            sent.append(msg)

        def close(self):
            pass

    def boom(*_a, **_k):
        raise ValueError(SECRET)

    monkeypatch.setattr(pdf_import, "_limit_resources", lambda _t: None)
    monkeypatch.setattr(pdf_import, "pdf_to_docx", boom)
    pdf_import._child_main(Conn(), b"%PDF-1.4", 5, 5)
    assert sent == [("error", "ValueError")]


def test_text_formatter_ignores_a_traceback_cached_by_another_handler():
    try:
        _raise()
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "m", None, sys.exc_info())
    logging.Formatter().format(record)  # handler "comum" guarda o traceback com a mensagem em exc_text
    assert "Maria Souza" in (record.exc_text or "")
    out = SafeTextFormatter("%(message)s").format(record)
    assert "Maria Souza" not in out and "ValueError" in out


def _json_record(extra: dict) -> dict:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "evento", None, None)
    for k, v in extra.items():
        setattr(record, k, v)
    return json.loads(JsonFormatter().format(record))


def test_only_allowlisted_extra_keys_reach_the_log():
    out = _json_record(
        {"job_id": "abc", "values": {"cpf": "529.982.247-25"}, "content": SECRET, "duration_ms": 12}
    )
    assert out["job_id"] == "abc" and out["duration_ms"] == 12
    assert "values" not in out and "content" not in out
    assert out["omitted_keys"] == ["content", "values"]  # só o nome da chave, para achar o log errado
    assert "Maria" not in json.dumps(out) and "529.982" not in json.dumps(out)


def test_allowlisted_text_is_masked_and_truncated_and_download_token_hidden():
    out = _json_record(
        {"path": "/api/v1/downloads/eyJ0b2tlbiI6InNlZ3JlZG8ifQ.assinatura", "error": "x" * 500}
    )
    assert out["path"] == "/api/v1/downloads/[token]"
    assert len(out["error"]) == 200
    out2 = _json_record({"error": "falhou para fulano@exemplo.com"})
    assert "fulano@exemplo.com" not in out2["error"]
