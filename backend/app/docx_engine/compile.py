"""Compilação do gabarito: aplica as edições do editor ao DOCX original e cria os runs-token.

Só parágrafos *modificados* (texto, marcas ou campos) são reconstruídos; os demais ficam iguais ao
original. Cada ocorrência de campo vira um único run com o texto `⟦F:<nonce>:<nome>⟧`, que o
renderizador troca pelo valor. Assim o valor nunca depende de casar texto atravessando runs.
"""

from __future__ import annotations

import io
import secrets
import zipfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from app.docx_engine.inline import (
    Piece,
    comparable,
    new_paragraph_like,
    pieces_to_nodes,
    read_paragraph,
    rebuild_paragraph,
)
from app.docx_engine.ooxml import local, parse_xml, to_bytes, w
from app.docx_engine.parse import part_files, walk_part

TOKEN_OPEN = "⟦"  # ⟦
TOKEN_CLOSE = "⟧"  # ⟧
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass
class BlockSpec:
    key: str
    container_key: str
    ordinal: int
    kind: str
    origin: str  # original | inserted
    content: Any
    attrs: dict[str, Any] | None = None


@dataclass
class CompileResult:
    data: bytes
    tokens: dict[str, int]
    modified_blocks: int
    inserted_blocks: int
    deleted_blocks: int
    warnings: list[str] = field(default_factory=list)


def make_token(nonce: str, name: str) -> str:
    return f"{TOKEN_OPEN}F:{nonce}:{name}{TOKEN_CLOSE}"


def _strip_external_templates(name: str, data: bytes) -> bytes | None:
    """Remove referências externas de modelo anexado (evita que o conversor busque recursos remotos)."""
    if name == "word/_rels/settings.xml.rels":
        root = parse_xml(data)
        changed = False
        for rel in list(root):
            if rel.get("TargetMode") == "External" and str(rel.get("Type", "")).endswith("/attachedTemplate"):
                root.remove(rel)
                changed = True
        return to_bytes(root) if changed else None
    return None


def compile_docx(
    original: bytes,
    specs: Sequence[BlockSpec],
    field_names: Mapping[str, str],
    *,
    nonce: str | None = None,
) -> CompileResult:
    nonce = nonce or secrets.token_hex(4)
    zf = zipfile.ZipFile(io.BytesIO(original))
    tokens: Counter[str] = Counter()
    warnings: list[str] = []
    modified = inserted = deleted = 0

    by_container: dict[str, list[BlockSpec]] = defaultdict(list)
    for s in specs:
        by_container[s.container_key].append(s)
    for lst in by_container.values():
        lst.sort(key=lambda s: s.ordinal)
    spec_keys = {s.key for s in specs}

    roots: dict[str, etree._Element] = {}
    elements: dict[str, etree._Element] = {}
    kinds: dict[str, str] = {}
    hidden: dict[str, bool] = {}
    first_in_container: dict[str, etree._Element] = {}
    container_of: dict[str, str] = {}
    for name, path in part_files(zf):
        if path not in zf.namelist():
            continue
        root = parse_xml(zf.read(path))
        roots[path] = root
        for item in walk_part(root, name):
            elements[item.key] = item.element
            kinds[item.key] = item.kind
            hidden[item.key] = item.hidden
            container_of[item.key] = item.container_key
            first_in_container.setdefault(item.container_key, item.element)

    # modelos de todos os parágrafos lidos ANTES de qualquer mutação (átomos podem ser referenciados)
    models = {k: read_paragraph(el) for k, el in elements.items() if kinds[k] == "paragraph"}

    def resolve_atom(ref: str) -> Piece | None:
        key, _, idx = ref.partition("#")
        model = models.get(key)
        if model is None or not idx.isdigit():
            return None
        atoms = model.atoms()
        return atoms[int(idx)] if int(idx) < len(atoms) else None

    def field_token(node: dict[str, Any]) -> str | None:
        name = field_names.get((node.get("attrs") or {}).get("fieldId") or "")
        if not name:
            warnings.append("Um campo removido ainda estava no documento; o texto original foi mantido.")
            return None
        tokens[name] += 1
        return make_token(nonce, name)

    for container_key, ordered in by_container.items():
        prev_el: etree._Element | None = None
        for spec in ordered:
            if spec.kind != "paragraph":
                prev_el = elements.get(spec.key, prev_el)
                continue
            if spec.origin == "original":
                el = elements.get(spec.key)
                if el is None or kinds.get(spec.key) != "paragraph":
                    warnings.append(f"Bloco {spec.key} não existe mais no arquivo original; ignorado.")
                    continue
                model = models[spec.key]
                if comparable(spec.content or []) != comparable(pieces_to_nodes(model.pieces, spec.key)):
                    rebuild_paragraph(
                        el, model, spec.content or [], resolve_atom=resolve_atom, field_token=field_token
                    )
                    modified += 1
                prev_el = el
            else:
                clone_key = (spec.attrs or {}).get("clone_of")
                newp, newmodel = new_paragraph_like(
                    elements.get(clone_key or ""), models.get(clone_key or "")
                )
                rebuild_paragraph(
                    newp, newmodel, spec.content or [], resolve_atom=resolve_atom, field_token=field_token
                )
                if prev_el is not None:
                    prev_el.addnext(newp)
                else:
                    first = first_in_container.get(container_key)
                    if first is not None and first.getparent() is not None:
                        first.addprevious(newp)
                    else:
                        warnings.append(f"Não foi possível inserir parágrafo em {container_key}.")
                        continue
                inserted += 1
                prev_el = newp

    # remoções por último (não invalidam âncoras de inserção)
    for key, el in elements.items():
        if kinds[key] != "paragraph" or key in spec_keys or hidden.get(key):
            continue
        parent = el.getparent()
        if parent is None:
            continue
        if local(parent) == "tc" and not [c for c in parent if local(c) in ("p", "tbl") and c is not el]:
            continue  # célula não pode ficar sem parágrafo
        parent.remove(el)
        deleted += 1

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zf.infolist():
            data = zf.read(info.filename)
            if info.filename in roots:
                data = to_bytes(roots[info.filename])
            elif (patched := _strip_external_templates(info.filename, data)) is not None:
                data = patched
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    return CompileResult(
        out.getvalue(), dict(tokens), modified, inserted, deleted, list(dict.fromkeys(warnings))
    )


__all__ = ["BlockSpec", "CompileResult", "compile_docx", "make_token", "w"]
