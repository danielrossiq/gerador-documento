"""Comparação de modelos de IA (OpenRouter) no conjunto ouro: acerto × custo × tempo, com teto de gasto.

Cada modelo analisa os 15 documentos fictícios do jeito que a análise real faz (regras determinísticas + IA,
`resolve_overlaps`, numeração de repetidos) e é medido com as mesmas métricas do baseline. Os preços vêm ao vivo
de GET /models (público) e servem para o teto: antes de cada chamada, o custo máximo dela (entrada estimada pelo
tamanho + saída máxima pedida) somado ao já gasto não pode passar de --budget. Depois da chamada vale o custo
informado pela API.

Uso (chave em ~/.minuta/openrouter.key ou OPENROUTER_KEY_FILE/OPENROUTER_API_KEY):
  python -m app.cli ai-eval models --models anthropic/claude-haiku-5.5,google/gemini-2.5-flash-lite --budget 1.5
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.adapters.ai.base import AISuggestionRequest, AIUnavailable, BlockText
from app.adapters.ai.openrouter import (
    FIELDS_SYSTEM,
    OpenRouterChat,
    OpenRouterFieldProvider,
    build_blocks_prompt,
    max_output_tokens,
    read_openrouter_key,
)
from app.docx_engine.parse import parse_docx
from app.eval import baseline
from app.eval.gold import GOLD, GoldDoc
from app.modules.suggestions.rules import describe_location


@dataclass
class ModelRun:
    model: str
    price_in: float  # US$ por token
    price_out: float
    cost_usd: float = 0.0
    seconds: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


class _Budget:
    def __init__(self, cap: float) -> None:
        self.cap = cap
        self.spent = 0.0

    def check(self, worst: float) -> None:
        if self.spent + worst > self.cap + 1e-9:
            raise SystemExit(f"Teto da avaliação (US$ {self.cap:.2f}) seria ultrapassado; gasto até aqui US$ {self.spent:.4f}.")


class _MeteredProvider(OpenRouterFieldProvider):
    """Provedor que confere o teto antes de cada chamada e soma o custo informado depois."""

    def __init__(self, chat: OpenRouterChat, run: ModelRun, budget: _Budget) -> None:
        super().__init__(chat, run.model)
        self.run, self.budget = run, budget

    def suggest(self, request: AISuggestionRequest):  # type: ignore[no-untyped-def]
        prompt, chars, _ = build_blocks_prompt(request)
        tokens_in = (len(FIELDS_SYSTEM) + len(prompt)) / 2.5  # estimativa conservadora de tokens de entrada
        worst = tokens_in * self.run.price_in + max_output_tokens(chars) * self.run.price_out
        self.budget.check(worst)
        t0 = time.monotonic()
        try:
            return super().suggest(request)
        finally:
            cost = self.last_cost_usd if self.last_cost_usd is not None else worst
            self.last_cost_usd = None
            self.run.cost_usd += cost
            self.budget.spent += cost
            self.run.seconds.append(time.monotonic() - t0)


def prices(models: list[str]) -> dict[str, tuple[float, float]]:
    data = httpx.get("https://openrouter.ai/api/v1/models", timeout=60).json()["data"]
    out = {}
    for m in data:
        if m["id"] in models:
            p = m.get("pricing") or {}
            out[m["id"]] = (float(p.get("prompt") or 0), float(p.get("completion") or 0))
    missing = [m for m in models if m not in out]
    if missing:
        raise SystemExit(f"Modelos não encontrados na OpenRouter: {', '.join(missing)}")
    return out


def _empty_result(doc: GoldDoc) -> baseline.DocResult:
    """Documento cuja chamada falhou conta como zero acerto (não some da média)."""

    class _NoHits:
        name = "falhou"

        def suggest(self, request):  # type: ignore[no-untyped-def]
            from app.adapters.ai.base import AISuggestionResult

            return AISuggestionResult([], "falhou")

    return baseline.evaluate(doc, _NoHits())


def run(models: list[str], budget_usd: float) -> list[ModelRun]:
    key = read_openrouter_key(os.environ.get("OPENROUTER_API_KEY"), os.environ.get("OPENROUTER_KEY_FILE") or str(Path.home() / ".minuta" / "openrouter.key"))
    if not key:
        raise SystemExit("Chave da OpenRouter não encontrada (OPENROUTER_API_KEY ou arquivo da chave).")
    table = prices(models)
    budget = _Budget(budget_usd)
    chat = OpenRouterChat(key, timeout=120, max_retries=3)
    runs: list[ModelRun] = []
    for m in models:
        r = ModelRun(m, *table[m])
        provider = _MeteredProvider(chat, r, budget)
        results = []
        for d in GOLD:
            try:
                results.append(baseline.evaluate(d, provider))
            except AIUnavailable as e:
                r.failures.append(f"{d.id}: {e.code}")
                results.append(_empty_result(d))
        r.summary = baseline.summarize(results)
        s = r.summary["summary"]
        print(
            f"{m:44} recall {s['recall_occurrences_pct']:5}% · precisão {s['precision_pct']:5}% · campos {s['recall_fields_pct']:5}% "
            f"· US$ {r.cost_usd:.4f} ({r.cost_usd / len(GOLD):.5f}/doc) · {sum(r.seconds) / max(1, len(r.seconds)):.1f}s/doc"
            + (f" · {len(r.failures)} falha(s)" if r.failures else "")
        )
        runs.append(r)
    print(f"Gasto total da avaliação: US$ {budget.spent:.4f} (teto US$ {budget_usd:.2f})")
    return runs


def write_report(runs: list[ModelRun], base: dict, out_md: Path, out_json: Path | None) -> None:
    b = base["summary"]
    rows = [
        "| Modelo | Recall ocorr. | Precisão | Recall campos | Tipo | Agrupamento | Custo/doc (US$) | Tempo/doc | Falhas |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| regras + heurísticas locais (sem IA) | {b['recall_occurrences_pct']}% | {b['precision_pct']}% | {b['recall_fields_pct']}% | "
        f"{b['type_accuracy_pct']}% | {b['grouping_pct']}% | 0 | — | — |",
    ]
    for r in runs:
        s = r.summary["summary"]
        rows.append(
            f"| `{r.model}` | {s['recall_occurrences_pct']}% | {s['precision_pct']}% | {s['recall_fields_pct']}% | {s['type_accuracy_pct']}% | "
            f"{s['grouping_pct']}% | {r.cost_usd / len(GOLD):.5f} | {sum(r.seconds) / max(1, len(r.seconds)):.1f} s | {len(r.failures)} |"
        )
    text = "\n".join(
        [
            "# Avaliação de modelos de IA no conjunto ouro",
            "",
            f"Gerado por `python -m app.cli ai-eval models`. {len(GOLD)} documentos fictícios (app/eval/gold.py); cada modelo roda "
            "junto com as regras determinísticas, como na análise real. Custo = informado pela OpenRouter.",
            "",
            *rows,
            "",
        ]
    )
    out_md.write_text(text, encoding="utf-8")
    if out_json:
        out_json.write_text(
            json.dumps([{"model": r.model, "cost_usd": r.cost_usd, "failures": r.failures, **r.summary} for r in runs], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main(models: list[str], budget: float, md: Path | None, js: Path | None) -> int:
    runs = run(models, budget)
    if md:
        write_report(runs, baseline.run(), md, js)
    return 0


# usado pelos testes: a mesma montagem de blocos que a análise real
def gold_blocks(doc: GoldDoc) -> list[BlockText]:
    parsed = parse_docx(doc.docx())
    return [BlockText(b.key, b.text, describe_location(b.key)) for b in parsed.blocks if b.kind == "paragraph" and b.text.strip()]
