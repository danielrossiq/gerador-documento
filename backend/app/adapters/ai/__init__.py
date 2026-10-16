from __future__ import annotations

from app.adapters.ai.anthropic import AnthropicMessagesProvider
from app.adapters.ai.base import PROMPT_VERSION, AIFieldSuggestionProvider
from app.adapters.ai.local import LocalHeuristicProvider
from app.adapters.ai.typesafe import RoleClassifierUnavailable, TypeSafeRoleClassifier
from app.core.config import get_settings


def get_ai_provider() -> AIFieldSuggestionProvider | None:
    """`auto`: API se houver chave; senão heurísticas locais (explícito na UI). `none`: só regras."""
    s = get_settings()
    choice = s.ai_provider
    if choice == "none":
        return None
    if not s.external_ai_enabled:  # trava do piloto: nenhum provedor externo, mesmo com chave configurada
        return LocalHeuristicProvider()
    if choice == "auto":
        choice = "anthropic" if s.ai_api_key else "local"
    if choice == "anthropic":
        if not s.ai_api_key:
            return None
        return AnthropicMessagesProvider(
            s.ai_api_key, s.ai_base_url, s.ai_model, s.ai_timeout_seconds, s.ai_max_retries
        )
    return LocalHeuristicProvider()


def get_role_classifier() -> TypeSafeRoleClassifier | None:
    """`None` sem `TYPESAFE_API_KEY` — o auto-detect de kits cai na heurística local (D24)."""
    s = get_settings()
    if not s.external_ai_enabled or not s.typesafe_api_key:
        return None
    return TypeSafeRoleClassifier(
        s.typesafe_api_key, s.typesafe_base_url, s.typesafe_model, s.typesafe_timeout_seconds
    )


__all__ = [
    "PROMPT_VERSION",
    "AIFieldSuggestionProvider",
    "AnthropicMessagesProvider",
    "LocalHeuristicProvider",
    "RoleClassifierUnavailable",
    "TypeSafeRoleClassifier",
    "get_ai_provider",
    "get_role_classifier",
]
