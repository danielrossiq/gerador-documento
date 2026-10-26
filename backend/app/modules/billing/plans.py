"""Planos comerciais e os limites que cada um aplica (fonte: plans.json, idêntico ao do site — teste de paridade)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PLANS_FILE = Path(__file__).with_name("plans.json")
FREE = "gratis"

# chave do limite no plano -> nome do limite usado pelo app (Ctx.limit / DEFAULT_LIMITS)
LIMIT_KEYS = {
    "docs_per_month": "max_docs_per_month",
    "models": "max_generators",
    "batch_rows": "max_batch_rows",
    "ai_analyses_per_month": "max_ai_actions_per_month",
    "signatures_per_month": "max_signatures_per_month",
}
UNLIMITED_MODELS = 10_000  # "modelos ilimitados" ainda tem um teto técnico de proteção


@lru_cache
def plans() -> dict[str, dict[str, Any]]:
    data = json.loads(PLANS_FILE.read_text(encoding="utf-8"))
    return {p["id"]: p for p in data["plans"]}


def plan_limits(plan_id: str) -> dict[str, int]:
    p = plans().get(plan_id) or plans()[FREE]
    out: dict[str, int] = {}
    for key, name in LIMIT_KEYS.items():
        v = p["limits"].get(key)
        out[name] = UNLIMITED_MODELS if v is None else int(v)
    return out


def price_cents(plan_id: str, cycle: str) -> int:
    """Total cobrado no ciclo, em centavos (anual = 12 × preço mensal do anual)."""
    p = plans()[plan_id]
    if cycle == "anual":
        return round(p["annualMonthly"] * 12 * 100)
    return round(p["monthly"] * 100)
