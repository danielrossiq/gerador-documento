"""Robustez contra arquivos e tamanhos que um usuário (ou atacante) pode mandar — achados do QA da sprint.

Os testes marcados `xfail(strict=True)` reproduzem bugs ainda abertos: quando o bug for corrigido o teste passa,
o pytest acusa XPASS e é hora de tirar a marca.
"""

from __future__ import annotations

import io
import time
import zipfile

import pytest

from app.modules.suggestions.rules import Hit, resolve_overlaps

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT * 3)  # repetido: a parte fica grande o bastante para corromper
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def _corrupt_member(data: bytes, name: str) -> bytes:
    """Estraga os bytes comprimidos de uma parte, mantendo o ZIP "válido" por fora (diretório central intacto)."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    info = zf.getinfo(name)
    raw = bytearray(data)
    head = 30 + len(info.filename.encode()) + len(info.extra)
    start = info.header_offset + head
    for i in range(start + 2, start + info.compress_size - 2):
        raw[i] ^= 0x5A
    return bytes(raw)


def _gen(api) -> str:  # type: ignore[no-untyped-def]
    api.register()
    return api.post("/generators", json={"name": "Robustez"}).json()["id"]


@pytest.mark.xfail(strict=True, reason="BUG QA-1: zlib.error de parte corrompida vira 500 (validate_docx/parse_docx)")
def test_docx_with_corrupt_compressed_part_is_rejected_with_422(api):
    gid = _gen(api)
    bad = _corrupt_member(_docx(["Contrato de teste."]), "[Content_Types].xml")
    r = api.post(f"/generators/{gid}/template", files={"file": ("contrato.docx", bad, "application/octet-stream")})
    assert r.status_code == 422, r.text


@pytest.mark.xfail(strict=True, reason="BUG QA-1: zlib.error de parte corrompida vira 500 (validate_docx/parse_docx)")
def test_docx_with_corrupt_document_xml_is_rejected_with_422(api):
    gid = _gen(api)
    bad = _corrupt_member(_docx(["Contrato de teste. " * 50]), "word/document.xml")
    r = api.post(f"/generators/{gid}/template", files={"file": ("contrato.docx", bad, "application/octet-stream")})
    assert r.status_code == 422, r.text


@pytest.mark.xfail(strict=True, reason="BUG QA-2: resolve_overlaps é quadrático no documento inteiro (4 mil parágrafos = 4 min)")
def test_resolve_overlaps_scales_with_document_size():
    # 1.500 parágrafos com 4 trechos cada (CPF, valor, data, nome) — um contrato longo, ~15 KB de .docx
    hits = [
        Hit(f"body/p{b}", s, s + 10, "x" * 10, "campo", "Campo", "text_short", 0.9, "rule", "")
        for b in range(1500)
        for s in (0, 20, 40, 60)
    ]
    t = time.perf_counter()
    out = resolve_overlaps(hits)
    elapsed = time.perf_counter() - t
    assert len(out) == len(hits)
    assert elapsed < 0.5, f"{len(hits)} trechos levaram {elapsed:.1f}s"
