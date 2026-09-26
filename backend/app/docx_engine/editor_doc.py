"""Conversão entre blocos persistidos e o documento JSON do editor (TipTap/ProseMirror).

Funções puras (sem banco) para facilitar teste. O servidor é a autoridade: o editor apenas exibe e
devolve o documento; o servidor valida a estrutura e reconcilia com os blocos originais.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class BlockLike(Protocol):
    key: str
    part: str
    container_key: str
    ordinal: int
    kind: str
    content: Any
    attrs: dict[str, Any] | None


@dataclass
class PartLike:
    name: str
    kind: str
    label: str
    hidden: bool = False


@dataclass
class BlockIn:
    """Bloco recebido do editor (ainda não reconciliado)."""

    key: str | None
    container_key: str
    part: str
    ordinal: int
    kind: str
    content: list[dict[str, Any]]
    attrs: dict[str, Any]


DISPLAY_ATTRS = ("style", "heading", "align", "list", "level")


def _table_node(block: BlockLike, by_container: dict[str, list[BlockLike]]) -> dict[str, Any]:
    grid = block.content or {"rows": [], "colwidths": []}
    rows = grid["rows"]
    colwidths = grid.get("colwidths") or []
    rowspans: dict[tuple[int, int], int] = {}
    restart_at: dict[int, tuple[int, int]] = {}
    for ri, row in enumerate(rows):
        col = 0
        for ci, cell in enumerate(row):
            vm = cell.get("vmerge")
            if vm == "continue":
                origin = restart_at.get(col)
                if origin:
                    rowspans[origin] += 1
            elif vm == "restart":
                restart_at[col] = (ri, ci)
                rowspans[(ri, ci)] = 1
            else:
                restart_at.pop(col, None)
            col += int(cell.get("colspan", 1))

    row_nodes = []
    for ri, row in enumerate(rows):
        cell_nodes = []
        col = 0
        for ci, cell in enumerate(row):
            span = int(cell.get("colspan", 1))
            start = col
            col += span
            if cell.get("vmerge") == "continue":
                continue
            widths = (
                [round(cw / 15) for cw in colwidths[start : start + span]]
                if colwidths and len(colwidths) >= start + span
                else None
            )
            inner = build_container(cell["container"], by_container) or [
                {"type": "paragraph", "attrs": {"blockKey": None}}
            ]
            cell_nodes.append(
                {
                    "type": "tableCell",
                    "attrs": {
                        "container": cell["container"],
                        "colspan": span,
                        "rowspan": rowspans.get((ri, ci), 1),
                        "colwidth": widths,
                    },
                    "content": inner,
                }
            )
        row_nodes.append({"type": "tableRow", "content": cell_nodes})
    return {"type": "table", "attrs": {"blockKey": block.key}, "content": row_nodes}


def build_container(container_key: str, by_container: dict[str, list[BlockLike]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for b in by_container.get(container_key, []):
        attrs = b.attrs or {}
        if attrs.get("hidden"):
            continue
        if b.kind == "paragraph":
            node: dict[str, Any] = {
                "type": "paragraph",
                "attrs": {"blockKey": b.key, **{k: attrs[k] for k in DISPLAY_ATTRS if k in attrs}},
            }
            if b.content:
                node["content"] = b.content
            nodes.append(node)
        elif b.kind == "table":
            nodes.append(_table_node(b, by_container))
        else:
            nodes.append(
                {
                    "type": "docOpaque",
                    "attrs": {"blockKey": b.key, "label": attrs.get("label", "Elemento avançado")},
                }
            )
    return nodes


def blocks_to_doc(blocks: Sequence[BlockLike], parts: Sequence[PartLike]) -> dict[str, Any]:
    by_container: dict[str, list[BlockLike]] = {}
    for b in sorted(blocks, key=lambda x: (x.container_key, x.ordinal)):
        by_container.setdefault(b.container_key, []).append(b)
    part_nodes = []
    for part in parts:
        if part.hidden:
            continue
        content = build_container(part.name, by_container)
        if content:
            part_nodes.append(
                {
                    "type": "docPart",
                    "attrs": {"part": part.name, "label": part.label, "kind": part.kind},
                    "content": content,
                }
            )
    return {"type": "doc", "content": part_nodes}


class DocStructureError(ValueError):
    pass


def walk_doc(doc: dict[str, Any]) -> Iterator[BlockIn]:
    if doc.get("type") != "doc":
        raise DocStructureError("Documento inválido: raiz deve ser 'doc'.")
    for part_node in doc.get("content", []):
        if part_node.get("type") != "docPart":
            raise DocStructureError("Documento inválido: esperado 'docPart'.")
        part = (part_node.get("attrs") or {}).get("part")
        if not part:
            raise DocStructureError("docPart sem identificador.")
        yield from _walk_nodes(part_node.get("content", []), part, part)


def _walk_nodes(nodes: list[dict[str, Any]], container_key: str, part: str) -> Iterator[BlockIn]:
    for ordinal, n in enumerate(nodes):
        t = n.get("type")
        attrs = n.get("attrs") or {}
        if t == "paragraph":
            yield BlockIn(
                attrs.get("blockKey"),
                container_key,
                part,
                ordinal,
                "paragraph",
                n.get("content", []) or [],
                {k: attrs[k] for k in DISPLAY_ATTRS if attrs.get(k) is not None},
            )
        elif t == "table":
            yield BlockIn(attrs.get("blockKey"), container_key, part, ordinal, "table", [], {})
            for row in n.get("content", []):
                for cell in row.get("content", []):
                    cont = (cell.get("attrs") or {}).get("container")
                    if not cont:
                        raise DocStructureError("Célula de tabela sem identificador.")
                    yield from _walk_nodes(cell.get("content", []), cont, part)
        elif t == "docOpaque":
            yield BlockIn(attrs.get("blockKey"), container_key, part, ordinal, "opaque", [], {})
        else:
            raise DocStructureError(f"Nó de bloco não suportado: {t!r}.")
