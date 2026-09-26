"""Conversão DOCX → PDF via LibreOffice headless, encapsulada em um adaptador.

Pontos importantes:
  * perfil do LibreOffice por *thread* (reaproveitado entre conversões → start rápido, sem conflito de lock);
  * várias conversões por invocação (o LO carrega uma vez) com *fallback item a item* para isolar falhas;
  * timeout com encerramento do grupo de processos; verificação do PDF de saída (`%PDF-`, tamanho > 0);
  * macros não são executadas: o arquivo já passou por `validate_docx` e o LO roda com perfil limpo.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import PermanentError, ServiceUnavailable, TransientError
from app.core.logging import get_logger

log = get_logger(__name__)


class PdfConverterUnavailable(ServiceUnavailable):
    code = "PDF_CONVERTER_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(
            "A conversão para PDF não está disponível neste ambiente (LibreOffice não encontrado). O DOCX foi gerado normalmente."
        )


class PdfConversionError(PermanentError):
    def __init__(self, message: str = "Falha ao converter o documento para PDF.") -> None:
        super().__init__(message, "PDF_CONVERSION_FAILED")


class PdfConversionTimeout(TransientError):
    pass


class PdfConverter(Protocol):
    def available(self) -> bool: ...
    def convert(self, docx: bytes) -> bytes: ...
    def convert_many(self, items: Sequence[tuple[str, bytes]]) -> dict[str, bytes | Exception]: ...


class NullConverter:
    def available(self) -> bool:
        return False

    def convert(self, docx: bytes) -> bytes:
        raise PdfConverterUnavailable

    def convert_many(self, items: Sequence[tuple[str, bytes]]) -> dict[str, bytes | Exception]:
        return {k: PdfConverterUnavailable() for k, _ in items}


class LibreOfficeConverter:
    def __init__(self, soffice_path: str, timeout: int, chunk_size: int) -> None:
        self.soffice = soffice_path
        self.timeout = timeout
        self.chunk_size = chunk_size
        self._local = threading.local()

    def available(self) -> bool:
        return shutil.which(self.soffice) is not None or Path(self.soffice).exists()

    def _profile(self) -> Path:
        prof = getattr(self._local, "profile", None)
        if prof is None or not prof.exists():
            prof = Path(tempfile.gettempdir()) / f"minuta_lo_{os.getpid()}_{threading.get_ident()}"
            prof.mkdir(parents=True, exist_ok=True)
            self._local.profile = prof
        return prof

    def _reset_profile(self) -> None:
        prof = getattr(self._local, "profile", None)
        if prof is not None:
            shutil.rmtree(prof, ignore_errors=True)
            self._local.profile = None

    def _run(self, files: list[Path], outdir: Path, timeout: float) -> None:
        cmd = [
            self.soffice,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nofirststartwizard",
            "--nologo",
            f"-env:UserInstallation={self._profile().as_uri()}",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(outdir),
            *map(str, files),
        ]
        kwargs: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 - comando fixo, argumentos não vêm do usuário
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._kill(proc)
            self._reset_profile()
            raise PdfConversionTimeout("Tempo esgotado na conversão para PDF.") from exc

    @staticmethod
    def _kill(proc: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait(timeout=10)

    @staticmethod
    def _read_pdf(path: Path) -> bytes:
        if not path.exists():
            raise PdfConversionError()
        data = path.read_bytes()
        if not data.startswith(b"%PDF-") or len(data) < 200:
            raise PdfConversionError("O PDF gerado é inválido.")
        return data

    def convert(self, docx: bytes) -> bytes:
        return self._one(docx)

    def _one(self, docx: bytes) -> bytes:
        if not self.available():
            raise PdfConverterUnavailable
        with tempfile.TemporaryDirectory(prefix="minuta_pdf_") as tmp:
            src = Path(tmp) / "doc.docx"
            src.write_bytes(docx)
            out = Path(tmp) / "out"
            out.mkdir()
            started = time.monotonic()
            self._run([src], out, self.timeout)
            pdf = self._read_pdf(out / "doc.pdf")
            log.info(
                "pdf_convertido",
                extra={"duration_ms": int((time.monotonic() - started) * 1000), "bytes": len(pdf)},
            )
            return pdf

    def convert_many(self, items: Sequence[tuple[str, bytes]]) -> dict[str, bytes | Exception]:
        if not self.available():
            return {k: PdfConverterUnavailable() for k, _ in items}
        results: dict[str, bytes | Exception] = {}
        for i in range(0, len(items), self.chunk_size):
            chunk = list(items[i : i + self.chunk_size])
            results.update(self._convert_chunk(chunk))
        return results

    def _convert_chunk(self, chunk: list[tuple[str, bytes]]) -> dict[str, bytes | Exception]:
        results: dict[str, bytes | Exception] = {}
        with tempfile.TemporaryDirectory(prefix="minuta_pdf_") as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            paths: dict[str, Path] = {}
            for n, (key, data) in enumerate(chunk):
                p = Path(tmp) / f"d{n}.docx"
                p.write_bytes(data)
                paths[key] = p
            started = time.monotonic()
            try:
                self._run(list(paths.values()), out, self.timeout + 5 * len(chunk))
            except (PdfConversionTimeout, OSError) as exc:
                log.warning(
                    "pdf_lote_falhou_fallback_individual",
                    extra={"error_type": type(exc).__name__, "n": len(chunk)},
                )
            for key, p in paths.items():
                try:
                    results[key] = self._read_pdf(out / f"{p.stem}.pdf")
                except PdfConversionError:
                    results[key] = PdfConversionError()
            log.info(
                "pdf_lote_convertido",
                extra={"n": len(chunk), "duration_ms": int((time.monotonic() - started) * 1000)},
            )
        # isola falhas: tenta individualmente só os que falharam no lote
        if len(chunk) > 1:
            for key, val in list(results.items()):
                if isinstance(val, Exception):
                    data = dict(chunk)[key]
                    try:
                        results[key] = self._one(data)
                    except Exception as exc:
                        results[key] = exc
        return results


CAPABILITY_KEY = "minuta:cap:pdf"
CAPABILITY_TTL = 90


def _redis_client():  # type: ignore[no-untyped-def]
    import redis

    url = get_settings().redis_url
    return redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1) if url else None


def publish_capability() -> bool:
    """Chamado pelo worker: sinaliza no Redis que há conversor de PDF utilizável (expira sozinho se o worker cair)."""
    if not get_pdf_converter().available():
        return False
    r = _redis_client()
    if r is None:
        return False
    r.setex(CAPABILITY_KEY, CAPABILITY_TTL, "1")
    return True


def pdf_available() -> bool:
    """A API pode não ter o LibreOffice (ele vive na imagem do worker): com fila externa, vale o que o worker publicou."""
    s = get_settings()
    if s.pdf_converter == "none":
        return False
    if s.job_backend == "dramatiq":
        try:
            r = _redis_client()
            return bool(r is not None and r.exists(CAPABILITY_KEY))
        except Exception:
            return False
    return get_pdf_converter().available()


_converter: PdfConverter | None = None


def get_pdf_converter() -> PdfConverter:
    global _converter
    if _converter is None:
        s = get_settings()
        _converter = (
            NullConverter()
            if s.pdf_converter == "none"
            else LibreOfficeConverter(s.soffice_path, s.pdf_timeout_seconds, s.pdf_chunk_size)
        )
    return _converter


def reset_pdf_converter() -> None:
    global _converter
    _converter = None
