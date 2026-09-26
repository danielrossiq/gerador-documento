"""Definição leve de campo (desacoplada do ORM) e regras de nomeação."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

FIELD_TYPES = (
    "text_short",
    "text_long",
    "number",
    "currency",
    "date",
    "cpf",
    "cnpj",
    "cep",
    "email",
    "phone",
    "select",
    "yes_no",
    "checkbox",
)
TYPE_LABELS = {
    "text_short": "Texto curto",
    "text_long": "Texto longo",
    "number": "Número",
    "currency": "Moeda (R$)",
    "date": "Data",
    "cpf": "CPF",
    "cnpj": "CNPJ",
    "cep": "CEP",
    "email": "E-mail",
    "phone": "Telefone",
    "select": "Lista suspensa",
    "yes_no": "Sim/Não",
    "checkbox": "Checkbox",
}
RESERVED_NAMES = frozenset({"hoje", "linha", "gerador"})  # tokens especiais do nome de arquivo
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# Palavras de papel/parte usadas para relabelar sugestões (CPF/CNPJ/nome) que aparecem logo depois delas no
# texto — ex.: "CONTRATANTE: João da Silva, CPF 123...". Compartilhado entre as regras determinísticas
# (app.modules.suggestions.rules) e o provedor local de sugestões (app.adapters.ai.local) para não manter
# duas listas divergentes.
ROLE_WORDS = (
    "contratante",
    "contratada",
    "contratado",
    "locador",
    "locadora",
    "locatário",
    "locatária",
    "outorgante",
    "outorgado",
    "outorgada",
    "comprador",
    "compradora",
    "vendedor",
    "vendedora",
    "empregador",
    "empregado",
    "empregada",
    "declarante",
    "cedente",
    "cessionário",
    "fiador",
    "promitente",
)
_ROLE_WORDS_RE = re.compile("|".join(ROLE_WORDS), re.I)


def role_before(text: str, start: int, window: int = 260) -> str | None:
    """Última palavra de papel (ROLE_WORDS) encontrada nos `window` caracteres antes de `start`, ou None."""
    matches = list(_ROLE_WORDS_RE.finditer(text[max(0, start - window) : start]))
    return matches[-1].group(0).lower() if matches else None


@dataclass(frozen=True)
class OptionDef:
    label: str
    value: str


@dataclass(frozen=True)
class FieldDef:
    id: str
    name: str
    label: str
    type: str
    required: bool = False
    default: Any = None
    options: tuple[OptionDef, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)
    mask: str | None = None
    include_in_batch: bool = True
    position: int = 0
    group: str | None = None
    description: str | None = None
    example: str | None = None

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "options": [{"label": o.label, "value": o.value} for o in self.options],
            "config": dict(self.config),
            "mask": self.mask,
            "include_in_batch": self.include_in_batch,
            "position": self.position,
            "group": self.group,
            "description": self.description,
            "example": self.example,
        }

    @classmethod
    def from_snapshot(cls, d: Mapping[str, Any]) -> FieldDef:
        return cls(
            id=str(d["id"]),
            name=d["name"],
            label=d["label"],
            type=d["type"],
            required=bool(d.get("required")),
            default=d.get("default"),
            options=tuple(OptionDef(o["label"], o["value"]) for o in d.get("options", [])),
            config=d.get("config") or {},
            mask=d.get("mask"),
            include_in_batch=bool(d.get("include_in_batch", True)),
            position=int(d.get("position", 0)),
            group=d.get("group"),
            description=d.get("description"),
            example=d.get("example"),
        )


def normalize_key(text: str) -> str:
    """Forma canônica para comparar nomes/rótulos por proximidade (sem acentos, só a-z0-9, sem parênteses).

    Usada para casar colunas de planilha com campos (importação) e para agrupar campos parecidos entre
    geradores diferentes (kits — ver `app.modules.kits.matching`).
    """
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def to_snake_case(text: str, fallback: str = "campo") -> str:
    """'Nome do contratante' → 'nome_do_contratante' (sem acentos, só a-z0-9_)."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    snake = re.sub(r"[^a-z0-9]+", "_", norm.lower()).strip("_")
    if not snake:
        snake = fallback
    if not snake[0].isalpha():
        snake = f"{fallback}_{snake}"
    return snake[:60].rstrip("_")


def unique_name(base: str, existing: Iterable[str]) -> str:
    taken = set(existing) | RESERVED_NAMES
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def option_value_from_label(label: str) -> str:
    return to_snake_case(label, fallback="opcao")
