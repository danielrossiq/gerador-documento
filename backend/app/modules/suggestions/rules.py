"""Detecção determinística de campos (sem IA): CPF, CNPJ, CEP, telefone, e-mail, moeda, percentual e datas.

Funções puras sobre (chave_do_bloco, texto). Retornam trechos com offsets no texto do bloco.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.fields.extenso import currency_words
from app.modules.fields.normalize import MONTHS, normalize_value, parse_date
from app.modules.fields.types import FieldDef, role_before, to_snake_case
from app.modules.fields.validators import is_valid_cnpj, is_valid_cpf, normalize_oab, normalize_phone

RULES_VERSION = "r5"
_MONTH_RE = "|".join(MONTHS)
MONTH_OPTIONS = [{"label": m.capitalize(), "value": to_snake_case(m)} for m in MONTHS]
# "(cinco mil reais)" logo depois do valor: só letras/espaços/vírgulas/hífen e termina em real/reais/centavo(s)
_WORDS_AFTER_VALUE = re.compile(r"\s*\(\s*([a-záéíóúâêôãõç ,\-]{0,200}\b(?:reais|real|centavos?))\s*\)", re.I)
_CURRENCY_PROBE = FieldDef(id="", name="valor", label="Valor", type="currency")

# Qualificação das partes (procurações, contratos): estado civil e regime de bens viram listas prontas.
# (masculino, feminino); a lista sugerida segue o gênero do termo encontrado no documento.
_CIVIL_STATUS = (
    ["solteiro", "casado", "divorciado", "viúvo", "separado judicialmente", "em união estável"],
    ["solteira", "casada", "divorciada", "viúva", "separada judicialmente", "em união estável"],
)
_PROPERTY_REGIME = (
    [
        "comunhão parcial de bens",
        "comunhão universal de bens",
        "separação total de bens",
        "separação convencional de bens",
        "separação obrigatória de bens",
        "participação final nos aquestos",
    ],
) * 2
_QUALIFICATION = [
    (
        "estado_civil",
        "Estado civil",
        r"\b(?:solteir[oa]|casad[oa]|divorciad[oa]|viúv[oa]|separad[oa] judicialmente|em união estável)\b",
        _CIVIL_STATUS,
    ),
    (
        "regime_de_bens",
        "Regime de bens",
        r"\b(?:comunhão (?:parcial|universal) de bens|separação (?:total|obrigatória|convencional) de bens"
        r"|participação final nos aquestos)\b",
        _PROPERTY_REGIME,
    ),
]


def _is_feminine(term: str) -> bool:
    first = term.split()[0].lower()
    return first not in ("em",) and first.endswith("a")


def _norm_words(t: str) -> str:
    return re.sub(r"[\s,]+", " ", t.strip().lower())


def _words_match_value(amount: str, words: str) -> bool:
    """O extenso escrito no documento é o mesmo que o sistema geraria para o valor."""
    canonical, err = normalize_value(_CURRENCY_PROBE, amount)
    if err is not None or canonical is None:
        return False
    return _norm_words(words) == _norm_words(currency_words(Decimal(str(canonical))))


@dataclass
class Hit:
    block_key: str
    start: int
    end: int
    text: str
    name: str
    label: str
    type: str
    confidence: float
    source: str  # rule | local | ai
    reason: str
    config: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _with_role(base: str, label: str, role: str | None) -> tuple[str, str]:
    if not role:
        return base, label
    return f"{base}_{role}", f"{label} — {role.capitalize()}"


def detect_rules(blocks: Sequence[tuple[str, str]]) -> list[Hit]:
    hits: list[Hit] = []
    for key, text in blocks:
        if not text.strip():
            continue
        local: list[Hit] = []

        def add(
            m: re.Match[str],
            base: str,
            label: str,
            typ: str,
            conf: float,
            reason: str,
            config: dict[str, Any] | None = None,
            group: int = 0,
            role: bool = True,
            key: str = key,
            text: str = text,
            out: list[Hit] = local,
        ) -> None:
            s, e = m.start(group), m.end(group)
            name, lab = _with_role(base, label, role_before(text, s) if role else None)
            out.append(Hit(key, s, e, text[s:e], name, lab, typ, conf, "rule", reason, config))

        for m in re.finditer(r"(?<![\d.\-/])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\d\-/])|(?<!\d)\d{11}(?!\d)", text):
            valid = is_valid_cpf(m.group(0))
            formatted = "." in m.group(0)
            if valid:
                add(m, "cpf", "CPF", "cpf", 0.98, "CPF com dígitos verificadores válidos")
            elif formatted:
                add(m, "cpf", "CPF", "cpf", 0.55, "Parece um CPF, mas os dígitos verificadores não conferem")
        for m in re.finditer(
            r"(?<![\w.])[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}(?![\w])|(?<!\d)\d{14}(?!\d)",
            text,
        ):
            valid = is_valid_cnpj(m.group(0))
            if valid:
                add(m, "cnpj", "CNPJ", "cnpj", 0.98, "CNPJ com dígitos verificadores válidos")
            elif "/" in m.group(0):
                add(
                    m,
                    "cnpj",
                    "CNPJ",
                    "cnpj",
                    0.55,
                    "Parece um CNPJ, mas os dígitos verificadores não conferem",
                )
        # inscrição na OAB: "OAB/ES 12.345", "OAB/ES 12345", "OAB/ES nº 12.345-A" (o trecho inteiro vira o campo,
        # que sai como "OAB/ES 12.345"). "OAB/SP sob o nº …" fica de fora: trocar o trecho mudaria a redação.
        for m in re.finditer(
            r"\bOAB\s*[/\-]\s*[A-Z]{2}\s*(?:n[º°o.]?\s*)?(?:\d{1,3}(?:\.\d{3})+|\d{1,6})(?!\d|\.\d)(?:\s*-\s*[ABE]\b)?",
            text,
        ):
            if normalize_oab(m.group(0)):
                add(m, "oab", "OAB", "oab", 0.95, "Número de inscrição na OAB")
        for m in re.finditer(r"(?<![\d\-])\d{5}-\d{3}(?![\d\-])", text):
            add(m, "cep", "CEP", "cep", 0.9, "Formato de CEP (00000-000)", role=False)
        for m in re.finditer(r"(?<![\w.@])[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+", text):
            add(m, "email", "E-mail", "email", 0.95, "Endereço de e-mail", role=True)
        for m in re.finditer(r"(?<![\d\-])(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}(?![\d\-])", text):
            if normalize_phone(m.group(0)):
                add(m, "telefone", "Telefone", "phone", 0.85, "Telefone com DDD")
        for m in re.finditer(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?|R\$\s?\d+(?:,\d{2})?", text):
            w = _WORDS_AFTER_VALUE.match(text, m.end())
            if w is None:
                add(m, "valor", "Valor", "currency", 0.95, "Valor em reais", role=False)
                continue
            # valor seguido do extenso entre parênteses: um campo só, que gera os dois juntos
            reason = (
                "Valor em reais com o extenso entre parênteses"
                if _words_match_value(m.group(0), w.group(1))
                else "Valor em reais com extenso entre parênteses (o extenso do documento não confere com o "
                "valor; o documento gerado terá o extenso correto)"
            )
            s0, e0 = m.start(), w.end()
            local.append(
                Hit(key, s0, e0, text[s0:e0], "valor", "Valor", "currency", 0.96, "rule", reason,
                    {"currency_format": "words"})
            )  # fmt: skip
        for m in re.finditer(r"\d{1,3}(?:,\d{1,2})?(?=\s?%)", text):
            add(
                m,
                "percentual",
                "Percentual",
                "number",
                0.85,
                "Percentual (o símbolo % permanece no texto)",
                config={"decimals": 2 if "," in m.group(0) else 0},
                role=False,
            )
        for m in re.finditer(r"(?<![\d/])\d{1,2}/\d{1,2}/\d{2,4}(?![\d/])", text):
            if parse_date(m.group(0)):
                add(m, "data", "Data", "date", 0.92, "Data no formato dd/mm/aaaa", role=False)
        for m in re.finditer(rf"\b\d{{1,2}}\s+de\s+(?:{_MONTH_RE})\s+de\s+\d{{4}}\b", text, re.I):
            add(
                m, "data", "Data", "date", 0.9, "Data por extenso", config={"date_format": "long"}, role=False
            )
        for m in re.finditer(r"\b(?:19|20)\d{2}\b", text):
            # confiança abaixo das regras de data: se o ano estiver DENTRO de uma data já capturada acima
            # (ex.: os "2026" de "01/10/2026" ou "21 de outubro de 2026"), a data vence no resolve_overlaps
            # (mesmo bloco, mesmo trecho) — este ano avulso só sobrevive quando não faz parte de uma data.
            add(
                m,
                "ano",
                "Ano",
                "number",
                0.72,
                "Número de 4 dígitos (19xx/20xx) — parece um ano",
                config={"decimals": 0},
                role=False,
            )
        for m in re.finditer(rf"\b(?:{_MONTH_RE})\b", text, re.I):
            add(
                m,
                "mes",
                "Mês",
                "select",
                0.6,
                "Nome de mês avulso no texto",
                config={"options": MONTH_OPTIONS},
                role=False,
            )
        # qualificação das partes: a lista inteira, no gênero e na grafia do documento (minúsculas no meio da frase)
        for base, label, pattern, lists in _QUALIFICATION:
            for m in re.finditer(pattern, text, re.I):
                feminine = _is_feminine(m.group(0))
                options = lists[1] if feminine else lists[0]
                if m.group(0)[0].isupper():  # início de frase/linha: as opções seguem a mesma caixa
                    options = [o[0].upper() + o[1:] for o in options]
                add(
                    m,
                    base,
                    label,
                    "select",
                    0.8,
                    f"{label} na qualificação de uma parte (lista com todas as opções)",
                    config={"options": [{"label": o, "value": to_snake_case(o)} for o in options]},
                )

        hits.extend(resolve_overlaps(local))
    return hits


def resolve_overlaps(hits: list[Hit]) -> list[Hit]:
    """Mantém o de maior confiança (e maior extensão) quando dois trechos se sobrepõem no mesmo bloco."""
    chosen: list[Hit] = []
    for h in sorted(hits, key=lambda x: (-x.confidence, -(x.end - x.start), x.start)):
        if any(c.block_key == h.block_key and h.start < c.end and c.start < h.end for c in chosen):
            continue
        chosen.append(h)
    return sorted(chosen, key=lambda x: (x.block_key, x.start))


def describe_location(key: str) -> str:
    """Localização legível a partir da chave do bloco."""
    parts = key.split("/")
    head = parts[0]
    if head.startswith("header"):
        return "Cabeçalho"
    if head.startswith("footer"):
        return "Rodapé"
    m = re.fullmatch(r"body/t(\d+)/r(\d+)/c(\d+)(?:/.*)?", key)
    if m:
        return f"Tabela {m[1]} · linha {m[2]} · coluna {m[3]}"
    m = re.fullmatch(r"body/[pn](\d+)", key)
    if m:
        return f"Parágrafo {m[1]}"
    return "Documento"
