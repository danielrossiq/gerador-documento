"""Arquivos de teste gerados na hora (todos fictícios): .docx grandes/malformados, zip bomb, imagens, planilhas.

Nada aqui usa documento real de pessoa. Os CPFs são de teste (dígitos verificadores válidos, sem dono).
"""

# ruff: noqa: S311 — ferramenta de teste local (sorteio não criptográfico, subprocessos fixos)
from __future__ import annotations

import io
import os
import random
import zipfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO_DOCX = ROOT / "demo" / "contrato_prestacao_servicos.docx"
FIXTURES = ROOT / "frontend" / "e2e" / "fixtures"
CPFS_TESTE = ["529.982.247-25", "111.444.777-35", "390.533.447-05", "714.602.380-01"]

CT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="bin" ContentType="application/octet-stream"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    'officeDocument" Target="word/document.xml"/></Relationships>'
)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _para(text: str) -> str:
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def docx_from_paragraphs(paragraphs: list[str], extra: dict[str, bytes] | None = None) -> bytes:
    body = "".join(_para(p) for p in paragraphs)
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def contract_paragraph(i: int) -> str:
    cpf = CPFS_TESTE[i % len(CPFS_TESTE)]
    return (
        f"Cláusula {i}. CONTRATANTE: Maria Ficticia Souza, CPF {cpf}, residente na Rua das Flores, {i}, "
        f"São Paulo/SP, CEP 01310-100, pagará R$ {1000 + i},00 até 10/0{1 + i % 9}/2027."
    )


@lru_cache
def demo_docx() -> bytes:
    return DEMO_DOCX.read_bytes()


@lru_cache
def many_paragraphs_docx(n: int) -> bytes:
    """Documento "normal" mas longo: n parágrafos de contrato (texto comprime bem: 50 mil ≈ 1 MB)."""
    return docx_from_paragraphs([contract_paragraph(i) for i in range(n)])


@lru_cache
def big_media_docx(mb: int) -> bytes:
    """Poucos parágrafos + um anexo binário aleatório (não comprime): testa o teto de tamanho do upload."""
    return docx_from_paragraphs([contract_paragraph(i) for i in range(5)], {"word/media/imagem1.bin": os.urandom(mb * 1024 * 1024)})


@lru_cache
def zip_bomb_docx() -> bytes:
    """Uma parte de 200 MB de zeros (~200 KB comprimida): deve cair na checagem de razão de compressão."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{_para("x")}</w:body></w:document>')
        z.writestr("word/media/bomba.bin", b"\0" * (200 * 1024 * 1024))
    return buf.getvalue()


@lru_cache
def sub_threshold_bomb_docx() -> bytes:
    """240 partes de 1 MB - 1 byte de zeros (abaixo do limiar da checagem de razão): ~240 MB em ~250 KB."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{_para("Contrato curto.")}</w:body></w:document>')
        for i in range(240):
            z.writestr(f"word/media/p{i}.bin", b"\0" * (1024 * 1024 - 1))
    return buf.getvalue()


def corrupt_docx() -> bytes:
    data = bytearray(demo_docx())
    for i in range(200, min(len(data), 4000), 7):
        data[i] = random.randint(0, 255)
    return bytes(data)


def truncated_docx() -> bytes:
    return demo_docx()[: len(demo_docx()) // 2]


def entity_docx() -> bytes:
    """document.xml com DTD/entidades (billion laughs pequeno): o leitor seguro deve recusar sem expandir."""
    lol = '<!DOCTYPE w:document [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
    doc = f'<?xml version="1.0"?>{lol}<w:document xmlns:w="{W}"><w:body>{_para("&c;")}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def fake_pdf_with_docx_ext() -> bytes:
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def typed_pdf() -> bytes:
    """PDF digitado (o mesmo gerador fictício dos testes do backend)."""
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from tests import pdf_samples  # type: ignore[import-not-found]

    return pdf_samples.typed_pdf()


def scanned_pdf(pages: int = 3, side: int = 1600) -> bytes:
    """PDF "escaneado": só imagens, sem camada de texto."""
    from PIL import Image, ImageDraw

    imgs = []
    for p in range(pages):
        im = Image.new("RGB", (side, int(side * 1.41)), (250, 250, 245))
        d = ImageDraw.Draw(im)
        for y in range(80, im.height - 80, 40):
            d.line((80, y, im.width - 80 - (y * 7 + p) % 300, y), fill=(30, 30, 30), width=3)
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:], resolution=150)
    return buf.getvalue()


# ------------------------------------------------------------------ imagens (fotos de documento)


def photo(width: int = 4000, height: int = 3000, quality: int = 80) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (width, height), (240, 240, 235))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def noisy_photo(width: int = 2400, height: int = 1800) -> bytes:
    """Foto com ruído (não comprime): ~tamanho real de foto de celular."""
    from PIL import Image

    img = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def png_dimensions(width: int, height: int) -> bytes:
    """PNG de dimensões enormes que comprime para quase nada (bomba de descompressão de imagem)."""
    from PIL import Image

    img = Image.new("L", (width, height), 0)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False, compress_level=9)
    return buf.getvalue()


def corrupt_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + os.urandom(5000)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ------------------------------------------------------------------ planilhas


def xlsx_rows(rows: int, cols: int = 7) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Modelo"
    ws.append([f"Coluna {c}" for c in range(cols)])
    for r in range(rows):
        ws.append([f"valor {r}-{c}" for c in range(cols)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_dimension_bomb(declared_rows: int = 200, declared_col: str = "XFD") -> bytes:
    """Planilha minúscula que DECLARA dimensão enorme (<dimension ref="A1:XFD..."/>) e tem uma célula na última
    linha: o leitor read_only do openpyxl preenche as linhas/colunas vazias até a dimensão declarada."""
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{declared_col}{declared_rows}"/><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Nome</t></is></c></row>'
        f'<row r="{declared_rows}"><c r="A{declared_rows}" t="inlineStr"><is><t>x</t></is></c></row>'
        "</sheetData></worksheet>"
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="Modelo" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()
