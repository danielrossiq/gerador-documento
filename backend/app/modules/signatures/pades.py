"""Verificação PAdES do PDF assinado fora do app (gov.br, certificado ICP-Brasil), do lado da API.

A API só repassa o PDF: no serviço isolado `pdfconv` (`POST /verify`) quando PDF_CONVERTER_URL está configurado, ou
num processo filho fora de produção. Em produção sem o serviço, a verificação fica indisponível (o PDF de fora nunca
é aberto no processo da API, D35).
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.errors import ServiceUnavailable, ValidationFailed
from app.core.logging import get_logger
from app.docx_engine.safety import DocxRejected

log = get_logger(__name__)

VERIFY_URL = "https://validar.iti.gov.br"
SIGNER_URL = "https://assinador.iti.br"


def verify_remote(data: bytes, *, url: str, client: Any = None) -> dict[str, Any]:
    import httpx

    http = client or httpx.Client(timeout=60)
    try:
        resp = http.post(f"{url.rstrip('/')}/verify", content=data, headers={"Content-Type": "application/pdf"})
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.error("pdfconv_verify_indisponivel", extra={"error_type": type(exc).__name__})
        raise DocxRejected("PDF_CONVERTER_UNAVAILABLE", "A verificação de assinaturas está indisponível agora.") from exc
    finally:
        if client is None:
            http.close()
    if resp.status_code == 200 and isinstance(body, dict) and isinstance(body.get("signatures"), list):
        return body
    if resp.status_code in (413, 422) and isinstance(body, dict) and isinstance(body.get("code"), str):
        raise DocxRejected(body["code"][:64], str(body.get("message") or "")[:300])
    raise DocxRejected("SIGNATURE_VERIFY_FAILED", "Não foi possível verificar as assinaturas deste PDF.")


def verify(data: bytes) -> dict[str, Any]:
    """Assinaturas do PDF (quem, quando, íntegra). Recusas viram ValidationFailed com o código do conversor."""
    s = get_settings()
    try:
        if s.pdf_converter_url:
            return verify_remote(data, url=s.pdf_converter_url)
        if s.is_production:
            raise ServiceUnavailable(
                "A verificação de assinaturas está indisponível agora.", code="SIGNATURE_VERIFY_UNAVAILABLE"
            )
        from app.pdfconv.signatures import verify_isolated

        return verify_isolated(data)
    except DocxRejected as exc:
        if exc.code == "PDF_CONVERTER_UNAVAILABLE":
            raise ServiceUnavailable(exc.message, code="SIGNATURE_VERIFY_UNAVAILABLE") from exc
        raise ValidationFailed(exc.message or "Não foi possível ler este PDF.", code=exc.code) from exc
