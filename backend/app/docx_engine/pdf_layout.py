"""Conversão de PDF em "layout exato": para boletos, faturas, notas e formulários — documentos de caixas, colunas
lado a lado e códigos de barras, que como texto corrido nunca ficariam fiéis.

Cada página do .docx tem:
  * ao fundo, a página do PDF renderizada SEM o texto (caixas, linhas, fundos, logotipos, código de barras, QR),
    como imagem atrás do texto e no mesmo lugar;
  * por cima, o texto — editável, então os campos continuam funcionando — em quadros (w:framePr) posicionados
    exatamente onde cada trecho estava, com a mesma fonte, tamanho, cor, negrito e itálico.

Um valor bem mais comprido que o original quebra dentro do próprio quadro, como num formulário de papel.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

BG_DPI = 200  # fundo nítido o bastante para código de barras e QR continuarem legíveis
GAP_SPLIT = 1.2  # espaço (em tamanhos de fonte) que separa dois trechos na mesma linha de base
EMU_PER_PT = 12700


@dataclass
class Chunk:
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    base: float
    size: float
    segs: list[Any]  # pdf_import.Seg


def _chunks(chars: list[dict[str, Any]], page_no: int, page_height: float, rules: list[Any]) -> list[Chunk]:
    """Linhas de base → trechos: um espaço grande (colunas, caixas lado a lado) separa trechos independentes."""
    from app.docx_engine.pdf_import import _baseline, _clean, _line_from_chars

    items = []
    for ch in chars:
        text, _ = _clean(ch.get("text") or "")
        items.append((ch, text, _baseline(ch, page_height)))
    items.sort(key=lambda t: (round(t[2], 1), t[0]["x0"]))
    rows: list[list[tuple[dict[str, Any], str, float]]] = []
    for it in items:
        if rows and abs(it[2] - rows[-1][0][2]) <= max(1.5, 0.25 * it[0]["size"]):
            rows[-1].append(it)
        else:
            rows.append([it])
    out: list[Chunk] = []
    for row in rows:
        row.sort(key=lambda t: t[0]["x0"])
        groups: list[list[tuple[dict[str, Any], str, float]]] = []
        last_x1: float | None = None
        for it in row:
            ch = it[0]
            if not it[1].strip():
                if groups:
                    groups[-1].append(it)
                continue
            if last_x1 is None or ch["x0"] - last_x1 > GAP_SPLIT * ch["size"]:
                groups.append([it])
            else:
                groups[-1].append(it)
            last_x1 = ch["x1"]
        for g in groups:
            # sem detecção de sublinhado: no layout exato todo traço (inclusive sublinhado de verdade) já vem no fundo,
            # e a borda de caixa logo abaixo de um texto viraria um sublinhado a mais
            line = _line_from_chars(g, page_no, [])
            if line is None:
                continue
            seg_text = "".join(s.text for s in line.segs).rstrip()
            if not seg_text:
                continue
            out.append(
                Chunk(page_no, line.x0, line.x1, line.top, line.bottom, line.base, line.size, line.segs)
            )
    return out


def background_png(ppage: Any, width: float, height: float, dpi: int = BG_DPI) -> bytes | None:
    """A página sem os objetos de texto, renderizada. None se a página ficar em branco (nada além do texto)."""
    import pypdfium2.raw as pdfium_c

    texts = [o for o in ppage.get_objects(max_depth=1) if o.type == pdfium_c.FPDF_PAGEOBJ_TEXT]
    for o in texts:
        ppage.remove_obj(o)
        o.close()  # removido da página, o objeto passa a ser nosso: libera já (senão a PDFium reclama no fim)
    if texts:
        ppage.gen_content()
    pil = ppage.render(scale=dpi / 72).to_pil().convert("RGB")
    if pil.getextrema() == ((255, 255), (255, 255), (255, 255)):
        return None
    gray = pil.convert("L")
    if all(abs(a - b) < 6 for a, b in zip(pil.split()[0].getdata(), pil.split()[2].getdata(), strict=False)):
        pil = gray  # página sem cor: PNG em tons de cinza (bem menor)
    buf = io.BytesIO()
    pil.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def anchor_behind(
    run: Any, png: bytes, x: float, y: float, w: float, h: float, *, v_from: str = "page", behind: bool = True
) -> None:
    """Imagem flutuante posicionada (pt): horizontal em relação à página, vertical em relação à página ou ao
    parágrafo-âncora; atrás do texto (fundo) ou à frente — no mesmo lugar em todo leitor."""
    from docx.oxml import parse_xml
    from docx.shared import Pt

    run.add_picture(io.BytesIO(png), width=Pt(w), height=Pt(h))
    inline = run._r.xpath(".//wp:inline")[0]
    graphic = inline.xpath("./a:graphic")[0]
    docpr = inline.xpath("./wp:docPr")[0]
    anchor = parse_xml(
        '<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        f'distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="{0 if behind else 2}" '
        f'behindDoc="{1 if behind else 0}" locked="1" '
        'layoutInCell="1" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{round(x * EMU_PER_PT)}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="{v_from}"><wp:posOffset>{round(y * EMU_PER_PT)}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{round(w * EMU_PER_PT)}" cy="{round(h * EMU_PER_PT)}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        "</wp:anchor>"
    )
    anchor.append(docpr)
    anchor.append(
        parse_xml(
            '<wp:cNvGraphicFramePr xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"/>'
        )
    )
    anchor.append(graphic)
    inline.getparent().replace(inline, anchor)


def layout_to_docx(
    pdf: Any, pdoc: Any, style_run_factory: Any
) -> tuple[bytes, dict[str, int], list[str], set[str]]:
    """Monta o .docx em layout exato. `style_run_factory(doc)` devolve (style_run, default_family, default_size)
    — o mesmo estilo de trecho da conversão em texto corrido."""
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_LINE_SPACING
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    from app.docx_engine.pdf_import import _thin_rules

    doc = Document()
    used: set[str] = set()
    all_chunks: list[Chunk] = []
    for i, page in enumerate(pdf.pages):
        chars = [c for c in page.chars if c.get("upright", True)]
        all_chunks.extend(_chunks(chars, i, page.height, _thin_rules(page)))
    for c in all_chunks:
        used |= {s.style[0] for s in c.segs}
    style_run, _, _ = style_run_factory(doc, [s for c in all_chunks for s in c.segs])

    frames = 0
    images = 0
    for i, page in enumerate(pdf.pages):
        section = doc.sections[0] if i == 0 else doc.add_section(WD_SECTION.NEW_PAGE)
        section.page_width, section.page_height = Pt(page.width), Pt(page.height)
        for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            setattr(section, side, Pt(14))
        section.header_distance = section.footer_distance = Pt(0)
        # parágrafo-âncora da página (o fundo fica preso a ele); o 1º parágrafo do documento já existe vazio
        anchor_p = doc.paragraphs[0] if i == 0 and doc.paragraphs else doc.add_paragraph()
        if i == 0 and not doc.paragraphs:
            anchor_p = doc.add_paragraph()
        pf = anchor_p.paragraph_format
        pf.line_spacing_rule, pf.line_spacing = WD_LINE_SPACING.EXACTLY, Pt(1)
        bg = background_png(pdoc[i], page.width, page.height)
        if bg is not None:
            anchor_behind(anchor_p.add_run(), bg, 0, 0, page.width, page.height)
            images += 1
        for c in (c for c in all_chunks if c.page == i):
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = pf.space_after = Pt(0)
            pf.line_spacing_rule, pf.line_spacing = WD_LINE_SPACING.EXACTLY, Pt(round(c.size * 1.18, 1))
            ppr = p._p.get_or_add_pPr()
            fr = OxmlElement("w:framePr")
            width = (c.x1 - c.x0) * 1.04 + 6  # folga: fonte substituta e arredondamentos
            # topo do quadro: a linha de base fica a ~0,92 do tamanho abaixo do topo da linha com entrelinha 1,18
            y = c.base - c.size * 0.95
            for k, v in (
                ("w:w", round(width * 20)),
                ("w:hSpace", 0),
                ("w:vSpace", 0),
                ("w:wrap", "around"),
                ("w:hAnchor", "page"),
                ("w:vAnchor", "page"),
                ("w:x", round((c.x0 - 1) * 20)),
                ("w:y", round(max(0.0, y) * 20)),
            ):
                fr.set(qn(k), str(v))
            ppr.insert(0, fr) if ppr.find(qn("w:pStyle")) is None else ppr.find(qn("w:pStyle")).addnext(fr)
            for seg in c.segs:
                if seg.text:
                    style_run(p.add_run(seg.text), seg.style)
            frames += 1
    out = io.BytesIO()
    doc.save(out)
    stats = {"pages": len(pdf.pages), "frames": frames, "images": images, "paragraphs": frames, "tables": 0}
    warnings = [
        "Documento de layout fixo (boleto, fatura, formulário): convertido em “layout exato” — cada texto no "
        "mesmo lugar do PDF, sobre a página original. Valores muito mais compridos que os do original quebram "
        "dentro do próprio espaço."
    ]
    return out.getvalue(), stats, warnings, used
