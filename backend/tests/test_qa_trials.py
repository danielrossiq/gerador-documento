"""Teste grátis (D38): casos-limite achados pelo QA na rota pública anônima.

Reproduzem bugs achados e corrigidos (QA-1, QA-3, QA-4 e a armadilha detectável, 0091fbc) e protegem
comportamentos que já estavam certos (claim, contagem de páginas, dois arquivos).
"""

from __future__ import annotations

import io
import time
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)


def _docx(paragraphs: list[str], ct_padding: int = 0) -> bytes:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT.replace("</Types>", f"<!--{'x' * ct_padding}--></Types>"))
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def _corrupt_member(data: bytes, name: str) -> bytes:
    zf = zipfile.ZipFile(io.BytesIO(data))
    info = zf.getinfo(name)
    raw = bytearray(data)
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    for i in range(start + 2, start + info.compress_size - 2):
        raw[i] ^= 0x5A
    return bytes(raw)


def send(api, content: bytes, **form: str):  # type: ignore[no-untyped-def]
    files = {"file": ("contrato.docx", content, "application/octet-stream")}
    return api.post("/public/trials", files=files, data=form)


def test_corrupt_compressed_part_is_refused_with_422(api):
    bad = _corrupt_member(_docx(["Contrato de teste."], ct_padding=3000), "[Content_Types].xml")
    r = send(api, bad)
    assert r.status_code == 422, r.text


def test_malformed_multipart_is_400(api):
    r = api.post(
        "/public/trials", content=b"x" * 100, headers={"Content-Type": "multipart/form-data; boundary=zzz"}
    )
    assert r.status_code == 400, r.text


def test_dense_document_is_processed_quickly(api):
    # 1 parágrafo de ~8 mil caracteres com ~800 achados (datas, CPFs, valores, CEPs): bem abaixo do teto de 10 páginas
    para = " ".join(["01/02/2027", "529.982.247-25", "R$ 1,00", "01310-100"] * 200)
    t = time.perf_counter()
    r = send(api, _docx([para]))  # JOB_BACKEND=sync: o processamento roda dentro do POST
    elapsed = time.perf_counter() - t
    assert r.status_code == 202, r.text
    assert api.get(f"/public/trials/{r.json()['token']}").json()["status"] == "done"
    assert elapsed < 1.0, f"{elapsed:.1f}s para um .docx de {len(_docx([para]))} bytes"


def test_honeypot_token_is_indistinguishable_from_a_real_one(api):
    r = send(api, _docx(["Contrato de teste, CPF 529.982.247-25."]), website="http://spam.example")
    assert r.status_code == 202
    assert api.get(f"/public/trials/{r.json()['token']}").status_code == 200


def test_claimed_or_unknown_trial_cannot_be_claimed_again(api, api2):
    r = send(api, _docx(["CONTRATANTE: Maria Ficticia Souza, CPF 529.982.247-25, paga R$ 1.000,00."]))
    token = r.json()["token"]
    api.register()
    first = api.post(f"/trials/{token}/claim")
    assert first.status_code == 201, first.text
    assert api.post(f"/trials/{token}/claim").status_code == 404
    api2.register()
    assert api2.post(f"/trials/{token}/claim").status_code == 404  # outro usuário com o link
    assert api2.get(f"/generators/{first.json()['generator_id']}").status_code == 404
    assert api.get(f"/public/trials/{token}").status_code == 404  # o link do teste deixa de valer


def test_claim_without_session_is_401(api):
    token = send(api, _docx(["Contrato curto, CPF 529.982.247-25."])).json()["token"]
    assert api.post(f"/trials/{token}/claim").status_code == 401


def test_word_page_count_cannot_hide_a_long_document(api):
    # docProps/app.xml diz 1 página, mas o texto passa do teto de 10 páginas: o servidor conta os caracteres
    data = _docx([f"Cláusula {i}. " + "Texto do contrato de teste. " * 8 for i in range(250)])
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "a") as z:
        z.writestr("docProps/app.xml", "<Properties xmlns='http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'><Pages>1</Pages></Properties>")
    r = send(api, buf.getvalue())
    status = api.get(f"/public/trials/{r.json()['token']}").json()
    assert status["status"] == "failed" and status["error"]["code"] == "TRIAL_TOO_LONG"


def test_two_files_in_one_request_are_refused(api):
    doc = _docx(["Contrato."])
    files = [("file", ("a.docx", doc, "application/octet-stream")), ("file", ("b.docx", doc, "application/octet-stream"))]
    assert api.post("/public/trials", files=files).status_code == 400
