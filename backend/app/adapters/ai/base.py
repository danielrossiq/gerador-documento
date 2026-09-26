"""Contrato dos provedores de sugestão de campos. A regra de negócio depende só desta interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from app.modules.fields.types import FIELD_TYPES

PROMPT_VERSION = "v1"


@dataclass(frozen=True)
class BlockText:
    key: str
    text: str
    location: str  # descrição legível: "Cláusula 2", "Tabela 1", "Cabeçalho"…


@dataclass
class AISuggestionRequest:
    blocks: list[BlockText]
    language: str = "pt-BR"
    max_chars: int = 60_000


class RawSuggestion(BaseModel):
    """Formato validado da resposta. Qualquer item fora do schema é descartado."""

    block: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    type: str
    confidence: float = Field(ge=0, le=1)
    reason: str | None = Field(default=None, max_length=300)

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in FIELD_TYPES:
            raise ValueError(f"tipo desconhecido: {v}")
        return v


class RawSuggestionList(BaseModel):
    suggestions: list[dict] = Field(default_factory=list)


@dataclass
class AISuggestionResult:
    suggestions: list[RawSuggestion]
    provider: str
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    chars_sent: int = 0
    duration_ms: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


class AIUnavailable(Exception):
    """Provedor indisponível (rede, quota, timeout). A análise segue só com regras determinísticas."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AIFieldSuggestionProvider(Protocol):
    name: str
    model: str | None

    def suggest(self, request: AISuggestionRequest) -> AISuggestionResult: ...
