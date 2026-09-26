"""Leitura de um .docx em um modelo de blocos com chaves estáveis.

Chaves (determinísticas, por posição no XML original):
  body/p3                 3º parágrafo do corpo
  body/t1                 1ª tabela; células: body/t1/r2/c1 ; parágrafo: body/t1/r2/c1/p1
  header1/p1, footer2/p1  cabeçalhos e rodapés
  body/x1                 elemento de bloco opaco (ex.: controle de conteúdo)
O mesmo percurso (`walk_part`) é usado pelo compilador, garantindo que as chaves coincidam.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from app.docx_engine.inline import inline_text, pieces_to_nodes, read_paragraph
from app.docx_engine.ooxml import PART_RE, local, parse_xml, w, wattr


@dataclass
class WalkItem:
    key: str
    container_key: str
    ordinal: int
    kind: str  # paragraph | table | opaque
    element: etree._Element
    hidden: bool = False
    grid: dict[str, Any] | None = None


@dataclass
class ParsedBlock:
    key: str
    part: str
    container_key: str
    ordinal: int
    kind: str
    content: Any
    attrs: dict[str, Any]
    text: str


@dataclass
class PartInfo:
    name: str  # body | header1 | footer1
    kind: str  # body | header | footer
    label: str
    hidden: bool = False


@dataclass
class ParsedDocument:
    blocks: list[ParsedBlock]
    parts: list[PartInfo]
    stats: dict[str, int]
    warnings: list[str] = field(default_factory=list)


def part_files(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(nome_lógico, caminho_no_zip)] na ordem: cabeçalhos, corpo, rodapés."""
    names = set(zf.namelist())
    headers, footers = [], []
    for n in sorted(names):
        m = PART_RE.match(n)
        if m:
            (headers if m.group(1) == "header" else footers).append((f"{m.group(1)}{m.group(2) or ''}", n))
    body = [("body", "word/document.xml")]
    return sorted(headers, key=_natural) + body + sorted(footers, key=_natural)


def _natural(item: tuple[str, str]) -> tuple[str, int]:
    m = re.match(r"([a-z]+)(\d*)", item[0])
    return (m.group(1), int(m.group(2) or 0)) if m else (item[0], 0)


def load_styles(zf: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    if "word/styles.xml" not in zf.namelist():
        return {}
    root = parse_xml(zf.read("word/styles.xml"))
    styles: dict[str, dict[str, Any]] = {}
    for st in root.findall(w("style")):
        sid = wattr(st, "styleId")
        if not sid:
            continue
        name_el = st.find(w("name"))
        based = st.find(w("basedOn"))
        ppr = st.find(w("pPr"))
        outline = ppr.find(w("outlineLvl")) if ppr is not None else None
        styles[sid] = {
            "name": (wattr(name_el, "val") or "").lower() if name_el is not None else "",
            "based_on": wattr(based, "val") if based is not None else None,
            "outline": int(wattr(outline, "val") or 9) if outline is not None else None,
        }
    return styles


def heading_level(
    style_id: str | None, styles: dict[str, dict[str, Any]], ppr: etree._Element | None
) -> int | None:
    seen = set()
    sid = style_id
    while sid and sid not in seen:
        seen.add(sid)
        st = styles.get(sid)
        if not st:
            break
        m = re.match(r"heading\s*(\d)", st["name"])
        if m:
            return min(int(m.group(1)), 6)
        if st["name"] == "title":
            return 1
        if st["name"] == "subtitle":
            return 2
        if st["outline"] is not None and st["outline"] < 9:
            return min(st["outline"] + 1, 6)
        sid = st["based_on"]
    if ppr is not None:
        ol = ppr.find(w("outlineLvl"))
        if ol is not None and (wattr(ol, "val") or "9").isdigit() and int(wattr(ol, "val") or 9) < 9:
            return min(int(wattr(ol, "val") or 0) + 1, 6)
    return None


def paragraph_attrs(ppr: etree._Element | None, styles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if ppr is None:
        return attrs
    ps = ppr.find(w("pStyle"))
    style = wattr(ps, "val") if ps is not None else None
    if style:
        attrs["style"] = style
    if (level := heading_level(style, styles, ppr)) is not None:
        attrs["heading"] = level
    jc = ppr.find(w("jc"))
    if jc is not None:
        v = wattr(jc, "val")
        attrs["align"] = {"both": "justify", "distribute": "justify", "start": "left", "end": "right"}.get(
            v or "", v
        )
    num = ppr.find(w("numPr"))
    if num is not None and num.find(w("numId")) is not None and wattr(num.find(w("numId")), "val") != "0":
        attrs["list"] = True
        il = num.find(w("ilvl"))
        attrs["level"] = int(wattr(il, "val") or 0) if il is not None else 0
    return attrs


def _table_grid(tbl: etree._Element, key: str) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    for ri, tr in enumerate(tbl.findall(w("tr")), 1):
        cells = []
        for ci, tc in enumerate(tr.findall(w("tc")), 1):
            tcpr = tc.find(w("tcPr"))
            span, vmerge, width = 1, None, None
            if tcpr is not None:
                gs = tcpr.find(w("gridSpan"))
                if gs is not None and (wattr(gs, "val") or "").isdigit():
                    span = max(1, int(wattr(gs, "val") or 1))
                vm = tcpr.find(w("vMerge"))
                if vm is not None:
                    vmerge = "restart" if wattr(vm, "val") == "restart" else "continue"
                tw = tcpr.find(w("tcW"))
                if (
                    tw is not None
                    and (wattr(tw, "type") or "dxa") == "dxa"
                    and (wattr(tw, "w") or "").isdigit()
                ):
                    width = int(wattr(tw, "w") or 0)
            cells.append(
                {"container": f"{key}/r{ri}/c{ci}", "colspan": span, "vmerge": vmerge, "width": width}
            )
        rows.append(cells)
    colwidths: list[int] = []
    tg = tbl.find(w("tblGrid"))
    if tg is not None:
        colwidths = [
            int(wattr(gc, "w") or 0) for gc in tg.findall(w("gridCol")) if (wattr(gc, "w") or "").isdigit()
        ]
    return {"rows": rows, "colwidths": colwidths}


def _walk_container(parent: etree._Element, container_key: str, hidden: bool) -> Iterator[WalkItem]:
    p = t = x = 0
    ordinal = 0
    for el in parent:
        n = local(el)
        if n == "p":
            p += 1
            yield WalkItem(f"{container_key}/p{p}", container_key, ordinal, "paragraph", el, hidden)
            ordinal += 1
        elif n == "tbl":
            t += 1
            key = f"{container_key}/t{t}"
            grid = _table_grid(el, key)
            yield WalkItem(key, container_key, ordinal, "table", el, hidden, grid)
            ordinal += 1
            for ri, tr in enumerate(el.findall(w("tr")), 1):
                for ci, tc in enumerate(tr.findall(w("tc")), 1):
                    cell = grid["rows"][ri - 1][ci - 1]
                    yield from _walk_container(tc, cell["container"], hidden or cell["vmerge"] == "continue")
        elif n == "sdt":
            x += 1
            yield WalkItem(f"{container_key}/x{x}", container_key, ordinal, "opaque", el, hidden)
            ordinal += 1


def walk_part(root: etree._Element, part: str) -> Iterator[WalkItem]:
    body = root.find(w("body")) if local(root) == "document" else root
    if body is None:
        return
    yield from _walk_container(body, part, False)


def _label(name: str, kind: str, index: int, total: int) -> str:
    base = {"header": "Cabeçalho", "footer": "Rodapé", "body": "Documento"}[kind]
    return base if total <= 1 or kind == "body" else f"{base} {index}"


def parse_docx(data: bytes) -> ParsedDocument:
    zf = zipfile.ZipFile(io.BytesIO(data))
    styles = load_styles(zf)
    files = part_files(zf)
    counts = {
        "header": sum(1 for n, _ in files if n.startswith("header")),
        "footer": sum(1 for n, _ in files if n.startswith("footer")),
    }
    blocks: list[ParsedBlock] = []
    parts: list[PartInfo] = []
    stats = {"paragraphs": 0, "tables": 0, "atoms": 0, "images": 0, "headers": 0, "footers": 0}
    warnings: list[str] = []

    for name, path in files:
        if path not in zf.namelist():
            continue
        root = parse_xml(zf.read(path))
        kind = "body" if name == "body" else ("header" if name.startswith("header") else "footer")
        part_blocks: list[ParsedBlock] = []
        has_content = kind == "body"
        for item in walk_part(root, name):
            if item.kind == "paragraph":
                model = read_paragraph(item.element)
                content = pieces_to_nodes(model.pieces, item.key)
                text = inline_text(content)
                attrs = paragraph_attrs(model.ppr, styles)
                if text.strip() or any(pc.kind == "atom" for pc in model.pieces):
                    has_content = True
                stats["paragraphs"] += 1
                for pc in model.pieces:
                    if pc.kind == "atom":
                        stats["atoms"] += 1
                        if pc.atom_kind in ("drawing", "pict"):
                            stats["images"] += 1
                if item.hidden:
                    attrs["hidden"] = True
                part_blocks.append(
                    ParsedBlock(
                        item.key, name, item.container_key, item.ordinal, "paragraph", content, attrs, text
                    )
                )
            elif item.kind == "table":
                stats["tables"] += 1
                attrs = {"hidden": True} if item.hidden else {}
                part_blocks.append(
                    ParsedBlock(
                        item.key, name, item.container_key, item.ordinal, "table", item.grid, attrs, ""
                    )
                )
            else:
                attrs = {"label": "Controle de conteúdo do Word (não editável)"}
                if item.hidden:
                    attrs["hidden"] = True
                warnings.append(
                    "O documento contém controles de conteúdo do Word; eles são preservados, mas não editáveis."
                )
                part_blocks.append(
                    ParsedBlock(item.key, name, item.container_key, item.ordinal, "opaque", None, attrs, "")
                )
        info = PartInfo(name, kind, "", hidden=not has_content)
        idx = int(re.sub(r"\D", "", name) or 1)
        info.label = _label(name, kind, idx, counts.get(kind, 1))
        if info.hidden:
            for b in part_blocks:
                b.attrs["hidden"] = True
        else:
            if kind == "header":
                stats["headers"] += 1
            elif kind == "footer":
                stats["footers"] += 1
        blocks.extend(part_blocks)
        parts.append(info)

    warnings = list(dict.fromkeys(warnings))
    if stats["atoms"]:
        warnings.append(
            f"{stats['atoms']} elemento(s) avançado(s) (imagens, quebras, campos do Word) foram preservados "
            "na mesma posição, mas não podem ser editados aqui."
        )
    return ParsedDocument(blocks, parts, stats, warnings)
