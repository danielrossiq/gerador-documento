"""Operações puras sobre o conteúdo inline de um bloco (nós no formato TipTap).

Modelo de offsets (idêntico no cliente): texto → seu texto; campo → `sample`; átomo → 1 char (U+FFFC);
hardBreak → 1 char (\\n).
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Iterator
from typing import Any

from app.docx_engine.inline import ATOM_CHAR, inline_text, normalize_nodes

CONTEXT_CHARS = 40


class RangeError(ValueError):
    pass


def node_len(node: dict[str, Any]) -> int:
    t = node.get("type")
    if t == "text":
        return len(node.get("text", ""))
    if t == "field":
        return len((node.get("attrs") or {}).get("sample", ""))
    if t in ("hardBreak", "docAtom"):
        return 1
    return 0


def iter_field_spans(content: list[dict[str, Any]]) -> Iterator[tuple[int, int, dict[str, Any]]]:
    pos = 0
    for n in content:
        length = node_len(n)
        if n.get("type") == "field":
            yield pos, pos + length, n
        pos += length


def context_around(text: str, start: int, end: int) -> tuple[str, str]:
    return text[max(0, start - CONTEXT_CHARS) : start], text[end : end + CONTEXT_CHARS]


def split_text_at(content: list[dict[str, Any]], offsets: set[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pos = 0
    for n in content:
        length = node_len(n)
        if n.get("type") == "text" and length:
            cuts = sorted(o - pos for o in offsets if pos < o < pos + length)
            if cuts:
                bounds = [0, *cuts, length]
                for a, b in itertools.pairwise(bounds):
                    piece = copy.deepcopy(n)
                    piece["text"] = n["text"][a:b]
                    out.append(piece)
                pos += length
                continue
        out.append(n)
        pos += length
    return out


def replace_range_with_field(
    content: list[dict[str, Any]], start: int, end: int, field_id: str
) -> tuple[list[dict[str, Any]], str]:
    """Troca content[start:end] por um nó de campo. Devolve (novo_conteúdo, texto_original)."""
    text = inline_text(content)
    if not (0 <= start <= end <= len(text)):
        raise RangeError("Trecho fora dos limites do bloco.")
    parts = split_text_at(content, {start, end})
    covered: list[dict[str, Any]] = []
    pos = 0
    first_idx: int | None = None
    for i, n in enumerate(parts):
        length = node_len(n)
        if length and pos >= start and pos + length <= end:
            if n.get("type") != "text":
                raise RangeError("A seleção contém quebras de linha ou elementos que não são texto.")
            covered.append(n)
        if first_idx is None and pos >= start:
            first_idx = i
        pos += length
    if start != end and not covered:
        raise RangeError("Trecho inválido.")
    sample = "".join(n["text"] for n in covered)
    marks_src: dict[str, Any] | None = covered[0] if covered else None
    if marks_src is None:  # inserção no cursor: herda marcas do texto à esquerda
        pos = 0
        for n in parts:
            length = node_len(n)
            if n.get("type") == "text" and pos + length <= start:
                marks_src = n
            pos += length
    field_node: dict[str, Any] = {"type": "field", "attrs": {"fieldId": field_id, "sample": sample}}
    if marks_src and marks_src.get("marks"):
        field_node["marks"] = copy.deepcopy(marks_src["marks"])

    out: list[dict[str, Any]] = []
    pos = 0
    placed = False
    for n in parts:
        length = node_len(n)
        if not placed and pos >= start:
            out.append(field_node)
            placed = True
        if length and pos >= start and pos + length <= end:
            pos += length
            continue
        out.append(n)
        pos += length
    if not placed:
        out.append(field_node)
    return normalize_nodes(out), sample


def unwrap_field(
    content: list[dict[str, Any]], field_id: str, keep_text: bool
) -> tuple[list[dict[str, Any]], int]:
    """Remove nós do campo `field_id`; se `keep_text`, deixa o texto original (sample) no lugar."""
    out: list[dict[str, Any]] = []
    count = 0
    for n in content:
        if n.get("type") == "field" and (n.get("attrs") or {}).get("fieldId") == field_id:
            count += 1
            sample = (n.get("attrs") or {}).get("sample", "")
            if keep_text and sample:
                item: dict[str, Any] = {"type": "text", "text": sample}
                if n.get("marks"):
                    item["marks"] = copy.deepcopy(n["marks"])
                out.append(item)
        else:
            out.append(n)
    return normalize_nodes(out), count


def has_atoms_or_fields(content: list[dict[str, Any]]) -> bool:
    return any(n.get("type") in ("field", "docAtom") for n in content)


__all__ = [
    "ATOM_CHAR",
    "RangeError",
    "context_around",
    "inline_text",
    "iter_field_spans",
    "node_len",
    "replace_range_with_field",
    "split_text_at",
    "unwrap_field",
]
