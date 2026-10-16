"""Normalização, validação e formatação de valores por tipo de campo (pt-BR).

Valores canônicos: texto → str; número/moeda → decimal em str ("1234.50"); data → ISO; CPF/CNPJ/CEP/
telefone → só caracteres significativos; e-mail → minúsculo; sim/não e checkbox → bool; lista → valor
interno da opção. A mesma lógica existe no cliente (shared/field-vectors.json valida as duas).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.fields import extenso
from app.modules.fields.types import FieldDef
from app.modules.fields.validators import (
    clean_cnpj,
    digits,
    format_cep,
    format_cnpj,
    format_cpf,
    format_oab,
    format_phone,
    is_valid_cnpj,
    is_valid_cpf,
    is_valid_email,
    mask_regex,
    normalize_oab,
    normalize_phone,
)

MONTHS = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]
TRUE_WORDS = {"sim", "s", "yes", "y", "true", "1", "x", "verdadeiro", "v"}
FALSE_WORDS = {"não", "nao", "n", "no", "false", "0", "falso", "f"}
MAX_SHORT = 255
MAX_LONG = 20000


@dataclass
class RowResult:
    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors


def is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def parse_decimal(raw: Any) -> Decimal | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    s = str(raw).strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if 20000 < raw < 80000:  # serial do Excel
            return date(1899, 12, 30) + timedelta(days=int(raw))
        return None
    s = str(raw).strip()
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", s):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})", s):
            y = int(m[3])
            if y < 100:
                y += 2000 if y < 70 else 1900
            return date(y, int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None


def br_number(d: Decimal, decimals: int | None) -> str:
    if decimals is not None:
        d = d.quantize(Decimal(1).scaleb(-decimals))
    sign = "-" if d < 0 else ""
    ip, _, fp = format(abs(d), "f").partition(".")
    ip = f"{int(ip):,}".replace(",", ".")
    return sign + ip + ("," + fp if fp else "")


def canonical_decimal(value: Any) -> Decimal | None:
    """Lê um decimal CANÔNICO ("1234.567": ponto = casa decimal, sem milhar). Não usa a regra pt-BR de entrada."""
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _dec_str(d: Decimal, decimals: int | None) -> str:
    if decimals is not None:
        return format(d.quantize(Decimal(1).scaleb(-decimals)), "f")
    return format(d.normalize(), "f")


def _to_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in TRUE_WORDS:
        return True
    if s in FALSE_WORDS:
        return False
    return None


def _cfg_num(cfg: Mapping[str, Any], key: str) -> Decimal | None:
    v = cfg.get(key)
    return None if v in (None, "") else parse_decimal(v)


def normalize_value(fd: FieldDef, raw: Any) -> tuple[Any, str | None]:
    """Retorna (valor_canônico, mensagem_de_erro). Vazio e opcional → (None, None)."""
    t = fd.type
    if t == "checkbox":
        if is_empty(raw):
            return False, ("Marque esta opção para continuar." if fd.required else None)
        b = _to_bool(raw)
        if b is None:
            return False, "Valor inválido para caixa de seleção (use sim/não)."
        if fd.required and not b:
            return False, "Marque esta opção para continuar."
        return b, None
    if is_empty(raw):
        return None, ("Campo obrigatório." if fd.required else None)

    if t == "text_short":
        s = re.sub(r"\s*[\r\n]+\s*", " ", str(raw)).strip()
        max_len = int(fd.config.get("max_length") or MAX_SHORT)
        if len(s) > max_len:
            return s, f"Use no máximo {max_len} caracteres."
        if fd.mask and not mask_regex(fd.mask).fullmatch(s):
            return s, f"Formato inválido. Use o padrão {fd.mask}."
        return s, None
    if t == "text_long":
        s = str(raw).replace("\r\n", "\n").replace("\r", "\n").strip()
        return (s, None) if len(s) <= MAX_LONG else (s, f"Use no máximo {MAX_LONG} caracteres.")
    if t in ("number", "currency"):
        d = parse_decimal(raw)
        if d is None:
            return str(raw), "Informe um número válido (ex.: 1.234,56)."
        decimals = (
            2
            if t == "currency"
            else (int(fd.config["decimals"]) if fd.config.get("decimals") not in (None, "") else None)
        )
        canonical = _dec_str(d, decimals)
        lo, hi = _cfg_num(fd.config, "min"), _cfg_num(fd.config, "max")
        if t == "currency" and d < 0 and lo is None:
            return canonical, "O valor não pode ser negativo."
        if lo is not None and d < lo:
            return canonical, f"O valor mínimo é {br_number(lo, decimals)}."
        if hi is not None and d > hi:
            return canonical, f"O valor máximo é {br_number(hi, decimals)}."
        return canonical, None
    if t == "date":
        d2 = parse_date(raw)
        return (d2.isoformat(), None) if d2 else (str(raw), "Data inválida. Use dd/mm/aaaa.")
    if t == "cpf":
        s = digits(str(raw))
        return (s, None) if is_valid_cpf(s) else (str(raw), "CPF inválido.")
    if t == "cnpj":
        s = clean_cnpj(str(raw))
        return (s, None) if is_valid_cnpj(s) else (str(raw), "CNPJ inválido.")
    if t == "cep":
        s = digits(str(raw))
        return (s, None) if len(s) == 8 else (str(raw), "CEP inválido. Use 8 dígitos.")
    if t == "email":
        s = str(raw).strip().lower()
        return (s, None) if is_valid_email(s) else (str(raw), "E-mail inválido.")
    if t == "phone":
        p = normalize_phone(str(raw))
        return (p, None) if p else (str(raw), "Telefone inválido. Use DDD + número.")
    if t == "oab":
        o = normalize_oab(str(raw))
        return (o, None) if o else (str(raw), "OAB inválida. Use UF e número (ex.: OAB/ES 12.345).")
    if t == "select":
        s = str(raw).strip()
        for o in fd.options:
            if o.value == s:
                return o.value, None
        low = s.lower()
        for o in fd.options:
            if o.label.lower() == low or o.value.lower() == low:
                return o.value, None
        return s, "Opção inválida. Escolha uma das opções da lista."
    if t == "yes_no":
        b = _to_bool(raw)
        return (b, None) if b is not None else (None, "Responda Sim ou Não.")
    return str(raw), f"Tipo de campo desconhecido: {t}."


def format_value(fd: FieldDef, value: Any) -> str:
    """Texto que vai para o documento."""
    t = fd.type
    if t == "checkbox":
        checked = bool(value)
        return str(fd.config.get("checked_text", "☒") if checked else fd.config.get("unchecked_text", "☐"))
    if is_empty(value):
        return ""
    if t == "currency":
        d = canonical_decimal(value)
        if d is None:
            return str(value)
        short = f"R$ {br_number(d, 2)}"
        if fd.config.get("currency_format") == "words" and abs(d) <= extenso.MAX_INTEGER:
            return f"{short} ({extenso.currency_words(d)})"
        return short
    if t == "number":
        d = canonical_decimal(value)
        dec = fd.config.get("decimals")
        return br_number(d, int(dec) if dec not in (None, "") else None) if d is not None else str(value)
    if t == "date":
        d2 = parse_date(value)
        if d2 is None:
            return str(value)
        if fd.config.get("date_format") == "long":
            return f"{d2.day} de {MONTHS[d2.month - 1]} de {d2.year}"
        if fd.config.get("date_format") == "words":
            return extenso.date_words(d2.day, MONTHS[d2.month - 1], d2.year)
        return d2.strftime("%d/%m/%Y")
    if t == "cpf":
        return format_cpf(str(value)) if len(str(value)) == 11 else str(value)
    if t == "cnpj":
        return format_cnpj(str(value)) if len(str(value)) == 14 else str(value)
    if t == "cep":
        return format_cep(str(value)) if len(str(value)) == 8 else str(value)
    if t == "phone":
        return format_phone(str(value)) if len(str(value)) in (10, 11) else str(value)
    if t == "oab":
        return format_oab(str(value))
    if t == "select":
        return next((o.label for o in fd.options if o.value == value), str(value))
    if t == "yes_no":
        return "Sim" if value is True else "Não"
    return str(value)


def validate_row(
    defs: Sequence[FieldDef], row: Mapping[str, Any], *, apply_defaults: bool = True
) -> RowResult:
    """Normaliza uma linha (por nome de campo). Campos desconhecidos são ignorados."""
    result = RowResult()
    for fd in defs:
        raw = row.get(fd.name)
        if apply_defaults and is_empty(raw) and not is_empty(fd.default):
            raw = fd.default
        value, err = normalize_value(fd, raw)
        result.values[fd.name] = value
        if err:
            result.errors[fd.name] = err
    return result


def today_utc() -> date:
    return datetime.now(UTC).date()
