"""PDF como documento-base: só PDFs digitados viram modelo; digitalizados (com ou sem OCR) são recusados."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.docx_engine.parse import parse_docx
from app.docx_engine.pdf_import import convert_pdf, pdf_to_docx
from app.docx_engine.safety import DocxRejected
from tests import pdf_samples
from tests.flows import upload


def _blocks(docx: bytes) -> dict[str, object]:
    return {b.key: b for b in parse_docx(docx).blocks}


def _rejected(data: bytes, **kw: object) -> DocxRejected:
    with pytest.raises(DocxRejected) as exc:
        pdf_to_docx(data, **kw)  # type: ignore[arg-type]
    return exc.value


# ------------------------------------------------------------------ conversão (no próprio processo)


def test_typed_contract_keeps_structure_of_the_original_docx():
    conv = pdf_to_docx(pdf_samples.typed_pdf())
    assert conv.stats == {"pages": 2, "paragraphs": 9, "tables": 1, "images": 1, "header": 1, "footer": 1}
    assert "convertido de PDF" in conv.warnings[0]
    blocks = _blocks(conv.docx)
    texts = [b.text for b in blocks.values()]  # type: ignore[attr-defined]
    # cabeçalho e rodapé repetidos nas duas páginas saem do corpo e vão para as partes do Word
    assert blocks["header1/p1"].text.startswith("Estúdio Exemplo Serviços Ltda.")  # type: ignore[attr-defined]
    assert blocks["footer1/p1"].text.startswith("Documento de demonstração")  # type: ignore[attr-defined]
    assert sum("Documento de demonstração" in t for t in texts) == 1
    assert blocks["body/p1"].attrs["align"] == "center"  # type: ignore[attr-defined]
    assert blocks["body/p2"].text == "￼"  # o logotipo virou imagem  # type: ignore[attr-defined]
    # cada cláusula é um parágrafo só (as linhas quebradas pelo PDF foram reunidas)
    p3 = blocks["body/p3"].text  # type: ignore[attr-defined]
    assert p3.startswith("CONTRATANTE: João da Silva, inscrito no CPF sob o nº 123.456.789-09")
    assert p3.endswith("doravante denominado CONTRATANTE.")
    assert "Renovação automática: Sim." in blocks["body/p7"].text  # type: ignore[attr-defined]
    cells = [blocks[f"body/t1/r{r}/c{c}/p1"].text for r in (1, 2, 3) for c in (1, 2)]  # type: ignore[attr-defined]
    assert cells == ["Item", "Detalhe", "Contratante", "João da Silva", "Valor mensal", "R$ 5.000,00"]
    assert blocks["body/p8"].attrs["align"] == "right"  # type: ignore[attr-defined]

    xml = zipfile.ZipFile(io.BytesIO(conv.docx)).read("word/document.xml").decode()
    assert "<w:pageBreakBefore/>" in xml  # a página de assinaturas continua começando numa página nova
    assert "<w:b/>" in xml and "<w:i/>" in xml  # "CONTRATANTE:" em negrito, "consultoria…" em itálico


def test_long_document_with_lists_page_numbers_and_table_across_pages():
    conv = pdf_to_docx(pdf_samples.typed_pdf("locacao_digitado.pdf"))
    blocks = _blocks(conv.docx)
    zf = zipfile.ZipFile(io.BytesIO(conv.docx))
    footer = next(zf.read(n).decode() for n in zf.namelist() if n.startswith("word/footer"))
    assert 'w:instr=" PAGE "' in footer and 'w:instr=" NUMPAGES "' in footer  # "Página X de Y" automático
    assert blocks["footer1/p1"].text == "Página ￼ de ￼"  # type: ignore[attr-defined]
    # tabela de 30 parcelas que atravessa a página vira UMA tabela, com o "Total" mesclado em 2 colunas
    rows = {k.split("/")[2] for k in blocks if k.startswith("body/t1/r")}
    assert len(rows) == 32
    assert blocks["body/t1/r32/c1/p1"].text == "Total"  # type: ignore[attr-defined]
    assert blocks["body/t1/r32/c2/p1"].text == "R$ 70.500,00"  # type: ignore[attr-defined]
    # itens de lista: um parágrafo por item, com tabulação depois do marcador
    items = [b.text for k, b in blocks.items() if k.startswith("body/p") and b.text[:2] in ("a)", "b)", "c)")]  # type: ignore[attr-defined]
    assert (
        len(items) == 3 and items[1].startswith("b)\tlevar") and items[1].endswith("turbações de terceiros;")
    )
    justified = [
        b for k, b in blocks.items() if k.startswith("body/p") and (b.attrs or {}).get("align") == "justify"
    ]  # type: ignore[attr-defined]
    assert len(justified) == 6
    xml = zf.read("word/document.xml").decode()
    assert "<w:u " in xml  # "R$ 2.350,00" sublinhado no original
    assert '<w:tab w:pos="' in xml  # assinaturas em colunas: paradas de tabulação nas posições do PDF


@pytest.mark.parametrize(
    ("sample", "code"),
    [
        (lambda: pdf_samples.scanned_pdf(), "PDF_SCANNED"),
        (lambda: pdf_samples.scanned_pdf(ocr=True), "PDF_SCANNED"),  # OCR = texto invisível sobre a imagem
        (lambda: pdf_samples.scanned_pdf(pages=3), "PDF_SCANNED"),
        (lambda: pdf_samples.encrypted_pdf(), "ENCRYPTED"),
        (lambda: b"%PDF-1.7\nisto nao e um pdf de verdade", "NOT_A_PDF"),
    ],
)
def test_rejects_scanned_encrypted_and_broken_pdfs(sample, code):
    assert _rejected(sample()).code == code


def test_scanned_message_explains_how_to_get_a_typed_pdf():
    msg = _rejected(pdf_samples.scanned_pdf(ocr=True)).message
    assert "digitalizado" in msg and "Salvar/Baixar como PDF" in msg and ".docx" in msg


def test_mixed_pdf_names_the_scanned_page():
    exc = _rejected(pdf_samples.mixed_pdf())
    assert exc.code == "PDF_SCANNED" and exc.message.startswith("A página 3 é uma imagem digitalizada")


def test_typed_text_over_letterhead_background_is_accepted():
    conv = pdf_to_docx(pdf_samples.letterhead_pdf())
    assert "CONTRATO DE PRESTACAO DE SERVICOS" in " ".join(b.text for b in parse_docx(conv.docx).blocks)
    assert any("papel timbrado" in w for w in conv.warnings)


def test_page_limit():
    exc = _rejected(pdf_samples.typed_pdf(), max_pages=1)
    assert exc.code == "PDF_TOO_MANY_PAGES" and "2 páginas" in exc.message


def test_isolated_conversion_matches_in_process_and_checks_size():
    """A API converte num processo filho (tempo e memória limitados); o resultado é o mesmo."""
    data = pdf_samples.typed_pdf()
    conv = convert_pdf(data, max_bytes=15 * 1024 * 1024)
    assert conv.stats == pdf_to_docx(data).stats
    with pytest.raises(DocxRejected) as exc:
        convert_pdf(pdf_samples.scanned_pdf(), max_bytes=15 * 1024 * 1024)
    assert exc.value.code == "PDF_SCANNED"  # a recusa atravessa o processo com código e mensagem
    with pytest.raises(DocxRejected) as exc:
        convert_pdf(data, max_bytes=1000, isolated=False)
    assert exc.value.code == "FILE_TOO_LARGE"


# ------------------------------------------------------------------ API


def test_upload_typed_pdf_becomes_an_editable_generator(api):
    api.register()
    gid = api.post("/generators", json={"name": "Contrato em PDF"}).json()["id"]
    r = upload(api, gid, pdf_samples.typed_pdf(), "contrato.pdf")
    assert r.status_code == 201, r.text
    assert r.json()["version"]["source_format"] == "pdf"

    ed = api.get(f"/generators/{gid}/editor").json()
    assert ed["version"]["source_filename"] == "contrato.pdf"
    assert any("convertido de PDF" in w for w in ed["warnings"])
    names = {g["suggested_name"] for g in api.get(f"/generators/{gid}/suggestions").json()["items"]}
    assert {"cpf_contratante", "cnpj_contratada", "valor"} <= names  # as sugestões funcionam igual ao .docx

    api.post(f"/generators/{gid}/suggestions/accept-all", json={"min_confidence": 0.9})
    values = {"cpf_contratante": "529.982.247-25", "valor": "1.234,50"}
    job = api.post(f"/generators/{gid}/generate", json={"values": values}).json()
    assert job["status"] == "succeeded", job


def test_upload_scanned_pdf_is_refused_and_audited(api):
    api.register()
    gid = api.post("/generators", json={"name": "Escaneado"}).json()["id"]
    r = upload(api, gid, pdf_samples.scanned_pdf(ocr=True), "escaneado.pdf")
    assert r.status_code == 422 and r.json()["error"]["code"] == "PDF_SCANNED"
    assert api.get(f"/generators/{gid}").json()["has_template"] is False
    assert upload(api, gid, b"nao sou pdf", "contrato.pdf").json()["error"]["code"] == "NOT_A_PDF"
