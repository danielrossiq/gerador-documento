"""Verificação de assinaturas digitais PAdES em PDF (D40: gov.br assistido e certificado ICP-Brasil feito fora do app).

Roda só isolado, como o resto da leitura de PDF de fora (D35): no serviço `pdfconv` (rota `/verify`) ou, fora de
produção, num processo filho descartável com limite de tempo e memória. O processo da API nunca abre o PDF.

Usa pyHanko sem buscar nada na rede (sem OCSP/CRL): diz se cada assinatura está íntegra, se cobre o arquivo inteiro,
quem assinou (nome e CPF mascarado do certificado) e quando. A cadeia de confiança (ICP-Brasil, gov.br) só é
conferida se SIGNATURE_TRUST_ROOTS_DIR apontar para os certificados raiz; a conferência oficial e completa é em
https://validar.iti.gov.br.
"""

from __future__ import annotations

import io
import logging
import multiprocessing
import os
import re
from pathlib import Path
from typing import Any

from app.docx_engine.pdf_import import _SLOTS, _limit_resources, looks_like_pdf
from app.docx_engine.safety import DocxRejected

VERIFY_TIMEOUT_S = 30
MAX_SIGNATURES = 20
CPF_OID = "2.16.76.1.3.1"  # ICP-Brasil: dados do titular (nascimento + CPF + …) no subjectAltName


def _load_roots(directory: str | None) -> list[Any]:
    if not directory:
        return []
    from asn1crypto import pem
    from asn1crypto import x509 as ax509

    roots = []
    for f in sorted(Path(directory).glob("*"))[:200]:
        if f.suffix.lower() not in (".crt", ".cer", ".pem", ".der") or not f.is_file():
            continue
        raw = f.read_bytes()
        try:
            if pem.detect(raw):
                roots.extend(ax509.Certificate.load(der) for _, _, der in pem.unarmor(raw, multiple=True))
            else:
                roots.append(ax509.Certificate.load(raw))
        except ValueError:
            continue
    return roots


def mask_cpf(digits: str) -> str:
    return f"***.{digits[3:6]}.{digits[6:9]}-**"


def _cpf(cert: Any) -> str | None:
    """CPF do titular: no nome comum ("NOME:00000000000", e-CPF) ou no subjectAltName ICP-Brasil (OID 2.16.76.1.3.1,
    onde o CPF vem depois dos 8 dígitos da data de nascimento). Sai mascarado."""
    cn = str(cert.subject.native.get("common_name") or "")
    m = re.search(r":(\d{11})$", cn)
    if m:
        return mask_cpf(m.group(1))
    try:
        san = cert.subject_alt_name_value
    except ValueError:
        return None
    for name in san or []:
        if name.name != "other_name":
            continue
        other = name.chosen
        if other["type_id"].dotted != CPF_OID:
            continue
        raw = other["value"].native
        text = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 19:
            return mask_cpf(digits[8:19])
    return None


def _name(name: Any) -> str:
    """Nome comum sem o ":CPF"/":CNPJ" que os certificados ICP-Brasil põem no fim (vale para titular e emissor)."""
    native = name.native
    cn = str(native.get("common_name") or native.get("organization_name") or "")
    return re.sub(r":\d{11,14}$", "", cn)[:200]


def verify_pdf_signatures(data: bytes, trust_roots_dir: str | None = None) -> dict[str, Any]:
    """Assinaturas do PDF → lista com quem, quando, íntegra, válida, confiável e cobertura."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.status import SignatureCoverageLevel
    from pyhanko_certvalidator import ValidationContext

    # o pyHanko registra em log o assunto do certificado (nome, CPF) quando a cadeia não fecha: silencia
    for name in ("pyhanko", "pyhanko_certvalidator"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    if not looks_like_pdf(data):
        raise DocxRejected("NOT_A_PDF", "O arquivo não é um PDF válido.")
    try:
        reader = PdfFileReader(io.BytesIO(data), strict=False)
        if reader.encrypted:
            raise DocxRejected("ENCRYPTED", "PDFs protegidos por senha não são aceitos.")
        embedded = list(reader.embedded_signatures)[:MAX_SIGNATURES]
    except DocxRejected:
        raise
    except Exception as exc:
        raise DocxRejected("NOT_A_PDF", "O arquivo está corrompido ou não é um PDF válido.") from exc
    roots = _load_roots(trust_roots_dir)
    context = ValidationContext(trust_roots=roots, allow_fetching=False)
    out: list[dict[str, Any]] = []
    for emb in embedded:
        field = str(emb.field_name or "")[:100]
        try:
            st = validate_pdf_signature(emb, context)
        except Exception as exc:  # assinatura malformada: aparece como inválida, sem a mensagem
            out.append({"field": field, "intact": False, "valid": False, "trusted": False, "error": type(exc).__name__})
            continue
        cert = st.signing_cert
        when = st.signer_reported_dt
        if st.timestamp_validity is not None:
            when = st.timestamp_validity.timestamp
        out.append(
            {
                "field": field,
                "signer": _name(cert.subject),
                "cpf": _cpf(cert),
                "issuer": _name(cert.issuer),
                "signed_at": when.isoformat() if when else None,
                "timestamped": st.timestamp_validity is not None,
                "intact": bool(st.intact),
                "valid": bool(st.valid),
                "trusted": bool(st.trusted),
                "covers_whole_file": st.coverage == SignatureCoverageLevel.ENTIRE_FILE,
                "modification": st.modification_level.name.lower() if st.modification_level else None,
            }
        )
    return {"signatures": out, "trust_roots": len(roots)}


def _child_verify(conn: Any, data: bytes, timeout: int, roots_dir: str | None) -> None:  # pragma: no cover - subprocesso
    try:
        _limit_resources(timeout)
        conn.send(("ok", verify_pdf_signatures(data, roots_dir)))
    except DocxRejected as exc:
        conn.send(("rejected", (exc.code, exc.message)))
    except BaseException as exc:
        conn.send(("error", type(exc).__name__))  # nunca a mensagem: pode citar o certificado ou o documento
    finally:
        conn.close()


def verify_isolated(data: bytes, timeout: int = VERIFY_TIMEOUT_S) -> dict[str, Any]:
    """Verificação num processo filho descartável (nunca no processo da API)."""
    roots_dir = os.environ.get("SIGNATURE_TRUST_ROOTS_DIR") or None
    mp = multiprocessing.get_context("spawn")
    with _SLOTS:
        recv, send = mp.Pipe(duplex=False)
        proc = mp.Process(target=_child_verify, args=(send, data, timeout, roots_dir), daemon=True)
        proc.start()
        send.close()
        try:
            if not recv.poll(timeout):
                raise DocxRejected("PDF_TIMEOUT", "O PDF demorou demais para ser verificado.")
            status, payload = recv.recv()
        except EOFError as exc:
            raise DocxRejected("NOT_A_PDF", "Não foi possível verificar este PDF.") from exc
        finally:
            recv.close()
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)
    if status == "ok":
        return payload  # type: ignore[no-any-return]
    if status == "rejected":
        raise DocxRejected(*payload)
    raise DocxRejected("SIGNATURE_VERIFY_FAILED", "Não foi possível verificar as assinaturas deste PDF.")
