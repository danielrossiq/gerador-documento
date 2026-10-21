"""Baseline do conjunto ouro: o que as regras determinísticas e as heurísticas locais já acertam (sem rede, sem IA).

Mesmo caminho da análise real (`suggestions.service.analyze_version`): o .docx passa pelo parser do app, as regras
e o provedor local geram trechos, `resolve_overlaps` escolhe entre sobrepostos e `_number_duplicate_hits` numera
campos repetidos. Cada trecho sugerido é comparado com as ocorrências anotadas.

Métricas (por documento e no total):
- recall de ocorrências: ocorrências anotadas encontradas com o trecho EXATO;
- recall parcial: o trecho sugerido só se sobrepõe à ocorrência (pegou de menos ou de mais);
- precisão: trechos sugeridos que batem exatamente com alguma ocorrência anotada;
- recall de campos: campos com ao menos uma ocorrência exata;
- tipo: entre os acertos exatos, tipo sugerido igual ao anotado;
- agrupamento: campos com 2+ ocorrências em que todas foram achadas sob o MESMO nome de campo.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.adapters.ai.base import AISuggestionRequest, BlockText
from app.adapters.ai.local import LocalHeuristicProvider
from app.docx_engine.parse import parse_docx
from app.eval.gold import GOLD, GoldDoc
from app.modules.suggestions.rules import Hit, describe_location, detect_rules, resolve_overlaps


@dataclass
class DocResult:
    id: str
    category: str
    occurrences: int
    exact: int
    partial: int
    hits: int
    hits_exact: int
    fields: int
    fields_found: int
    type_ok: int
    groups: int
    groups_ok: int
    missed: list[str] = field(default_factory=list)  # campos sem nenhum acerto exato
    extra: list[str] = field(default_factory=list)  # trechos sugeridos que não são campo anotado


def suggest(doc: GoldDoc) -> list[Hit]:
    from app.modules.suggestions.service import _number_duplicate_hits

    parsed = parse_docx(doc.docx())
    blocks = [(b.key, b.text) for b in parsed.blocks if b.kind == "paragraph" and b.text.strip()]
    by_key = dict(blocks)
    hits = list(detect_rules(blocks))
    res = LocalHeuristicProvider().suggest(
        AISuggestionRequest([BlockText(k, t, describe_location(k)) for k, t in blocks])
    )
    for raw in res.suggestions:
        text = by_key.get(raw.block, "")
        start = text.find(raw.text)
        while start >= 0:
            hits.append(
                Hit(
                    raw.block,
                    start,
                    start + len(raw.text),
                    raw.text,
                    raw.name,
                    raw.label,
                    raw.type,
                    raw.confidence,
                    "local",
                    raw.reason or "",
                    None,
                )
            )
            start = text.find(raw.text, start + 1)
    return _number_duplicate_hits(resolve_overlaps(hits))


def evaluate(doc: GoldDoc) -> DocResult:
    rendered = dict(doc.render())
    hits = suggest(doc)
    for h in hits:  # o parser e o render têm de concordar: as chaves e o texto são a base da comparação
        assert rendered.get(h.block_key, "")[h.start : h.end] == h.text, (doc.id, h.block_key)
    types = {f.name: f.type for f in doc.fields}
    exact_hit: dict[int, Hit] = {}
    partial = 0
    matched_hits: set[int] = set()
    for i, o in enumerate(doc.occurrences):
        for j, h in enumerate(hits):
            if h.block_key != o.block:
                continue
            if (h.start, h.end) == (o.start, o.end):
                exact_hit[i] = h
                matched_hits.add(j)
                break
        else:
            if any(h.block_key == o.block and h.start < o.end and o.start < h.end for h in hits):
                partial += 1
    per_field: dict[str, list[Hit | None]] = {}
    for i, o in enumerate(doc.occurrences):
        per_field.setdefault(o.field, []).append(exact_hit.get(i))
    groups = {n: hs for n, hs in per_field.items() if len(hs) > 1}
    return DocResult(
        id=doc.id,
        category=doc.category,
        occurrences=len(doc.occurrences),
        exact=len(exact_hit),
        partial=partial,
        hits=len(hits),
        hits_exact=len(matched_hits),
        fields=len(doc.fields),
        fields_found=sum(1 for hs in per_field.values() if any(hs)),
        type_ok=sum(1 for i, h in exact_hit.items() if h.type == types[doc.occurrences[i].field]),
        groups=len(groups),
        groups_ok=sum(1 for hs in groups.values() if all(hs) and len({h.name for h in hs if h}) == 1),
        missed=sorted(n for n, hs in per_field.items() if not any(hs)),
        extra=[f"{h.text} ({h.type})" for j, h in enumerate(hits) if j not in matched_hits],
    )


def _pct(a: int, b: int) -> float:
    return round(100 * a / b, 1) if b else 0.0


def run() -> dict:
    results = [evaluate(d) for d in GOLD]
    tot = {
        k: sum(getattr(r, k) for r in results)
        for k in (
            "occurrences",
            "exact",
            "partial",
            "hits",
            "hits_exact",
            "fields",
            "fields_found",
            "type_ok",
            "groups",
            "groups_ok",
        )
    }
    summary = {
        "documents": len(results),
        "recall_occurrences_pct": _pct(tot["exact"], tot["occurrences"]),
        "partial_occurrences_pct": _pct(tot["partial"], tot["occurrences"]),
        "precision_pct": _pct(tot["hits_exact"], tot["hits"]),
        "recall_fields_pct": _pct(tot["fields_found"], tot["fields"]),
        "type_accuracy_pct": _pct(tot["type_ok"], tot["exact"]),
        "grouping_pct": _pct(tot["groups_ok"], tot["groups"]),
        **tot,
    }
    by_type: dict[str, list[int]] = {}
    for d in GOLD:
        r = next(x for x in results if x.id == d.id)
        for f in d.fields:
            found, total = by_type.setdefault(f.type, [0, 0])
            by_type[f.type] = [found + (f.name not in r.missed), total + 1]
    return {
        "summary": summary,
        "recall_by_type_pct": {t: _pct(a, b) for t, (a, b) in sorted(by_type.items())},
        "documents": [asdict(r) for r in results],
    }


def write_report(data: dict, out: Path) -> None:
    s = data["summary"]
    lines = [
        "# Baseline do conjunto ouro (regras + heurísticas locais, sem IA)",
        "",
        "Gerado por `python -m app.cli ai-eval baseline`. 15 modelos fictícios (app/eval/gold.py).",
        "",
        "| Métrica | Valor | Meta do F1 |",
        "|---|---:|---:|",
        f"| Recall de ocorrências (trecho exato) | {s['recall_occurrences_pct']}% | ≥ 90% |",
        f"| Precisão | {s['precision_pct']}% | ≥ 90% |",
        f"| Recall de campos | {s['recall_fields_pct']}% | — |",
        f"| Tipo correto (entre acertos) | {s['type_accuracy_pct']}% | — |",
        f"| Agrupamento de ocorrências | {s['grouping_pct']}% | — |",
        f"| Ocorrências só parcialmente cobertas | {s['partial_occurrences_pct']}% | — |",
        "",
        "## Recall de campos por tipo",
        "",
        "| Tipo | Recall |",
        "|---|---:|",
        *[f"| {t} | {v}% |" for t, v in data["recall_by_type_pct"].items()],
        "",
        "## Por documento",
        "",
        "| Documento | Categoria | Recall ocorr. | Precisão | Campos achados | Não achados |",
        "|---|---|---:|---:|---:|---|",
        *[
            f"| {d['id']} | {d['category']} | {_pct(d['exact'], d['occurrences'])}% | {_pct(d['hits_exact'], d['hits'])}% | "
            f"{d['fields_found']}/{d['fields']} | {', '.join(d['missed'])} |"
            for d in data["documents"]
        ],
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main(json_out: Path | None, md_out: Path | None) -> int:
    data = run()
    if json_out:
        json_out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if md_out:
        write_report(data, md_out)
    s = data["summary"]
    print(
        f"baseline: recall {s['recall_occurrences_pct']}% · precisão {s['precision_pct']}% · campos {s['recall_fields_pct']}% · "
        f"tipo {s['type_accuracy_pct']}% · agrupamento {s['grouping_pct']}% ({s['documents']} documentos)"
    )
    return 0
