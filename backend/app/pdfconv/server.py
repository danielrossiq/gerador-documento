"""Conversor de PDF → .docx em contêiner próprio (D35).

PDF é um formato complexo e o arquivo vem de fora; o leitor (PDFium/pdfminer) é a parte do sistema mais exposta
a um arquivo malicioso. Por isso a conversão roda aqui, e não na API:

* contêiner sem segredos (nada de banco, storage, chaves) e só numa rede Docker interna, sem saída para a internet
  e sem porta publicada — só a API alcança este serviço;
* sistema de arquivos somente leitura (+ /tmp pequeno em memória), usuário sem privilégios, sem capabilities,
  limites de memória/CPU/processos do contêiner (docker-compose.yml);
* dentro dele, cada PDF ainda é convertido num processo filho descartável com tempo e memória limitados
  (`convert_pdf`), e no máximo `PDFCONV_MAX_INFLIGHT` conversões por vez (o resto recebe 503).

Protocolo (só a API usa):
  GET  /health                       → 200 "ok"
  POST /convert  (corpo = o PDF)     → 200 {"docx": base64, "stats": {...}, "warnings": [...]}
                 X-Max-Pages: n      → 422 {"code", "message"}  (PDF recusado: digitalizado, com senha…)
                                     → 413 arquivo grande demais · 503 ocupado · 500 falha
Nada do conteúdo vai para o log: só códigos e tipos de erro.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.core.logging import configure_logging, get_logger
from app.docx_engine.pdf_import import PDF_MAX_PAGES, convert_pdf, looks_like_pdf, pdf_info_isolated
from app.docx_engine.safety import DocxRejected

log = get_logger("app.pdfconv")

MAX_BYTES = int(os.environ.get("PDFCONV_MAX_MB", "16")) * 1024 * 1024
MAX_PAGES = int(os.environ.get("PDFCONV_MAX_PAGES", str(PDF_MAX_PAGES)))
DRAIN_MAX = 64 * 1024 * 1024  # só a API fala com o serviço; ela nunca manda mais que isso
_INFLIGHT = threading.BoundedSemaphore(int(os.environ.get("PDFCONV_MAX_INFLIGHT", "4")))


class Handler(BaseHTTPRequestHandler):
    server_version = "pdfconv"
    sys_version = ""
    timeout = 30  # leitura do corpo: cliente lento não segura uma thread para sempre

    def log_message(self, format: str, *args: object) -> None:
        return  # o log de acesso padrão escreveria caminho/cliente em texto livre; registramos só o essencial

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self, length: int) -> None:
        """Descarta o corpo de uma recusa (até DRAIN_MAX) para a resposta chegar inteira; acima disso, só fecha."""
        if length > DRAIN_MAX:
            return
        left = length
        while left > 0:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)

    def do_GET(self) -> None:
        if self.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json(404, {"code": "NOT_FOUND", "message": "Rota inexistente."})

    def do_POST(self) -> None:
        if self.path not in ("/convert", "/info"):
            self._json(404, {"code": "NOT_FOUND", "message": "Rota inexistente."})
            return
        try:
            length = int(self.headers.get("Content-Length") or "-1")
        except ValueError:
            length = -1
        if length < 0:
            self._json(411, {"code": "LENGTH_REQUIRED", "message": "Tamanho do arquivo não informado."})
            return
        if length > MAX_BYTES:
            self.close_connection = True
            self._drain(length)  # sem ler, o cliente às vezes via a conexão cair antes do 413 (teste intermitente)
            self._json(
                413,
                {
                    "code": "FILE_TOO_LARGE",
                    "message": f"O arquivo excede o limite de {MAX_BYTES // (1024 * 1024)} MB.",
                },
            )
            return
        try:
            max_pages = min(MAX_PAGES, max(1, int(self.headers.get("X-Max-Pages") or MAX_PAGES)))
        except ValueError:
            max_pages = MAX_PAGES
        if not _INFLIGHT.acquire(blocking=False):
            self.close_connection = True
            self._drain(length)
            self._json(
                503,
                {
                    "code": "PDF_CONVERTER_BUSY",
                    "message": "Muitas conversões ao mesmo tempo. Tente de novo em instantes.",
                },
            )
            return
        if self.path == "/info":
            self._info(length)
            return
        try:
            data = self.rfile.read(length)
            conv = convert_pdf(data, max_bytes=MAX_BYTES, max_pages=max_pages)
        except DocxRejected as exc:
            log.info("pdfconv_recusado", extra={"code": exc.code})
            self._json(422, {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:  # nunca a mensagem: pode trazer trecho do documento
            log.error("pdfconv_falhou", extra={"error_type": type(exc).__name__})
            self._json(
                500, {"code": "PDF_CONVERSION_FAILED", "message": "Não foi possível converter este PDF."}
            )
            return
        finally:
            _INFLIGHT.release()
        log.info(
            "pdfconv_ok",
            extra={"pages": conv.stats.get("pages"), "bytes_in": length, "bytes_out": len(conv.docx)},
        )
        self._json(
            200,
            {"docx": base64.b64encode(conv.docx).decode(), "stats": conv.stats, "warnings": conv.warnings},
        )

    def _info(self, length: int) -> None:
        """`POST /info`: só conta as páginas (processo filho com tempo e memória limitados). Serve para a API estimar o
        custo da leitura de um PDF pela IA sem abrir o PDF dela mesma (D37/D39)."""
        try:
            data = self.rfile.read(length)
            if not looks_like_pdf(data):
                raise DocxRejected("NOT_A_PDF", "O arquivo não é um PDF válido.")
            info = pdf_info_isolated(data)
        except DocxRejected as exc:
            log.info("pdfconv_info_recusado", extra={"code": exc.code})
            self._json(422, {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:
            log.error("pdfconv_info_falhou", extra={"error_type": type(exc).__name__})
            self._json(500, {"code": "PDF_INFO_FAILED", "message": "Não foi possível ler este PDF."})
            return
        finally:
            _INFLIGHT.release()
        self._json(200, {"pages": info["pages"]})


def make_server(host: str = "0.0.0.0", port: int = 8090) -> ThreadingHTTPServer:  # noqa: S104 - só na rede interna
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def main() -> None:
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"), os.environ.get("LOG_JSON", "true") == "true")
    port = int(os.environ.get("PDFCONV_PORT", "8090"))
    log.info(
        "pdfconv_iniciado", extra={"port": port, "max_mb": MAX_BYTES // (1024 * 1024), "max_pages": MAX_PAGES}
    )
    make_server(port=port).serve_forever()


if __name__ == "__main__":
    main()
