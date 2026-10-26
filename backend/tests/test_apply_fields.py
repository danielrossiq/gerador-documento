"""`apply_fields` (prévia do teste grátis, QA-4): mesmo resultado que `replace_range_with_field` um por um."""

from __future__ import annotations

import random

from app.docx_engine.inline import inline_text, normalize_nodes
from app.docx_engine.nodes import RangeError, apply_fields, replace_range_with_field


def _one_by_one(content, spans):  # type: ignore[no-untyped-def]
    applied = []
    for s, e, fid in sorted(spans, reverse=True):
        try:
            content, _ = replace_range_with_field(content, s, e, fid)
        except RangeError:
            continue
        applied.append((s, e, fid))
    return content, sorted(applied)


def test_same_result_as_the_one_by_one_path():
    rng = random.Random(7)
    for _ in range(200):
        content = []
        for i in range(rng.randint(1, 6)):
            kind = rng.random()
            if kind < 0.15:
                content.append({"type": "hardBreak"})
            elif kind < 0.25:
                content.append({"type": "docAtom", "attrs": {"kind": "image", "label": "Imagem"}})
            else:
                text = "".join(rng.choice("abc 12.,") for _ in range(rng.randint(1, 12)))
                node = {"type": "text", "text": text}
                if i % 2:
                    node["marks"] = [{"type": "bold"}]
                content.append(node)
        n = len(inline_text(content))
        spans, pos = [], 0
        while pos < n - 1 and len(spans) < 5:
            s = rng.randint(pos, n - 1)
            e = rng.randint(s + 1, min(n, s + 6))
            spans.append((s, e, f"f{len(spans)}"))
            pos = e
        fast, applied = apply_fields(content, spans)
        slow, slow_applied = _one_by_one(content, spans)
        assert applied == slow_applied
        assert normalize_nodes(fast) == normalize_nodes(slow)


def test_overlaps_are_skipped_and_text_is_kept():
    content = [{"type": "text", "text": "CPF 529.982.247-25 e R$ 10,00"}]
    out, applied = apply_fields(content, [(4, 18, "cpf"), (10, 20, "x"), (21, 29, "valor")])
    assert applied == [(4, 18, "cpf"), (21, 29, "valor")]
    assert inline_text(out) == "CPF 529.982.247-25 e R$ 10,00"
    assert [n["type"] for n in out] == ["text", "field", "text", "field"]


def test_thousands_of_spans_in_one_paragraph_is_fast():
    import time

    text = "01/10/2026 529.982.247-25 R$ 1,00 " * 1200  # ~40 mil caracteres, 3.600 trechos
    content = [{"type": "text", "text": text}]
    spans = []
    for i in range(1200):
        base = i * 34
        spans += [(base, base + 10, "d"), (base + 11, base + 25, "c"), (base + 26, base + 33, "v")]
    t = time.perf_counter()
    out, applied = apply_fields(content, spans)
    assert len(applied) == 3600 and inline_text(out) == text
    assert time.perf_counter() - t < 2
