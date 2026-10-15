"""PDFs de teste gerados na hora com o PDFium: digitalizado (só imagem), digitalizado com camada de OCR
(texto invisível por cima da imagem), misto e digitado sobre papel timbrado.

O PDF digitado "real" vem de `fixtures/contrato_digitado.pdf` (o contrato de demonstração exportado pelo
LibreOffice) e `fixtures/locacao_digitado.pdf` (3 páginas: justificado, listas, tabela que atravessa a
página com célula mesclada e rodapé "Página X de Y").
"""

from __future__ import annotations

import ctypes
import io
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

FIXTURES = Path(__file__).parent / "fixtures"


def typed_pdf(name: str = "contrato_digitado.pdf") -> bytes:
    return (FIXTURES / name).read_bytes()


def _save(doc: pdfium.PdfDocument) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _page_image(pdf_bytes: bytes, index: int = 0, scale: float = 1.5):  # type: ignore[no-untyped-def]
    src = pdfium.PdfDocument(pdf_bytes)
    return src[index].render(scale=scale).to_pil().convert("RGB")


def _add_image(
    doc: pdfium.PdfDocument, page: pdfium.PdfPage, pil, x: float, y: float, w: float, h: float
) -> None:  # type: ignore[no-untyped-def]
    img = pdfium.PdfImage.new(doc)
    img.set_bitmap(pdfium.PdfBitmap.from_pil(pil))
    img.set_matrix(pdfium.PdfMatrix().scale(w, h).translate(x, y))
    page.insert_obj(img)


def _add_text(
    doc: pdfium.PdfDocument, page: pdfium.PdfPage, text: str, x: float, y: float, *, invisible: bool
) -> None:
    font = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
    obj = pdfium_c.FPDFPageObj_CreateTextObj(doc.raw, font, 11.0)
    raw = (text + "\0").encode("utf-16-le")
    buf = ctypes.create_string_buffer(raw, len(raw))
    pdfium_c.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(pdfium_c.FPDF_WCHAR)))
    if invisible:
        pdfium_c.FPDFTextObj_SetTextRenderMode(obj, pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE)
    pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
    pdfium_c.FPDFPage_InsertObject(page.raw, obj)


LINES = [
    "CONTRATO DE PRESTACAO DE SERVICOS",
    "CONTRATANTE: Joao da Silva, inscrito no CPF sob o no 123.456.789-09.",
    "CONTRATADA: Estudio Exemplo Servicos Ltda., CNPJ 11.222.333/0001-81.",
    "CLAUSULA 1a - DO OBJETO. Prestacao de servicos de consultoria em software.",
    "CLAUSULA 2a - DO VALOR. Valor mensal de R$ 5.000,00.",
]


def scanned_pdf(*, ocr: bool = False, pages: int = 1) -> bytes:
    """Página inteira como imagem (foto/escaneamento); com `ocr`, a camada de texto invisível dos scanners."""
    pil = _page_image(typed_pdf())
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        page = doc.new_page(595, 842)
        _add_image(doc, page, pil, 0, 0, 595, 842)
        if ocr:
            for i, line in enumerate(LINES):
                _add_text(doc, page, line, 72, 760 - i * 16, invisible=True)
        page.gen_content()
    return _save(doc)


def mixed_pdf() -> bytes:
    """Contrato digitado (2 páginas) + um anexo escaneado (página 3)."""
    doc = pdfium.PdfDocument(typed_pdf())
    doc.import_pages(pdfium.PdfDocument(scanned_pdf()))
    return _save(doc)


def letterhead_pdf() -> bytes:
    """Texto digitado de verdade por cima de um papel timbrado que ocupa a página inteira: é aceito."""
    from PIL import Image

    doc = pdfium.PdfDocument.new()
    page = doc.new_page(595, 842)
    _add_image(doc, page, Image.new("RGB", (60, 85), (235, 240, 250)), 0, 0, 595, 842)
    for i, line in enumerate(LINES * 2):
        _add_text(doc, page, line, 72, 760 - i * 16, invisible=False)
    page.gen_content()
    return _save(doc)


def encrypted_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for p in PdfReader(io.BytesIO(typed_pdf())).pages:
        writer.add_page(p)
    writer.encrypt("senha-secreta")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
