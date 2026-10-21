from __future__ import annotations

from app.adapters.ai.anthropic import AnthropicMessagesProvider
from app.adapters.ai.base import PROMPT_VERSION, AIFieldSuggestionProvider
from app.adapters.ai.local import LocalHeuristicProvider
from app.adapters.ai.openrouter import OpenRouterChat, OpenRouterFieldProvider, read_openrouter_key
from app.adapters.ai.typesafe import RoleClassifierUnavailable, TypeSafeRoleClassifier
from app.core.config import get_settings


def get_ai_provider() -> AIFieldSuggestionProvider | None:
    """`auto`: OpenRouter se houver chave, senão Anthropic se houver chave, senão heurísticas locais (explícito na
    UI). `none`: só regras."""
    s = get_settings()
    choice = s.ai_provider
    if choice == "none":
        return None
    if not s.external_ai_enabled:  # trava geral: nenhum provedor externo, mesmo com chave configurada
        return LocalHeuristicProvider()
    openrouter_key = read_openrouter_key(s.openrouter_api_key, s.openrouter_key_file)
    if choice == "auto":
        choice = "openrouter" if openrouter_key else ("anthropic" if s.ai_api_key else "local")
    if choice == "openrouter":
        if not openrouter_key:
            return LocalHeuristicProvider()
        chat = OpenRouterChat(openrouter_key, base_url=s.openrouter_base_url, timeout=max(s.ai_timeout_seconds, 60), referer=s.public_web_url)
        return OpenRouterFieldProvider(chat, s.openrouter_model)
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
