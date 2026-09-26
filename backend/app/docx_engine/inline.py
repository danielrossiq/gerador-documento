"""Modelo inline de um parágrafo do Word e reconstrução preservando formatação.

Um parágrafo é lido como uma lista de *peças*:
  - texto (com o `w:rPr` do run de origem e, se houver, o `w:hyperlink` que o contém);
  - átomos opacos (imagens, quebras de página, campos complexos do Word, controles de conteúdo…),
    preservados intactos e na mesma posição.

Isso resolve o problema clássico do Word: um trecho visual ("João da Silva") pode estar dividido
em vários runs ("Jo" + "ão da Silva"), com formatações diferentes. Aqui o texto vira uma sequência
de caracteres e cada caractere sabe de qual run veio; a reconstrução mapeia o texto novo ao antigo
(difflib) para herdar a formatação correta.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from lxml import etree

from app.docx_engine.ooxml import apply_marks, local, make_text_children, marks_of, w, wattr

ATOM_CHAR = "￼"
MARK_ORDER = ["bold", "italic", "underline", "strike"]

TRANSPARENT = {"ins", "smartTag", "customXml", "moveTo"}
DROPPED = {"del", "moveFrom", "proofErr", "commentRangeStart", "commentRangeEnd", "permStart", "permEnd"}
PASSTHROUGH = {"bookmarkStart", "bookmarkEnd"}
ATOM_LABELS = {
    "drawing": "Imagem",
    "pict": "Imagem",
    "object": "Objeto",
    "sym": "Símbolo",
    "footnoteReference": "Nota de rodapé",
    "endnoteReference": "Nota de fim",
    "commentReference": "Comentário",
    "pagebreak": "Quebra de página",
    "columnbreak": "Quebra de coluna",
    "field": "Campo do Word",
    "sdt": "Controle de conteúdo",
    "fldSimple": "Campo do Word",
    "oMath": "Equação",
    "oMathPara": "Equação",
}


@dataclass
class Piece:
    kind: str  # "text" | "atom"
    text: str
    rpr: etree._Element | None = None
    container: etree._Element | None = None
    elements: list[etree._Element] = field(default_factory=list)
    atom_kind: str = ""
    label: str = ""


@dataclass
class ParaModel:
    pieces: list[Piece]
    ppr: etree._Element | None
    passthrough: list[etree._Element]

    def chars(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for i, pc in enumerate(self.pieces):
            if pc.kind == "atom":
                out.append((ATOM_CHAR, i))
            else:
                out.extend((ch, i) for ch in pc.text)
        return out

    def text(self) -> str:
        return "".join(ch for ch, _ in self.chars())

    def atoms(self) -> list[Piece]:
        return [p for p in self.pieces if p.kind == "atom"]


def _wrap_run(child: etree._Element, rpr: etree._Element | None) -> etree._Element:
    r = etree.Element(w("r"))
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    r.append(copy.deepcopy(child))
    return r


def _flatten(p: etree._Element) -> list[tuple[str, etree._Element, etree._Element | None]]:
    out: list[tuple[str, etree._Element, etree._Element | None]] = []

    def visit(parent: etree._Element, container: etree._Element | None) -> None:
        for child in parent:
            n = local(child)
            if n is None or n == "pPr":
                continue
            if n == "r":
                out.append(("run", child, container))
            elif n == "hyperlink":
                visit(child, child)
            elif n in TRANSPARENT:
                visit(child, container)
            elif n in DROPPED:
                continue
            elif n in PASSTHROUGH:
                out.append(("pass", child, None))
            else:
                out.append(("atom", child, container))

    visit(p, None)
    return out


def read_paragraph(p: etree._Element) -> ParaModel:
    pieces: list[Piece] = []
    passthrough: list[etree._Element] = []
    items = _flatten(p)

    def add_text(text: str, rpr: etree._Element | None, container: etree._Element | None) -> None:
        if text:
            pieces.append(Piece("text", text, rpr, container))

    def add_atom(kind: str, elements: list[etree._Element], label: str | None = None) -> None:
        pieces.append(
            Piece(
                "atom",
                ATOM_CHAR,
                elements=elements,
                atom_kind=kind,
                label=label or ATOM_LABELS.get(kind, "Elemento"),
            )
        )

    i = 0
    while i < len(items):
        kind, el, cont = items[i]
        if kind == "pass":
            passthrough.append(copy.deepcopy(el))
            i += 1
            continue
        if kind == "atom":
            n = local(el) or "object"
            label = ATOM_LABELS.get(n, "Elemento")
            if n == "fldSimple":
                label = f"Campo do Word ({(wattr(el, 'instr') or '').strip().split(' ')[0] or '…'})"
            add_atom("sdt" if n == "sdt" else n, [copy.deepcopy(el)], label)
            i += 1
            continue
        # run
        if any(fc.get(w("fldCharType")) == "begin" for fc in el.iter(w("fldChar"))):
            collected: list[etree._Element] = []
            depth = 0
            instr = ""
            while i < len(items):
                k2, e2, _ = items[i]
                if k2 == "run":
                    for fc in e2.iter(w("fldChar")):
                        t = fc.get(w("fldCharType"))
                        depth += 1 if t == "begin" else -1 if t == "end" else 0
                    for it in e2.iter(w("instrText")):
                        instr += it.text or ""
                    collected.append(copy.deepcopy(e2))
                i += 1
                if depth <= 0:
                    break
            head = instr.strip().split(" ")[0] if instr.strip() else "…"
            add_atom("field", collected, f"Campo do Word ({head})")
            continue
        rpr = el.find(w("rPr"))
        for c in el:
            n = local(c)
            if n in (None, "rPr"):
                continue
            if n == "t":
                add_text(c.text or "", rpr, cont)
            elif n == "tab":
                add_text("\t", rpr, cont)
            elif n == "cr":
                add_text("\n", rpr, cont)
            elif n == "br":
                typ = c.get(w("type"))
                if typ == "page":
                    add_atom("pagebreak", [_wrap_run(c, rpr)])
                elif typ == "column":
                    add_atom("columnbreak", [_wrap_run(c, rpr)])
                else:
                    add_text("\n", rpr, cont)
            elif n == "noBreakHyphen":
                add_text("‑", rpr, cont)
            elif n in ("softHyphen", "lastRenderedPageBreak", "delText", "instrText", "annotationRef"):
                continue
            else:
                add_atom(n or "object", [_wrap_run(c, rpr)])
        i += 1
    return ParaModel(pieces, p.find(w("pPr")), passthrough)


# ----------------------------------------------------------------------------- nós do editor


def _marks_nodes(marks: list[str]) -> list[dict[str, str]]:
    return [{"type": m} for m in MARK_ORDER if m in marks]


def pieces_to_nodes(pieces: list[Piece], key: str) -> list[dict[str, Any]]:
    """Converte peças em nós inline no formato TipTap (texto+marcas, hardBreak, docAtom)."""
    nodes: list[dict[str, Any]] = []
    atom_i = 0
    for pc in pieces:
        if pc.kind == "atom":
            nodes.append(
                {
                    "type": "docAtom",
                    "attrs": {"ref": f"{key}#{atom_i}", "kind": pc.atom_kind, "label": pc.label},
                }
            )
            atom_i += 1
            continue
        marks = marks_of(pc.rpr)
        for part in re.split(r"(\n)", pc.text):
            if part == "\n":
                nodes.append({"type": "hardBreak"})
            elif part:
                node: dict[str, Any] = {"type": "text", "text": part}
                if marks:
                    node["marks"] = _marks_nodes(marks)
                nodes.append(node)
    return normalize_nodes(nodes)


def _node_marks(node: dict[str, Any]) -> tuple[str, ...]:
    names = {m["type"] if isinstance(m, dict) else m for m in node.get("marks", []) or []}
    return tuple(m for m in MARK_ORDER if m in names)


def normalize_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Forma canônica: junta textos adjacentes de mesmas marcas, ordena marcas, remove texto vazio."""
    out: list[dict[str, Any]] = []
    for node in nodes:
        t = node.get("type")
        if t == "text":
            text = node.get("text", "")
            if not text:
                continue
            marks = _node_marks(node)
            if out and out[-1].get("type") == "text" and _node_marks(out[-1]) == marks:
                out[-1]["text"] += text
                continue
            item: dict[str, Any] = {"type": "text", "text": text}
            if marks:
                item["marks"] = _marks_nodes(list(marks))
            out.append(item)
        elif t == "field":
            attrs = node.get("attrs", {})
            item = {
                "type": "field",
                "attrs": {"fieldId": attrs.get("fieldId"), "sample": attrs.get("sample", "")},
            }
            if marks := _node_marks(node):
                item["marks"] = _marks_nodes(list(marks))
            out.append(item)
        elif t == "docAtom":
            attrs = node.get("attrs", {})
            out.append(
                {
                    "type": "docAtom",
                    "attrs": {
                        "ref": attrs.get("ref"),
                        "kind": attrs.get("kind", ""),
                        "label": attrs.get("label", ""),
                    },
                }
            )
        elif t == "hardBreak":
            out.append({"type": "hardBreak"})
    return out


def comparable(nodes: list[dict[str, Any]]) -> list[Any]:
    """Assinatura para decidir se um parágrafo mudou (ignora rótulo/tipo dos átomos)."""
    sig: list[Any] = []
    for n in normalize_nodes(nodes):
        t = n["type"]
        if t == "text":
            sig.append(("t", n["text"], _node_marks(n)))
        elif t == "field":
            sig.append(("f", n["attrs"]["fieldId"], n["attrs"]["sample"], _node_marks(n)))
        elif t == "docAtom":
            sig.append(("a", n["attrs"]["ref"]))
        else:
            sig.append(("b",))
    return sig


def inline_text(nodes: list[dict[str, Any]]) -> str:
    """Texto plano usado para offsets: campo → `sample`; átomo → U+FFFC; quebra → \\n."""
    out: list[str] = []
    for n in nodes:
        t = n.get("type")
        if t == "text":
            out.append(n.get("text", ""))
        elif t == "hardBreak":
            out.append("\n")
        elif t == "field":
            out.append((n.get("attrs") or {}).get("sample", ""))
        elif t == "docAtom":
            out.append(ATOM_CHAR)
    return "".join(out)


# ----------------------------------------------------------------------------- reconstrução


def _make_run(text: str, piece: Piece | None, marks: frozenset[str]) -> etree._Element:
    r = etree.Element(w("r"))
    rpr = copy.deepcopy(piece.rpr) if piece is not None and piece.rpr is not None else etree.Element(w("rPr"))
    apply_marks(rpr, marks)
    if len(rpr):
        r.append(rpr)
    make_text_children(text, r)
    return r


def rebuild_paragraph(
    p: etree._Element,
    model: ParaModel,
    nodes: list[dict[str, Any]],
    *,
    resolve_atom: Callable[[str], Piece | None],
    field_token: Callable[[dict[str, Any]], str | None],
) -> None:
    """Reescreve os filhos de `p` para refletir `nodes`, herdando a formatação dos runs originais."""
    nodes = normalize_nodes(nodes)
    o_chars = model.chars()
    o_text = "".join(c for c, _ in o_chars)
    n_text = inline_text(nodes)

    n_to_o: list[int | None] = [None] * len(n_text)
    if o_text and n_text:
        for tag, i1, i2, j1, _j2 in SequenceMatcher(None, o_text, n_text, autojunk=False).get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    n_to_o[j1 + k] = i1 + k

    text_piece_idx = [i for i, pc in enumerate(model.pieces) if pc.kind == "text"]
    default_piece = text_piece_idx[0] if text_piece_idx else None

    # peça de texto que governa cada posição j de n_text (com sentinela em len(n_text))
    piece_for: list[int | None] = [None] * (len(n_text) + 1)
    last: int | None = None
    for j in range(len(n_text)):
        o = n_to_o[j]
        if o is not None and model.pieces[o_chars[o][1]].kind == "text":
            last = o_chars[o][1]
        piece_for[j] = last
    piece_for[len(n_text)] = last
    nxt: int | None = None
    for j in range(len(n_text), -1, -1):
        if piece_for[j] is not None:
            nxt = piece_for[j]
        elif nxt is not None:
            piece_for[j] = nxt
    piece_for = [pf if pf is not None else default_piece for pf in piece_for]

    def piece(idx: int | None) -> Piece | None:
        return model.pieces[idx] if idx is not None else None

    elements: list[tuple[etree._Element | None, etree._Element]] = []
    j = 0
    for node in nodes:
        t = node["type"]
        marks = frozenset(_node_marks(node))
        if t == "text":
            txt = node["text"]
            k = 0
            while k < len(txt):
                pi = piece_for[j + k]
                e = k
                while e < len(txt) and piece_for[j + e] == pi:
                    e += 1
                pc = piece(pi)
                elements.append((pc.container if pc else None, _make_run(txt[k:e], pc, marks)))
                k = e
            j += len(txt)
        elif t == "hardBreak":
            pc = piece(piece_for[j])
            elements.append((pc.container if pc else None, _make_run("\n", pc, frozenset())))
            j += 1
        elif t == "field":
            sample = node["attrs"].get("sample", "")
            pi = piece_for[j] if sample else (piece_for[j - 1] if j > 0 else default_piece)
            pc = piece(pi)
            token = field_token(node)
            content = token if token is not None else sample
            if content:
                elements.append((pc.container if pc else None, _make_run(content, pc, marks)))
            j += len(sample)
        elif t == "docAtom":
            src = resolve_atom(node["attrs"].get("ref") or "")
            if src is not None:
                elements.extend((None, copy.deepcopy(el)) for el in src.elements)
            j += 1

    for child in list(p):
        if local(child) != "pPr":
            p.remove(child)
    for pt in model.passthrough:
        p.append(copy.deepcopy(pt))
    current_container: etree._Element | None = None
    wrapper: etree._Element | None = None
    for cont, el in elements:
        if cont is None:
            p.append(el)
            current_container, wrapper = None, None
            continue
        if cont is not current_container or wrapper is None:
            wrapper = etree.SubElement(p, cont.tag)
            for k2, v2 in cont.attrib.items():
                wrapper.set(k2, v2)
            current_container = cont
        wrapper.append(el)


def new_paragraph_like(
    template_p: etree._Element | None, template_model: ParaModel | None
) -> tuple[etree._Element, ParaModel]:
    """Parágrafo vazio que clona o `w:pPr` do modelo; formatação de run vem do 1º run de texto dele."""
    p = etree.Element(w("p"))
    if template_p is not None:
        ppr = template_p.find(w("pPr"))
        if ppr is not None:
            p.append(copy.deepcopy(ppr))
    first_text = next(
        (pc for pc in (template_model.pieces if template_model else []) if pc.kind == "text"), None
    )
    pieces = [Piece("text", "", first_text.rpr if first_text else None)] if first_text else []
    return p, ParaModel(pieces, p.find(w("pPr")), [])
