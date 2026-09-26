"""Utilitários de baixo nível para OOXML (WordprocessingML)."""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"

# Elementos de w:rPr na ordem exigida pelo schema (para inserir marcas no lugar certo).
RPR_ORDER = [
    "rStyle",
    "rFonts",
    "b",
    "bCs",
    "i",
    "iCs",
    "caps",
    "smallCaps",
    "strike",
    "dstrike",
    "outline",
    "shadow",
    "emboss",
    "imprint",
    "noProof",
    "snapToGrid",
    "vanish",
    "webHidden",
    "color",
    "spacing",
    "w",
    "kern",
    "position",
    "sz",
    "szCs",
    "highlight",
    "u",
    "effect",
    "bdr",
    "shd",
    "fitText",
    "vertAlign",
    "rtl",
    "cs",
    "em",
    "lang",
    "eastAsianLayout",
    "specVanish",
    "oMath",
]

PART_RE = re.compile(r"^word/(header|footer)(\d*)\.xml$")


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def local(el: Any) -> str | None:
    """Nome local do elemento; None para comentários/instruções de processamento."""
    tag = getattr(el, "tag", None)
    if not isinstance(tag, str):
        return None
    return tag.rsplit("}", 1)[-1]


def wattr(el: etree._Element, name: str) -> str | None:
    return el.get(w(name))


def new_parser() -> etree.XMLParser:
    # Sem entidades externas, sem rede, sem DTD: protege contra XXE e "billion laughs".
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_blank_text=False,
    )


def parse_xml(data: bytes) -> etree._Element:
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("DTD/entidades não são permitidas em partes OOXML")
    return etree.fromstring(data, new_parser())


def to_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def flag_on(rpr: etree._Element | None, tag: str) -> bool:
    """True se a propriedade booleana existe e não está desligada (val=0/false/none)."""
    if rpr is None:
        return False
    el = rpr.find(w(tag))
    if el is None:
        return False
    val = el.get(w("val"))
    return val is None or val.lower() not in ("0", "false", "off", "none")


def set_rpr_flag(rpr: etree._Element, tag: str, on: bool, complex_tag: str | None = None) -> None:
    """Liga/desliga uma propriedade (b, i, u, strike) respeitando a ordem do schema."""
    for t in [tag] + ([complex_tag] if complex_tag else []):
        for el in rpr.findall(w(t)):
            rpr.remove(el)
    if not on:
        return
    el = etree.Element(w(tag))
    if tag == "u":
        el.set(w("val"), "single")
    _insert_ordered(rpr, el, tag)


def _insert_ordered(rpr: etree._Element, el: etree._Element, tag: str) -> None:
    order = RPR_ORDER.index(tag) if tag in RPR_ORDER else len(RPR_ORDER)
    for i, child in enumerate(rpr):
        name = local(child)
        pos = RPR_ORDER.index(name) if name in RPR_ORDER else len(RPR_ORDER)
        if pos > order:
            rpr.insert(i, el)
            return
    rpr.append(el)


MARK_TO_RPR = {
    "bold": ("b", "bCs"),
    "italic": ("i", "iCs"),
    "underline": ("u", None),
    "strike": ("strike", None),
}


def apply_marks(rpr: etree._Element, marks: frozenset[str] | set[str]) -> None:
    """Faz o rPr refletir exatamente as marcas do editor (negrito/itálico/sublinhado/tachado)."""
    for mark, (tag, ctag) in MARK_TO_RPR.items():
        want = mark in marks
        have = flag_on(rpr, tag) or (tag == "strike" and flag_on(rpr, "dstrike"))
        if want != have:
            set_rpr_flag(rpr, tag, want, ctag)


def marks_of(rpr: etree._Element | None) -> list[str]:
    out = []
    if flag_on(rpr, "b"):
        out.append("bold")
    if flag_on(rpr, "i"):
        out.append("italic")
    if flag_on(rpr, "u"):
        out.append("underline")
    if flag_on(rpr, "strike") or flag_on(rpr, "dstrike"):
        out.append("strike")
    return out


def make_text_children(text: str, run: etree._Element) -> None:
    """Acrescenta ao run os filhos w:t / w:tab / w:br equivalentes ao texto."""
    buf: list[str] = []

    def flush() -> None:
        if buf:
            t = etree.SubElement(run, w("t"))
            t.text = "".join(buf)
            t.set(f"{{{XML_NS}}}space", "preserve")
            buf.clear()

    for ch in text:
        if ch == "\t":
            flush()
            etree.SubElement(run, w("tab"))
        elif ch == "\n":
            flush()
            etree.SubElement(run, w("br"))
        else:
            buf.append(ch)
    flush()
