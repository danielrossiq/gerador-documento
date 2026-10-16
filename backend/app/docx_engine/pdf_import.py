"""Importação de PDF digitado → .docx editável (o resto do sistema continua trabalhando só com .docx).

Só aceitamos PDFs **digitados** — exportados do Word, Google Docs, LibreOffice ou de um sistema —, em que o
texto existe como texto dentro do arquivo. PDFs **digitalizados** (foto ou escaneamento de papel, com ou
sem camada de OCR) são recusados com uma mensagem clara: reconhecer texto em imagem erra justamente nomes,
CPFs e valores, que são os trechos que viram campos.

Como cada página é classificada (PDFium, via pypdfium2):
  * texto visível suficiente → página digitada (mesmo com papel timbrado/imagem de fundo);
  * pouca ou nenhuma letra visível e grande área coberta por imagem → digitalizada. A camada de OCR que
    scanners e apps (CamScanner, Adobe Scan…) colocam por cima da imagem usa texto *invisível*
    (modo de renderização 3), que por isso não conta como texto digitado;
  * texto transformado em desenho (sem letras, muitos traçados) → ilegível.

Conversão (pdfplumber para caracteres/fontes/tabelas e python-docx para escrever; licenças MIT/BSD/Apache,
sem LibreOffice no container da API):
  * linhas → parágrafos (espaçamento, recuo, alinhamento, lista, "a próxima palavra caberia na linha");
  * negrito/itálico/sublinhado/cor/tamanho por trecho; fonte padrão do documento no estilo Normal;
  * tabelas com bordas (inclusive células mescladas e tabelas que continuam na página seguinte);
  * imagens (logotipos, assinaturas digitalizadas dentro de um PDF digitado);
  * cabeçalho e rodapé = linhas que se repetem no alto/pé das páginas; o número da página vira o campo PAGE;
  * página que termina cedo → quebra de página antes do conteúdo seguinte (ex.: página de assinaturas).

PDF é um formato complexo e o arquivo vem de fora: a conversão roda num processo filho com tempo e
memória limitados (`convert_pdf`), nunca no processo da API.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import math
import multiprocessing
import re
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.docx_engine.safety import DocxRejected

log = get_logger(__name__)

PDF_MAX_PAGES = 40
PDF_TIMEOUT_S = 60
PDF_MEMORY_BYTES = 2 * 1024 * 1024 * 1024

MIN_VISIBLE_CHARS = 20  # abaixo disso a página não tem "texto digitado" de verdade
SCAN_COVERAGE = 0.3  # fração da página coberta por imagem que, sem texto visível, indica digitalização
FULLPAGE_COVERAGE = (
    0.6  # imagem de página inteira: só é fundo/papel timbrado se houver bastante texto por cima
)
FULLPAGE_MIN_CHARS = 150
UNREADABLE_SHARE = 0.05  # glifos sem mapeamento para Unicode ("(cid:12)") acima disso → texto ilegível
TAB_GAP = 2.5  # espaço horizontal (em tamanhos de fonte) que vira tabulação em vez de espaço
HEADER_ZONE = 0.14
FOOTER_ZONE = 0.86

_SLOTS = threading.BoundedSemaphore(2)  # conversões simultâneas por processo da API


@dataclass
class PdfConversion:
    docx: bytes
    stats: dict[str, int]
    warnings: list[str]


# ============================================================================ entrada pública


def convert_pdf(
    data: bytes, *, max_bytes: int, max_pages: int = PDF_MAX_PAGES, isolated: bool = True
) -> PdfConversion:
    """Valida e converte um PDF digitado. Recusas viram `DocxRejected(code, message)` (mesmo contrato do .docx)."""
    if not data:
        raise DocxRejected("EMPTY_FILE", "O arquivo está vazio.")
    if len(data) > max_bytes:
        raise DocxRejected("FILE_TOO_LARGE", f"O arquivo excede o limite de {max_bytes // (1024 * 1024)} MB.")
    if not looks_like_pdf(data):
        raise DocxRejected("NOT_A_PDF", "O arquivo não é um PDF válido.")
    if not isolated:
        return pdf_to_docx(data, max_pages=max_pages)
    return _run_isolated(data, max_pages)


def looks_like_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def _run_isolated(data: bytes, max_pages: int, timeout: int = PDF_TIMEOUT_S) -> PdfConversion:
    mp = multiprocessing.get_context("spawn")
    with _SLOTS:
        recv, send = mp.Pipe(duplex=False)
        proc = mp.Process(target=_child_main, args=(send, data, max_pages, timeout), daemon=True)
        proc.start()
        send.close()
        try:
            if not recv.poll(timeout):
                raise DocxRejected(
                    "PDF_TIMEOUT",
                    "O PDF demorou demais para ser lido. Envie o documento em Word (.docx) ou um PDF menor.",
                )
            status, payload = recv.recv()
        except EOFError as exc:  # processo filho morreu (ex.: limite de memória)
            raise DocxRejected(
                "PDF_CONVERSION_FAILED",
                "Não foi possível ler este PDF. Envie o documento em Word (.docx).",
            ) from exc
        finally:
            recv.close()
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)
    if status == "ok":
        return PdfConversion(**payload)
    if status == "rejected":
        raise DocxRejected(*payload)
    # só o tipo da exceção: a mensagem pode trazer trechos do PDF (conteúdo do cliente)
    log.error("pdf_conversao_falhou", extra={"error_type": str(payload)[:80]})
    raise DocxRejected(
        "PDF_CONVERSION_FAILED", "Não foi possível converter este PDF. Envie o documento em Word (.docx)."
    )


def _child_main(
    conn: Any, data: bytes, max_pages: int, timeout: int
) -> None:  # pragma: no cover - subprocesso
    try:
        _limit_resources(timeout)
        conv = pdf_to_docx(data, max_pages=max_pages)
        conn.send(("ok", {"docx": conv.docx, "stats": conv.stats, "warnings": conv.warnings}))
    except DocxRejected as exc:
        conn.send(("rejected", (exc.code, exc.message)))
    except BaseException as exc:
        conn.send(("error", type(exc).__name__))  # nunca a mensagem: pode conter texto do documento
    finally:
        conn.close()


def _limit_resources(timeout: int) -> None:  # pragma: no cover - só Linux
    if sys.platform == "win32":  # desenvolvimento no Windows: sem limites de SO
        return
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (PDF_MEMORY_BYTES, PDF_MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5))


# ============================================================================ modelo intermediário

Style = tuple[str, float, bool, bool, bool, str | None]  # família, tamanho, negrito, itálico, sublinhado, cor


@dataclass
class Seg:
    text: str
    style: Style
    field: str | None = None  # "PAGE" | "NUMPAGES"


@dataclass
class Line:
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    base: float
    size: float
    segs: list[Seg]
    first_word: float  # largura da primeira palavra (decide se ela caberia no fim da linha anterior)
    second_x: float  # onde começa a 2ª palavra (texto de um item "a) ..." com recuo deslocado)
    first_gap: float = 0.0  # espaço entre a 1ª e a 2ª palavra (marcador de lista seguido de tabulação)
    tabs: list[float] = field(default_factory=list)  # x onde recomeça o texto depois de cada tabulação

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.segs)


@dataclass
class ImageItem:
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    png: bytes
    gap_before: float = 0.0
    page_break: bool = False


@dataclass
class Cell:
    r0: int
    r1: int
    c0: int
    c1: int
    lines: list[Line] = field(default_factory=list)
    images: list[ImageItem] = field(default_factory=list)


@dataclass
class TableItem:
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    cols: list[float]
    rows: list[float]
    cells: list[Cell]
    gap_before: float = 0.0
    page_break: bool = False


@dataclass
class Para:
    lines: list[Line]
    gap_before: float = 0.0
    page_break: bool = False
    top_of_page: bool = False  # começou no alto de uma página por fluxo natural (espaço antes não é medível)


@dataclass
class Metrics:
    left: float
    right: float
    ratio: float  # distância entre linhas de um parágrafo / tamanho da fonte


# ============================================================================ texto e estilo

_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st", "­": ""}
_KNOWN_FONTS = {
    "timesnewroman": "Times New Roman",
    "times": "Times New Roman",
    "timesroman": "Times New Roman",
    "tinos": "Times New Roman",
    "liberationserif": "Times New Roman",
    "arial": "Arial",
    "helvetica": "Arial",
    "arimo": "Arial",
    "liberationsans": "Arial",
    "arialnarrow": "Arial Narrow",
    "couriernew": "Courier New",
    "courier": "Courier New",
    "cousine": "Courier New",
    "liberationmono": "Courier New",
    "calibri": "Calibri",
    "carlito": "Calibri",
    "cambria": "Cambria",
    "caladea": "Cambria",
    "segoeui": "Segoe UI",
    "trebuchetms": "Trebuchet MS",
    "bookantiqua": "Book Antiqua",
    "centurygothic": "Century Gothic",
    "palatinolinotype": "Palatino Linotype",
}
_LIST_START = re.compile(
    r"^\s*(?:[•●▪◦■□➢►–—-]\s|\d{1,3}(?:\.\d{1,3})*[.)]\s|[a-zA-Z][.)]\s|[IVXLC]{1,6}\s*[.)–-]\s|§)"
)


def _clean(text: str) -> tuple[str, bool]:
    """Texto do glifo pronto para o Word; o segundo valor diz se o glifo era ilegível."""
    if text.startswith("(cid:") or text == "�":
        return "", True
    if (
        len(text) == 1 and 0xE000 <= ord(text) <= 0xF8FF
    ):  # fontes de símbolo (Wingdings…) usadas como marcador
        return "•", False
    return _LIGATURES.get(text, text), False


def _font_info(fontname: str) -> tuple[str, bool, bool]:
    name = (fontname or "").split("+", 1)[-1]
    low = name.lower()
    bold = any(k in low for k in ("bold", "black", "heavy", "semibold", "demibold", "extrabold"))
    italic = "italic" in low or "oblique" in low or bool(re.search(r"[-,](it|bi|boldit)$", low))
    base = re.split(r"[-,]", name)[0]
    base = re.sub(r"(PSMT|PS|MT)$", "", base)
    key = re.sub(r"[^a-z]", "", base.lower())
    family = _KNOWN_FONTS.get(key) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base).strip() or "Arial"
    return family, bold, italic


def _color_hex(color: Any) -> str | None:
    if not isinstance(color, (tuple, list)) or not color:
        return None
    try:
        vals = [min(1.0, max(0.0, float(v))) for v in color]
    except (TypeError, ValueError):
        return None
    if len(vals) == 1:
        r = g = b = vals[0]
    elif len(vals) == 3:
        r, g, b = vals
    elif len(vals) == 4:
        c, m, y, k = vals
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return None
    if max(r, g, b) < 0.2:  # preto/quase preto: cor automática do Word
        return None
    return f"{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


# ============================================================================ páginas → linhas


def _baseline(ch: dict[str, Any], page_height: float) -> float:
    m = ch.get("matrix")
    return page_height - m[5] if m else ch["bottom"]


def _thin_rules(page: Any) -> list[tuple[float, float, float]]:
    """Traços horizontais finos (candidatos a sublinhado): (x0, x1, y)."""
    rules = []
    for obj in list(page.lines) + list(page.rects):
        if abs(obj["bottom"] - obj["top"]) <= 1.5 and obj["x1"] - obj["x0"] >= 2:
            rules.append((obj["x0"], obj["x1"], (obj["top"] + obj["bottom"]) / 2))
    return rules if len(rules) <= 500 else []


def _build_lines(
    chars: list[dict[str, Any]], page_no: int, page_height: float, rules: list[tuple[float, float, float]]
) -> tuple[list[Line], int]:
    """Agrupa caracteres por linha de base e monta os trechos com estilo. Devolve (linhas, glifos ilegíveis)."""
    unreadable = 0
    items = []
    for ch in chars:
        text, bad = _clean(ch.get("text") or "")
        unreadable += bad
        items.append((ch, text, _baseline(ch, page_height)))
    items.sort(key=lambda t: (round(t[2], 1), t[0]["x0"]))
    groups: list[list[tuple[dict[str, Any], str, float]]] = []
    for it in items:
        if groups and abs(it[2] - groups[-1][0][2]) <= max(1.5, 0.25 * it[0]["size"]):
            groups[-1].append(it)
        else:
            groups.append([it])
    lines = []
    for g in groups:
        g.sort(key=lambda t: t[0]["x0"])
        line = _line_from_chars(g, page_no, rules)
        if line is not None:
            lines.append(line)
    lines.sort(key=lambda ln: ln.base)
    return lines, unreadable


def _line_from_chars(
    group: list[tuple[dict[str, Any], str, float]], page_no: int, rules: list[tuple[float, float, float]]
) -> Line | None:
    visible = [(ch, t, b) for ch, t, b in group if t.strip()]
    if not visible:
        return None
    sizes = Counter(round(ch["size"] * 2) / 2 for ch, _, _ in visible)
    size = sizes.most_common(1)[0][0]
    base = visible[0][2]
    segs: list[Seg] = []
    prev: dict[str, Any] | None = None
    pending_space = False
    first_word_end: float | None = None
    second_x: float | None = None
    tabs: list[float] = []

    def push(text: str, style: Style) -> None:
        if segs and segs[-1].style == style:
            segs[-1].text += text
        else:
            segs.append(Seg(text, style))

    for ch, text, b in group:
        if not text.strip():
            pending_space = pending_space or prev is not None
            continue
        family, bold, italic = _font_info(ch.get("fontname", ""))
        cx = (ch["x0"] + ch["x1"]) / 2
        underline = any(
            r0 - 1 <= cx <= r1 + 1 and b - 0.5 <= y <= b + 0.25 * ch["size"] + 1.5 for r0, r1, y in rules
        )
        style: Style = (
            family,
            round(ch["size"] * 2) / 2,
            bold,
            italic,
            underline,
            _color_hex(ch.get("non_stroking_color")),
        )
        if prev is not None:
            gap = ch["x0"] - prev["x1"]
            sep = ""
            if gap > TAB_GAP * size:
                sep = "\t"
            elif pending_space or gap > 0.18 * size:
                sep = " "
            if sep:
                if first_word_end is None:
                    first_word_end, second_x = prev["x1"], ch["x0"]
                if sep == "\t":
                    tabs.append(ch["x0"])
                prev_style = segs[-1].style if segs else style
                # espaço herda o estilo do texto anterior, mas nunca sublinhado (evita "traço" entre palavras)
                push(sep, (*prev_style[:4], prev_style[4] and style[4], prev_style[5]))
        push(text, style)
        prev = ch
        pending_space = False
    x0 = visible[0][0]["x0"]
    x1 = max(ch["x1"] for ch, _, _ in visible)
    return Line(
        page=page_no,
        x0=x0,
        x1=x1,
        top=min(ch["top"] for ch, _, _ in visible),
        bottom=max(ch["bottom"] for ch, _, _ in visible),
        base=base,
        size=size,
        segs=segs,
        first_word=(first_word_end if first_word_end is not None else x1) - x0,
        second_x=second_x if second_x is not None else x0,
        first_gap=(second_x - first_word_end) if second_x is not None and first_word_end is not None else 0.0,
        tabs=tabs,
    )


# ============================================================================ linhas → parágrafos


def _line_ratio(pages_lines: list[list[Line]]) -> float:
    """Distância típica entre linhas de um mesmo parágrafo, em múltiplos do tamanho da fonte."""
    values = []
    for lines in pages_lines:
        for a, b in itertools.pairwise(lines):
            if abs(a.size - b.size) <= 0.5 and a.size > 0:
                r = (b.base - a.base) / a.size
                if 1.0 <= r <= 2.2:
                    values.append(round(r, 2))
    if not values:
        return 1.2
    return Counter(values).most_common(1)[0][0]


def _align_class(ln: Line, m: Metrics) -> str:
    width = m.right - m.left
    center = (m.left + m.right) / 2
    if (
        ln.x0 > m.left + 12
        and ln.x1 < m.right - 8
        and abs((ln.x0 + ln.x1) / 2 - center) <= max(4, 0.02 * width)
    ):
        return "center"
    if abs(ln.x1 - m.right) <= 4 and ln.x0 > m.left + 0.25 * width:
        return "right"
    return "left"


def _is_list_start(text: str) -> bool:
    return bool(_LIST_START.match(text))


def _breaks(a: Line, b: Line, para: list[Line], m: Metrics, *, check_gap: bool = True) -> bool:
    """Decide se `b` começa um parágrafo novo depois de `a` (quebrar a mais é inofensivo; juntar demais não)."""
    if check_gap and b.base - a.base > a.size * m.ratio * 1.35 + 1:
        return True
    if abs(b.size - a.size) > 1.0:
        return True
    head = para[0]
    if _is_list_start(head.text.replace("\t", " ")) and abs(b.x0 - head.second_x) <= 3 and head.x0 < b.x0:
        # continuação de um item "a) texto…" alinhada ao texto do item (recuo deslocado)
        return "\t" in b.text or m.right - a.x1 > b.first_word + 0.3 * b.size + 2
    if "\t" in a.text or "\t" in b.text:  # linhas com colunas (assinaturas, "Nome:\tCPF:") são diagramação
        return True
    ca, cb = _align_class(a, m), _align_class(b, m)
    if ca != cb:
        return True
    if ca != "left":
        return False
    if (
        m.right - a.x1 > b.first_word + 0.3 * b.size + 2
    ):  # a próxima palavra caberia: a linha terminou de propósito
        return True
    if _is_list_start(b.text) and re.search(r"[.:;]$", a.text.rstrip()):
        return True
    first = a is para[0]
    if b.x0 > a.x0 + 6 and not (first and _is_list_start(a.text)):
        return True  # recuo aumentou: parágrafo novo (ou item com recuo)
    return b.x0 < a.x0 - 6 and not first  # recuo diminuiu depois da 1ª linha: fim do item


def _join_lines(lines: list[Line]) -> list[Seg]:
    segs: list[Seg] = []
    for i, ln in enumerate(lines):
        if i:
            prev_text = segs[-1].text if segs else ""
            if not prev_text.endswith(("-", "\t", " ")):
                style = segs[-1].style if segs else ln.segs[0].style
                segs.append(Seg(" ", (*style[:4], False, style[5])))
        for s in ln.segs:
            if segs and segs[-1].style == s.style and not segs[-1].field and not s.field:
                segs[-1] = Seg(segs[-1].text + s.text, s.style)
            else:
                segs.append(Seg(s.text, s.style, s.field))
    return segs


def _marker_tab(segs: list[Seg]) -> None:
    """Troca o separador logo depois do marcador ("a)", "1.", "•") por tabulação."""
    for s in segs:
        if s.field:
            return
        m = re.search(r"[ \t]", s.text.lstrip())
        if m:
            i = len(s.text) - len(s.text.lstrip()) + m.start()
            s.text = s.text[:i] + "\t" + s.text[i + 1 :]
            return


# ============================================================================ tabelas e imagens


def _cluster(values: list[float], tol: float = 2.0) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def _index(bounds: list[float], v: float) -> int:
    return min(range(len(bounds)), key=lambda i: abs(bounds[i] - v))


def _tables(page: Any) -> list[TableItem]:
    out = []
    area = page.width * page.height
    for t in page.find_tables():
        x0, top, x1, bottom = t.bbox
        cells = [c for c in t.cells if c]
        if not cells:
            continue
        if len(cells) == 1 and (x1 - x0) * (bottom - top) > 0.5 * area:
            continue  # moldura da página, não tabela
        cols = _cluster([c[0] for c in cells] + [c[2] for c in cells])
        rows = _cluster([c[1] for c in cells] + [c[3] for c in cells])
        if len(cols) < 2 or len(rows) < 2:
            continue
        specs = []
        for cx0, ctop, cx1, cbottom in cells:
            c0, c1 = _index(cols, cx0), _index(cols, cx1)
            r0, r1 = _index(rows, ctop), _index(rows, cbottom)
            if c1 > c0 and r1 > r0:
                specs.append(Cell(r0, r1, c0, c1))
        out.append(TableItem(page.page_number - 1, x0, x1, top, bottom, cols, rows, specs))
    return out


def _cell_at(table: TableItem, x: float, y: float) -> Cell | None:
    for c in table.cells:
        if table.cols[c.c0] <= x <= table.cols[c.c1] and table.rows[c.r0] <= y <= table.rows[c.r1]:
            return c
    return None


def _images(ppage: Any, page_no: int, width: float, height: float, warnings: set[str]) -> list[ImageItem]:
    import pypdfium2.raw as pdfium_c

    out = []
    for obj in ppage.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=0):
        left, bottom, right, top = obj.get_bounds()
        x0, x1 = max(0.0, left), min(width, right)
        t, b = max(0.0, height - top), min(height, height - bottom)
        if x1 - x0 < 6 or b - t < 6:
            continue
        if (x1 - x0) * (b - t) > FULLPAGE_COVERAGE * width * height:
            warnings.add("A imagem de fundo das páginas (papel timbrado ou marca d'água) não foi importada.")
            continue
        try:
            pil = obj.get_bitmap(render=True).to_pil()
        except Exception:  # imagem num formato que o PDFium não rasteriza: recorta a página renderizada
            pil = ppage.render(scale=2, crop=(x0, height - b, width - x1, t)).to_pil()
        buf = io.BytesIO()
        pil.convert("RGBA" if pil.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "PNG", optimize=True)
        out.append(ImageItem(page_no, x0, x1, t, b, buf.getvalue()))
    return out


# ============================================================================ classificação (digitado × digitalizado)


def _classify(plumber_page: Any, pdfium_page: Any) -> tuple[str, int]:
    """("text" | "scanned" | "outlined" | "blank", letras visíveis estimadas)."""
    import pypdfium2.raw as pdfium_c

    visible_objs = invisible_objs = paths = 0
    for obj in pdfium_page.get_objects(
        filter=[pdfium_c.FPDF_PAGEOBJ_TEXT, pdfium_c.FPDF_PAGEOBJ_PATH], max_depth=4
    ):
        if obj.type == pdfium_c.FPDF_PAGEOBJ_PATH:
            paths += 1
        elif pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw) == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
            invisible_objs += 1
        else:
            visible_objs += 1
    chars = sum(1 for ch in plumber_page.chars if (ch.get("text") or "").strip())
    total_objs = visible_objs + invisible_objs
    visible = round(chars * (visible_objs / total_objs)) if total_objs else 0
    area = plumber_page.width * plumber_page.height
    covered = 0.0
    for im in plumber_page.images:
        w = max(0.0, min(plumber_page.width, im["x1"]) - max(0.0, im["x0"]))
        h = max(0.0, min(plumber_page.height, im["bottom"]) - max(0.0, im["top"]))
        covered += w * h
    coverage = min(1.0, covered / area) if area else 0.0
    if coverage >= FULLPAGE_COVERAGE and visible < FULLPAGE_MIN_CHARS:
        return "scanned", visible
    if visible >= MIN_VISIBLE_CHARS:
        return "text", visible
    if coverage >= SCAN_COVERAGE or (chars >= MIN_VISIBLE_CHARS and invisible_objs > visible_objs):
        return "scanned", visible
    if chars == 0 and paths > 200:
        return "outlined", visible
    if chars == 0 and coverage == 0:
        return "blank", visible
    return "text", visible


def _pages_label(pages: list[int]) -> str:
    nums = [str(p + 1) for p in pages]
    if len(nums) == 1:
        return f"A página {nums[0]} é uma imagem digitalizada"
    return f"As páginas {', '.join(nums[:-1])} e {nums[-1]} são imagens digitalizadas"


# ============================================================================ conversão


def pdf_to_docx(data: bytes, *, max_pages: int = PDF_MAX_PAGES) -> PdfConversion:
    import pdfplumber
    import pypdfium2 as pdfium

    try:
        pdoc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise DocxRejected(
                "ENCRYPTED", "PDFs protegidos por senha não são aceitos. Remova a senha e envie de novo."
            ) from exc
        raise DocxRejected("NOT_A_PDF", "O arquivo está corrompido ou não é um PDF válido.") from exc
    try:
        n = len(pdoc)
        if n == 0:
            raise DocxRejected("EMPTY_DOCUMENT", "O PDF não tem páginas.")
        if n > max_pages:
            raise DocxRejected(
                "PDF_TOO_MANY_PAGES",
                f"O PDF tem {n} páginas; o limite para conversão é {max_pages}. Envie o documento em Word (.docx).",
            )
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return _convert(pdf, pdoc)
    finally:
        pdoc.close()


def _convert(pdf: Any, pdoc: Any) -> PdfConversion:
    pages = pdf.pages
    n = len(pages)
    kinds = [_classify(pages[i], pdoc[i]) for i in range(n)]
    scanned = [i for i, (k, _) in enumerate(kinds) if k == "scanned"]
    if scanned:
        if len(scanned) == n:
            msg = (
                "Este PDF é digitalizado (foto ou escaneamento de papel) e não pode virar modelo. Envie o PDF "
                "gerado direto pelo Word/Google Docs (Arquivo → Salvar/Baixar como PDF) ou o próprio .docx."
            )
        else:
            which = "essa página" if len(scanned) == 1 else "essas páginas"
            msg = (
                f"{_pages_label(scanned)}. Só aceitamos PDFs digitados: remova {which} ou envie o "
                "documento em Word (.docx)."
            )
        raise DocxRejected("PDF_SCANNED", msg)
    if not any(k == "text" for k, _ in kinds):
        if any(k == "outlined" for k, _ in kinds):
            raise DocxRejected(
                "PDF_TEXT_UNREADABLE",
                "O texto deste PDF foi transformado em desenho e não pode ser editado. Envie o documento em Word (.docx).",
            )
        raise DocxRejected("EMPTY_DOCUMENT", "O PDF não tem texto para transformar em modelo.")

    warnings: set[str] = set()
    all_lines: list[list[Line]] = []
    tables: list[list[TableItem]] = []
    images: list[list[ImageItem]] = []
    unreadable = total_chars = rotated = curves = 0
    sizes = {(round(p.width), round(p.height)) for p in pages}
    for i, page in enumerate(pages):
        page_tables = _tables(page)
        page_images = _images(pdoc[i], i, page.width, page.height, warnings)
        in_table: list[dict[str, Any]] = []
        free: list[dict[str, Any]] = []
        for ch in page.chars:
            if not ch.get("upright", True):
                rotated += 1
                continue
            cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2
            owner = next((t for t in page_tables if t.x0 <= cx <= t.x1 and t.top <= cy <= t.bottom), None)
            (in_table if owner else free).append(ch)
        total_chars += len(page.chars)
        lines, bad = _build_lines(free, i, page.height, _thin_rules(page))
        unreadable += bad
        for t in page_tables:
            for c in t.cells:
                x0, x1 = t.cols[c.c0], t.cols[c.c1]
                top, bottom = t.rows[c.r0], t.rows[c.r1]
                mine = [
                    ch
                    for ch in in_table
                    if x0 <= (ch["x0"] + ch["x1"]) / 2 <= x1
                    and top <= (ch["top"] + ch["bottom"]) / 2 <= bottom
                ]
                c.lines, bad = _build_lines(mine, i, page.height, [])
                unreadable += bad
        loose = []
        for im in page_images:
            cx, cy = (im.x0 + im.x1) / 2, (im.top + im.bottom) / 2
            host = next((t for t in page_tables if t.x0 <= cx <= t.x1 and t.top <= cy <= t.bottom), None)
            cell = _cell_at(host, cx, cy) if host else None
            if cell is not None:
                cell.images.append(im)
            else:
                loose.append(im)
        curves += len(page.curves)
        all_lines.append(lines)
        tables.append(page_tables)
        images.append(loose)

    if total_chars and unreadable / total_chars > UNREADABLE_SHARE:
        raise DocxRejected(
            "PDF_TEXT_UNREADABLE",
            "O texto deste PDF usa fontes sem mapeamento de caracteres e sairia embaralhado. "
            "Exporte o PDF de novo pelo Word/Google Docs ou envie o documento em Word (.docx).",
        )
    if rotated:
        warnings.add("Textos na vertical (ex.: na margem) foram ignorados.")
    if curves > 20:
        warnings.add("Desenhos vetoriais (ex.: logotipos desenhados ou gráficos) não foram importados.")
    if len(sizes) > 1:
        warnings.add("O PDF mistura tamanhos de página; usamos o tamanho da primeira.")

    header, footer = _split_header_footer(all_lines, images, pages)

    metrics = _margins(all_lines, pages[0].width)

    flow = _build_flow(all_lines, tables, images, pages, metrics, footer)
    docx = _write_docx(flow, header, footer, pages, metrics, all_lines)
    stats = {
        "pages": n,
        "paragraphs": sum(1 for f in flow if isinstance(f, Para)),
        "tables": sum(1 for f in flow if isinstance(f, TableItem)),
        "images": sum(1 for f in flow if isinstance(f, ImageItem)),
        "header": int(bool(header)),
        "footer": int(bool(footer)),
    }
    return PdfConversion(
        docx=docx,
        stats=stats,
        warnings=[
            "Documento convertido de PDF: confira fontes, espaçamentos e quebras de página antes de gerar.",
            *sorted(warnings),
        ],
    )


def _margins(all_lines: list[list[Line]], page_width: float) -> Metrics:
    """Margem esquerda = onde a maioria das linhas começa; direita = fim da linha mais longa que começa nela.

    A direita ganha 1,5pt de folga: uma linha que no original terminava rente à margem não pode quebrar antes
    por arredondamento (e 1,5pt é menos que um espaço, então nenhuma palavra a mais passa a caber).
    """
    body = [ln for lines in all_lines for ln in lines]
    if not body:
        return Metrics(72.0, page_width - 72.0, 1.2)
    mode = Counter(round(ln.x0) for ln in body).most_common(1)[0][0]
    left = min(ln.x0 for ln in body if abs(ln.x0 - mode) <= 2)
    ends = sorted((ln.x1 for ln in body if abs(ln.x0 - left) <= 2 and ln.x1 < page_width - 18), reverse=True)
    right = (ends[0] if ends else max(ln.x1 for ln in body)) + 1.5
    return Metrics(left=left, right=min(right, page_width - 18), ratio=_line_ratio(all_lines))


# ============================================================================ cabeçalho e rodapé


def _signature(ln: Line, zone: str) -> tuple[str, int, str]:
    return (zone, round(ln.top / 4), re.sub(r"\d+", "#", ln.text).strip())


def _split_header_footer(
    all_lines: list[list[Line]], images: list[list[ImageItem]], pages: list[Any]
) -> tuple[list[Line | ImageItem], list[Line | ImageItem]]:
    """Linhas/imagens que se repetem no alto ou no pé de (quase) todas as páginas saem do corpo."""
    n = len(pages)
    if n < 2:
        return [], []
    need = max(2, math.ceil(0.5 * n))
    counts: Counter[tuple[str, int, str]] = Counter()
    for i, lines in enumerate(all_lines):
        h = pages[i].height
        seen = set()
        for ln in lines:
            zone = "header" if ln.bottom < h * HEADER_ZONE else "footer" if ln.top > h * FOOTER_ZONE else None
            if zone:
                seen.add(_signature(ln, zone))
        counts.update(seen)
    repeated = {s for s, c in counts.items() if c >= need}

    def img_sig(im: ImageItem, h: float) -> tuple[str, int, int, int, int] | None:
        zone = (
            "header" if im.bottom < h * HEADER_ZONE * 1.3 else "footer" if im.top > h * FOOTER_ZONE else None
        )
        if zone is None:
            return None
        return (
            zone,
            round(im.x0 / 4),
            round(im.top / 4),
            round((im.x1 - im.x0) / 4),
            round((im.bottom - im.top) / 4),
        )

    img_counts: Counter[tuple[str, int, int, int, int]] = Counter()
    for i, imgs in enumerate(images):
        img_counts.update({s for im in imgs if (s := img_sig(im, pages[i].height))})
    repeated_imgs = {s for s, c in img_counts.items() if c >= need}

    header: list[Line | ImageItem] = []
    footer: list[Line | ImageItem] = []
    per_sig_lines: dict[tuple[str, int, str], list[Line]] = {}
    placed_imgs: set[tuple[str, int, int, int, int]] = set()
    for i, lines in enumerate(all_lines):
        h = pages[i].height
        keep = []
        for ln in lines:
            zone = "header" if ln.bottom < h * HEADER_ZONE else "footer" if ln.top > h * FOOTER_ZONE else None
            sig = _signature(ln, zone) if zone else None
            if sig and sig in repeated:
                per_sig_lines.setdefault(sig, []).append(ln)
            else:
                keep.append(ln)
        all_lines[i] = keep
        keep_i = []
        for im in images[i]:
            s = img_sig(im, h)
            if s is None or s not in repeated_imgs:
                keep_i.append(im)
            elif s not in placed_imgs:  # a mesma imagem de todas as páginas entra uma vez só
                placed_imgs.add(s)
                (header if s[0] == "header" else footer).append(im)
        images[i] = keep_i

    for sig, lns in per_sig_lines.items():
        first = lns[0]
        _page_number_fields(first, lns, n)
        (header if sig[0] == "header" else footer).append(first)
    header.sort(key=lambda x: x.top)
    footer.sort(key=lambda x: x.top)
    return header, footer


def _page_number_fields(first: Line, occurrences: list[Line], total: int) -> None:
    """Número que acompanha a página ("Página 2 de 5") vira os campos PAGE/NUMPAGES do Word."""
    token_values: list[list[str]] = [re.findall(r"\d+", ln.text) for ln in occurrences]
    if not token_values or not token_values[0] or len({len(v) for v in token_values}) != 1:
        return
    kinds: dict[int, str] = {}
    for k in range(len(token_values[0])):
        vals = [v[k] for v in token_values]
        if (
            all(val == str(ln.page + 1) for val, ln in zip(vals, occurrences, strict=True))
            and len(set(vals)) > 1
        ):
            kinds[k] = "PAGE"
        elif all(val == str(total) for val in vals) and total > 1 and len(occurrences) > 1:
            kinds[k] = "NUMPAGES"
    if not kinds:
        return
    new: list[Seg] = []
    k = 0
    for s in first.segs:
        parts = re.split(r"(\d+)", s.text)
        for part in parts:
            if not part:
                continue
            if part.isdigit():
                kind = kinds.get(k)
                k += 1
                new.append(Seg(part, s.style, kind))
            elif new and new[-1].style == s.style and not new[-1].field:
                new[-1].text += part
            else:
                new.append(Seg(part, s.style))
    first.segs = new


# ============================================================================ fluxo do corpo


def _build_flow(
    all_lines: list[list[Line]],
    tables: list[list[TableItem]],
    images: list[list[ImageItem]],
    pages: list[Any],
    m: Metrics,
    footer: list[Line | ImageItem],
) -> list[Para | TableItem | ImageItem]:
    flow: list[Para | TableItem | ImageItem] = []
    prev: Line | TableItem | ImageItem | None = None
    page_items: list[list[Line | TableItem | ImageItem]] = [
        [*all_lines[i], *tables[i], *images[i]] for i in range(len(pages))
    ]
    all_bottoms = [it.bottom for items in page_items for it in items]
    footer_top = min((f.top for f in footer), default=None)
    bottom_limit = max(
        max(all_bottoms, default=0.0),
        (footer_top - 36) if footer_top else pages[0].height - 72,
    )
    top_margin = min(
        (min((it.top for it in items), default=1e9) for items in page_items),
        default=72.0,
    )

    for i in range(len(pages)):
        items: list[Line | TableItem | ImageItem] = sorted(
            [*all_lines[i], *tables[i], *images[i]], key=lambda x: x.top
        )
        for j, it in enumerate(items):
            first_on_page = j == 0
            page_break = False
            if first_on_page and prev is not None:
                need = (
                    (it.bottom - it.top) if not isinstance(it, TableItem) else min(40.0, it.bottom - it.top)
                )
                page_break = bottom_limit - prev.bottom > need + 2 * _size_of(prev) * m.ratio
            if isinstance(it, Line):
                cur = flow[-1] if flow and isinstance(flow[-1], Para) else None
                if cur is not None and isinstance(prev, Line) and not page_break:
                    same_page = not first_on_page
                    if not _breaks(prev, it, cur.lines, m, check_gap=same_page):
                        cur.lines.append(it)
                        prev = it
                        continue
                gap = _gap(prev, it, m) if prev is not None and not first_on_page else 0.0
                if prev is None:
                    gap = max(0.0, it.top - top_margin)
                natural_top = first_on_page and prev is not None and not page_break
                flow.append(Para([it], gap_before=gap, page_break=page_break, top_of_page=natural_top))
            elif isinstance(it, TableItem):
                last = flow[-1] if flow else None
                if (
                    first_on_page
                    and isinstance(last, TableItem)
                    and isinstance(prev, TableItem)
                    and len(last.cols) == len(it.cols)
                    and all(abs(a - b) <= 2 for a, b in zip(last.cols, it.cols, strict=True))
                ):
                    _append_rows(last, it)
                else:
                    it.gap_before = _gap(prev, it, m) if prev is not None and not first_on_page else 0.0
                    it.page_break = page_break
                    flow.append(it)
            else:
                it.gap_before = _gap(prev, it, m) if prev is not None and not first_on_page else 0.0
                it.page_break = page_break
                flow.append(it)
            prev = it
    # parágrafo que abriu uma página por falta de espaço tinha o espaçamento normal do documento antes dele
    gaps = Counter(round(p.gap_before) for p in flow if isinstance(p, Para) and p.gap_before >= 2)
    if gaps:
        typical = float(gaps.most_common(1)[0][0])
        for p in flow:
            if isinstance(p, Para) and p.top_of_page:
                p.gap_before = typical
    return flow


def _size_of(it: Line | TableItem | ImageItem) -> float:
    return it.size if isinstance(it, Line) else 11.0


def _gap(prev: Line | TableItem | ImageItem | None, it: Line | TableItem | ImageItem, m: Metrics) -> float:
    if prev is None:
        return 0.0
    raw = it.top - prev.bottom
    if isinstance(prev, Line) and isinstance(it, Line):
        raw -= prev.size * m.ratio - prev.size
    else:
        raw -= 2
    return max(0.0, min(72.0, raw))


def _row_text(t: TableItem, r: int) -> str:
    return "|".join(
        " ".join(ln.text for ln in c.lines) for c in sorted(t.cells, key=lambda c: c.c0) if c.r0 == r
    )


def _append_rows(dest: TableItem, src: TableItem) -> None:
    """Tabela que continua na página seguinte: junta as linhas (sem repetir o cabeçalho repetido)."""
    skip_first = _row_text(src, 0) == _row_text(dest, 0) and _row_text(src, 0).strip() != ""
    offset = len(dest.rows) - 1
    shift = -1 if skip_first else 0
    for c in src.cells:
        if skip_first and c.r0 == 0:
            continue
        dest.cells.append(Cell(c.r0 + offset + shift, c.r1 + offset + shift, c.c0, c.c1, c.lines, c.images))
    start = src.rows[1] if skip_first else src.rows[0]
    extra = src.rows[2:] if skip_first else src.rows[1:]
    dest.rows = dest.rows + [dest.rows[-1] + (r - start) for r in extra]


# ============================================================================ escrita do .docx


def _para_format(lines: list[Line], left: float, right: float, m: Metrics) -> dict[str, Any]:
    sub = Metrics(left, right, m.ratio)
    classes = [_align_class(ln, sub) for ln in lines]
    fmt: dict[str, Any] = {"align": "left", "left": 0.0, "first": 0.0}
    if all(c == "center" for c in classes):
        fmt["align"] = "center"
        return fmt
    if all(c == "right" for c in classes):
        fmt["align"] = "right"
        return fmt
    # justificado: todas as linhas (menos a última) terminam na margem direita — com uma linha só isso pode ser
    # coincidência de um texto alinhado à esquerda, então exige ao menos duas
    if len(lines) >= 3 and all(abs(ln.x1 - right) <= 2.5 for ln in lines[:-1]):
        fmt["align"] = "justify"
    head = lines[0]
    base = min(ln.x0 for ln in lines[1:]) if len(lines) >= 2 else head.x0
    if len(lines) >= 2:
        fmt["left"] = max(0.0, base - left)
        fmt["first"] = head.x0 - base
    else:
        fmt["left"] = max(0.0, head.x0 - left)
    # item "a)  texto…": recuo deslocado e tabulação depois do marcador, como o Word faz em listas
    if _is_list_start(head.text.replace("\t", " ")) and head.second_x > head.x0 + 2:
        aligned = len(lines) >= 2 and abs(base - head.second_x) <= 3
        if aligned or head.first_gap > 0.45 * head.size:
            fmt["left"] = head.second_x - left
            fmt["first"] = head.x0 - head.second_x
            fmt["marker_tab"] = True
    fmt["tabs"] = sorted({round(x - left, 1) for ln in lines for x in ln.tabs if x - left > 1})
    return fmt


def _write_docx(
    flow: list[Para | TableItem | ImageItem],
    header: list[Line | ImageItem],
    footer: list[Line | ImageItem],
    pages: list[Any],
    m: Metrics,
    all_lines: list[list[Line]],
) -> bytes:
    from docx import Document
    from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    doc = Document()

    # estilo Normal = fonte/tamanho mais comuns do corpo; os trechos só sobrescrevem o que difere
    counter: Counter[tuple[str, float]] = Counter()
    for lines in all_lines:
        for ln in lines:
            for s in ln.segs:
                counter[(s.style[0], s.style[1])] += len(s.text)
    for it in flow:
        if isinstance(it, Para):
            for ln in it.lines:
                for s in ln.segs:
                    counter[(s.style[0], s.style[1])] += len(s.text)
    default_family, default_size = counter.most_common(1)[0][0] if counter else ("Arial", 11.0)
    normal = doc.styles["Normal"]
    normal.font.name = default_family
    normal.font.size = Pt(default_size)
    rfonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), default_family)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.0

    first = pages[0]
    section = doc.sections[0]
    section.page_width = Pt(first.width)
    section.page_height = Pt(first.height)
    header_bottom = max((h.bottom for h in header), default=None)
    footer_top = min((f.top for f in footer), default=None)
    body_tops = [it.top for lines in all_lines for it in lines]
    top_margin = min(body_tops, default=72.0) - 2
    if header_bottom is not None:
        top_margin = max(top_margin, header_bottom + 6)
        section.header_distance = Pt(max(18.0, min(h.top for h in header) - 2))
    if footer_top is not None:
        bottom_margin = first.height - footer_top + 6
        section.footer_distance = Pt(max(18.0, first.height - max(f.bottom for f in footer) - 2))
    else:
        body_bottom = max((ln.bottom for lines in all_lines for ln in lines), default=first.height - 72)
        bottom_margin = min(72.0, first.height - body_bottom)
    section.top_margin = Pt(max(28.0, min(144.0, top_margin)))
    section.bottom_margin = Pt(max(28.0, min(144.0, bottom_margin)))
    section.left_margin = Pt(max(18.0, min(144.0, m.left)))
    section.right_margin = Pt(max(18.0, min(144.0, first.width - m.right)))

    def set_line_spacing(p: Any, pts: float) -> None:
        ppr = p._p.get_or_add_pPr()
        sp = ppr.find(qn("w:spacing"))
        if sp is None:
            sp = OxmlElement("w:spacing")
            ppr.append(sp)
        sp.set(qn("w:line"), str(round(pts * 20)))
        sp.set(qn("w:lineRule"), "atLeast")

    def add_field(p: Any, seg: Seg) -> None:
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), f" {seg.field} ")
        r = OxmlElement("w:r")
        fld.append(r)
        t = OxmlElement("w:t")
        t.text = seg.text
        r.append(t)
        p._p.append(fld)
        run = p.runs[-1] if p.runs and p.runs[-1]._r is r else None
        if run is not None:
            style_run(run, seg.style)

    def style_run(run: Any, style: Style) -> None:
        family, size, bold, italic, underline, color = style
        if family != default_family:
            run.font.name = family
            run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:cs"), family)
        if abs(size - default_size) >= 0.5:
            run.font.size = Pt(size)
        if bold:
            run.font.bold = True
        if italic:
            run.font.italic = True
        if underline:
            run.font.underline = True
        if color:
            run.font.color.rgb = RGBColor.from_string(color)

    def write_lines(container: Any, lines: list[Line], left: float, right: float, reuse: Any = None) -> Any:
        """Agrupa as linhas em parágrafos e escreve; `reuse` = parágrafo vazio existente (célula/cabeçalho)."""
        sub = Metrics(left, right, m.ratio)
        paras: list[list[Line]] = []
        for ln in lines:
            if paras and not _breaks(paras[-1][-1], ln, paras[-1], sub):
                paras[-1].append(ln)
            else:
                paras.append([ln])
        last = None
        for k, group in enumerate(paras):
            p = reuse if (k == 0 and reuse is not None) else container.add_paragraph()
            prev_group = paras[k - 1] if k else None
            write_para(
                p,
                Para(group, gap_before=_gap(prev_group[-1], group[0], sub) if prev_group else 0.0),
                left,
                right,
            )
            last = p
        return last

    def write_para(p: Any, para: Para, left: float, right: float) -> None:
        fmt = _para_format(para.lines, left, right, m)
        pf = p.paragraph_format
        if fmt["align"] != "left":
            pf.alignment = align_map[fmt["align"]]
        if fmt["left"] >= 2:
            pf.left_indent = Pt(round(fmt["left"], 1))
        if abs(fmt["first"]) >= 2:
            pf.first_line_indent = Pt(round(fmt["first"], 1))
        if para.gap_before >= 2:
            pf.space_before = Pt(round(para.gap_before))
        if para.page_break:
            pf.page_break_before = True
        for pos in fmt.get("tabs", []):
            pf.tab_stops.add_tab_stop(Pt(pos))
        size = max(ln.size for ln in para.lines)
        set_line_spacing(p, round(size * m.ratio * 0.98, 1))
        segs = _join_lines(para.lines)
        if fmt.get("marker_tab"):
            _marker_tab(segs)
        for seg in segs:
            if seg.field:
                add_field(p, seg)
            elif seg.text:
                style_run(p.add_run(seg.text), seg.style)

    def write_image(container: Any, im: ImageItem, left: float, right: float, reuse: Any = None) -> Any:
        p = reuse if reuse is not None else container.add_paragraph()
        width = im.x1 - im.x0
        center = (left + right) / 2
        if abs((im.x0 + im.x1) / 2 - center) <= 10 and im.x0 > left + 6:
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif abs(im.x1 - right) <= 6 and im.x0 > left + 6:
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif im.x0 - left >= 2:
            p.paragraph_format.left_indent = Pt(round(im.x0 - left, 1))
        if im.gap_before >= 2:
            p.paragraph_format.space_before = Pt(round(im.gap_before))
        if im.page_break:
            p.paragraph_format.page_break_before = True
        p.add_run().add_picture(io.BytesIO(im.png), width=Pt(min(width, right - left)))
        return p

    def write_table(t: TableItem) -> None:
        nr, nc = len(t.rows) - 1, len(t.cols) - 1
        table = doc.add_table(rows=nr, cols=nc)
        with contextlib.suppress(KeyError):
            table.style = doc.styles["Table Grid"]
        table.autofit = False
        widths = [t.cols[i + 1] - t.cols[i] for i in range(nc)]
        for ci, wpt in enumerate(widths):
            table.columns[ci].width = Pt(wpt)
            for cell in table.columns[ci].cells:
                cell.width = Pt(wpt)
        for ri, row in enumerate(table.rows):  # altura mínima = a do PDF (o Word só cresce se o texto pedir)
            row.height = Pt(round(t.rows[ri + 1] - t.rows[ri], 1))
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        center = (m.left + m.right) / 2
        if abs((t.x0 + t.x1) / 2 - center) <= 6 and t.x0 > m.left + 6:
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
        elif (
            abs(t.x0 - m.left) >= 1
        ):  # negativo é o normal: a borda fica fora da margem e o texto alinhado a ela
            tblpr = table._tbl.tblPr
            ind = OxmlElement("w:tblInd")
            ind.set(qn("w:w"), str(round((t.x0 - m.left) * 20)))
            ind.set(qn("w:type"), "dxa")
            tblpr.append(ind)
        for c in t.cells:
            a = table.cell(c.r0, c.c0)
            b = table.cell(c.r1 - 1, c.c1 - 1)
            if a._tc is not b._tc:
                a.merge(b)
        for c in t.cells:
            cell = table.cell(c.r0, c.c0)
            cx0, cx1 = t.cols[c.c0] + 5.4, t.cols[c.c1] - 5.4  # margem interna padrão da célula no Word
            items: list[Line | ImageItem] = sorted([*c.lines, *c.images], key=lambda x: x.top)
            reuse = cell.paragraphs[0] if cell.paragraphs and not cell.paragraphs[0].text else None
            pending: list[Line] = []
            for it in items:
                if isinstance(it, Line):
                    pending.append(it)
                    continue
                if pending:
                    write_lines(cell, pending, cx0, cx1, reuse)
                    reuse, pending = None, []
                write_image(cell, it, cx0, cx1, reuse)
                reuse = None
            if pending:
                write_lines(cell, pending, cx0, cx1, reuse)
        prev_el = table._tbl.getprevious()
        if t.gap_before >= 2 and prev_el is not None and prev_el.tag == qn("w:p"):
            # tabela não tem "espaço antes" no Word: o espaço vai para o parágrafo anterior
            ppr = prev_el.get_or_add_pPr()
            sp = ppr.find(qn("w:spacing"))
            if sp is None:
                sp = OxmlElement("w:spacing")
                ppr.append(sp)
            sp.set(qn("w:after"), str(round(t.gap_before * 20)))
        if t.page_break and prev_el is not None:
            br_p = doc.add_paragraph()
            br_p.add_run().add_break(WD_BREAK.PAGE)
            table._tbl.addprevious(br_p._p)

    last_was_table = False
    for it in flow:
        if isinstance(it, Para):
            write_para(doc.add_paragraph(), it, m.left, m.right)
            last_was_table = False
        elif isinstance(it, TableItem):
            if last_was_table:
                doc.add_paragraph()  # duas tabelas seguidas no Word se fundem: separa com parágrafo vazio
            write_table(it)
            last_was_table = True
        else:
            write_image(doc, it, m.left, m.right)
            last_was_table = False
    if last_was_table or not doc.paragraphs:
        doc.add_paragraph()

    for part_items, part in ((header, section.header), (footer, section.footer)):
        if not part_items:
            continue
        part.is_linked_to_previous = False
        reuse = part.paragraphs[0] if part.paragraphs else None
        pending_h: list[Line] = []
        for x in part_items:
            if isinstance(x, Line):
                pending_h.append(x)
                continue
            if pending_h:
                write_lines(part, pending_h, m.left, m.right, reuse)
                reuse, pending_h = None, []
            write_image(part, x, m.left, m.right, reuse)
            reuse = None
        if pending_h:
            write_lines(part, pending_h, m.left, m.right, reuse)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
