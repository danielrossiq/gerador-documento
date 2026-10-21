"""Ponto único das chamadas pagas de IA do produto (OpenRouter): trava geral, chave, preço, teto e cota.

Ordem em toda chamada: EXTERNAL_AI_ENABLED → chave → preço do modelo → custo máximo da chamada → reserva no teto
(por chamada, mensal global e cota mensal do workspace) → chamada → acerto com o custo informado.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.ai.base import AIUnavailable
from app.adapters.ai.openrouter import ChatResult, OpenRouterChat, read_openrouter_key
from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules import ai_budget

log = get_logger(__name__)

FALLBACK_PRICE = (1.0e-6, 5.0e-6)  # US$/token: conservador, se a tabela pública não responder
_PRICES: dict[str, tuple[float, float, float]] = {}  # modelo -> (entrada, saída, quando)
PRICE_TTL_S = 6 * 3600


class AIDisabled(Exception):
    """IA externa desligada ou sem chave: o recurso some da interface e a análise usa só regras locais."""


def configured_key() -> str | None:
    s = get_settings()
    return read_openrouter_key(s.openrouter_api_key, s.openrouter_key_file)


def enabled() -> bool:
    return bool(get_settings().external_ai_enabled and configured_key())


def model_prices(model: str) -> tuple[float, float]:
    cached = _PRICES.get(model)
    if cached and time.time() - cached[2] < PRICE_TTL_S:
        return cached[0], cached[1]
    try:
        data = httpx.get(f"{get_settings().openrouter_base_url}/models", timeout=15).json()["data"]
        for m in data:
            if m["id"] == model:
                p = m.get("pricing") or {}
                _PRICES[model] = (float(p.get("prompt") or 0), float(p.get("completion") or 0), time.time())
                return _PRICES[model][0], _PRICES[model][1]
    except (httpx.HTTPError, KeyError, ValueError):
        log.warning("ia_tabela_precos_indisponivel")
    return FALLBACK_PRICE


def worst_cost(model: str, prompt_chars: int, max_tokens: int) -> Decimal:
    pin, pout = model_prices(model)
    tokens_in = prompt_chars / 2.5  # português ≈ 3–4 caracteres por token; 2,5 deixa folga
    return Decimal(str(round(tokens_in * pin + max_tokens * pout, 6))) or Decimal("0.000001")


def chat_client() -> OpenRouterChat:
    key = configured_key()
    if not get_settings().external_ai_enabled or not key:
        raise AIDisabled()
    s = get_settings()
    return OpenRouterChat(key, base_url=s.openrouter_base_url, timeout=s.ai_timeout_seconds, referer=s.public_web_url)


def guarded_chat(
    *,
    purpose: str,
    workspace_id: uuid.UUID | None,
    quota: int | None,
    system: str,
    user: str,
    schema_name: str,
    schema: dict[str, Any],
    max_tokens: int,
) -> ChatResult:
    """Chamada com teto e cota. Levanta AIDisabled, ai_budget.BudgetExceeded ou AIUnavailable."""
    client = chat_client()
    s = get_settings()
    model = s.openrouter_assist_model if purpose in ("fill", "review") else s.openrouter_model
    spend_id = ai_budget.reserve(
        model, purpose, worst_cost(model, len(system) + len(user), max_tokens), workspace_id=workspace_id, quota=quota
    )
    try:
        res = client.complete(model=model, system=system, user=user, schema_name=schema_name, schema=schema, max_tokens=max_tokens)
    except AIUnavailable:
        ai_budget.fail(spend_id)
        raise
    if not ai_budget.settle(spend_id, res.cost_usd, res.tokens_in, res.tokens_out):
        log.warning("ia_custo_acima_da_reserva", extra={"purpose": purpose, "model": res.model})
    return res
