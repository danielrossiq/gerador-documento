"""Validadores de documentos e formatos brasileiros (funções puras)."""

from __future__ import annotations

import re

_CNPJ_W1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_W2 = [6, *_CNPJ_W1]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
VALID_DDD = frozenset(
    [
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "21",
        "22",
        "24",
        "27",
        "28",
        "31",
        "32",
        "33",
        "34",
        "35",
        "37",
        "38",
        "41",
        "42",
        "43",
        "44",
        "45",
        "46",
        "47",
        "48",
        "49",
        "51",
        "53",
        "54",
        "55",
        "61",
        "62",
        "63",
        "64",
        "65",
        "66",
        "67",
        "68",
        "69",
        "71",
        "73",
        "74",
        "75",
        "77",
        "79",
        "81",
        "82",
        "83",
        "84",
        "85",
        "86",
        "87",
        "88",
        "89",
        "91",
        "92",
        "93",
        "94",
        "95",
        "96",
        "97",
        "98",
        "99",
    ]
)


def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def is_valid_cpf(value: str) -> bool:
    d = digits(value)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        total = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (total * 10) % 11 % 10 != int(d[n]):
            return False
    return True


def clean_cnpj(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", value).upper()


def _cnpj_dv(base: str, weights: list[int]) -> int:
    # CNPJ alfanumérico (vigente desde jul/2026): valor do caractere = código ASCII − 48; compatível com o numérico.
    total = sum((ord(c) - 48) * w for c, w in zip(base, weights, strict=True))
    r = total % 11
    return 0 if r < 2 else 11 - r


def is_valid_cnpj(value: str) -> bool:
    v = clean_cnpj(value)
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", v) or v == v[0] * 14:
        return False
    d1 = _cnpj_dv(v[:12], _CNPJ_W1)
    d2 = _cnpj_dv(v[:12] + str(d1), _CNPJ_W2)
    return v[12] == str(d1) and v[13] == str(d2)


def format_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def format_cnpj(v: str) -> str:
    return f"{v[:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:]}"


def format_cep(d: str) -> str:
    return f"{d[:5]}-{d[5:]}"


def format_phone(d: str) -> str:
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    return f"({d[:2]}) {d[2:6]}-{d[6:]}"


def normalize_phone(value: str) -> str | None:
    """Devolve só dígitos (DDD + número) ou None se inválido. Aceita prefixo +55."""
    d = digits(value)
    if len(d) in (12, 13) and d.startswith("55"):
        d = d[2:]
    if len(d) not in (10, 11):
        return None
    if d[:2] not in VALID_DDD:
        return None
    number = d[2:]
    if len(number) == 9 and number[0] != "9":
        return None
    if len(number) == 8 and number[0] in "01":
        return None
    return d


def is_valid_email(value: str) -> bool:
    return len(value) <= 254 and bool(_EMAIL_RE.match(value))


def mask_regex(mask: str) -> re.Pattern[str]:
    """Máscara simples: # ou 0 = dígito, A = letra, * = letra/dígito; demais caracteres são literais."""
    out = []
    for ch in mask:
        if ch in "#0":
            out.append(r"\d")
        elif ch == "A":
            out.append(r"[A-Za-zÀ-ÿ]")
        elif ch == "*":
            out.append(r"[A-Za-zÀ-ÿ0-9]")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$")
