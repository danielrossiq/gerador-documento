"""Números e valores em reais por extenso (pt-BR), para contratos: "R$ 1.500,00 (mil e quinhentos reais)".

Regras usadas (as mais comuns em documentos jurídicos):
  * "mil", não "um mil"; "cem" sozinho, "cento e …" com resto;
  * "e" entre centenas, dezenas e unidades ("trezentos e quarenta e cinco");
  * entre grupos de milhar, "e" só antes do último grupo quando ele é menor que 100 ou centena redonda
    ("mil e quinhentos", "dois mil e dez"); nos demais casos, só espaço ("mil duzentos e trinta e quatro");
  * "de reais" depois de milhão/bilhão/trilhão redondos ("um milhão de reais", mas "um milhão e mil reais");
  * centavos depois de "e" ("dez reais e cinquenta centavos"); só centavos → "cinquenta centavos".
O frontend tem a mesma implementação (lib/fields/extenso.ts) e os dois rodam shared/field-vectors.json.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_UNITS = [
    "zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
    "dez", "onze", "doze", "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove",
]  # fmt: skip
_TENS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_HUNDREDS = [
    "", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
    "seiscentos", "setecentos", "oitocentos", "novecentos",
]  # fmt: skip
# (singular, plural) por grupo de milhar a partir do segundo
_SCALES = [("mil", "mil"), ("milhão", "milhões"), ("bilhão", "bilhões"), ("trilhão", "trilhões")]
MAX_INTEGER = 10**15 - 1  # até 999 trilhões


def _below_thousand(n: int) -> str:
    if n == 100:
        return "cem"
    parts: list[str] = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(_HUNDREDS[h])
    if rest:
        if rest < 20:
            parts.append(_UNITS[rest])
        else:
            t, u = divmod(rest, 10)
            parts.append(_TENS[t] + (f" e {_UNITS[u]}" if u else ""))
    return " e ".join(parts)


def integer_words(n: int) -> str:
    """0 ≤ n ≤ MAX_INTEGER → texto por extenso (masculino)."""
    if n < 0 or n > MAX_INTEGER:
        raise ValueError("número fora do intervalo do extenso")
    if n == 0:
        return "zero"
    groups: list[int] = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    words: list[tuple[int, str]] = []  # (valor do grupo, texto) da maior escala para a menor
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        if i == 0:
            words.append((g, _below_thousand(g)))
        elif i == 1:
            words.append((g, "mil" if g == 1 else f"{_below_thousand(g)} mil"))
        else:
            sing, plur = _SCALES[i - 1]
            words.append((g, f"{_below_thousand(g)} {sing if g == 1 else plur}"))
    out = words[0][1]
    for idx in range(1, len(words)):
        g, text = words[idx]
        last = idx == len(words) - 1
        out += (" e " if last and (g < 100 or g % 100 == 0) else " ") + text
    return out


def date_words(day: int, month_name: str, year: int) -> str:
    """21/09/2026 → "vinte e um de setembro de dois mil e vinte e seis" (dia 1 = "primeiro")."""
    d = "primeiro" if day == 1 else integer_words(day)
    return f"{d} de {month_name} de {integer_words(year)}"


def currency_words(value: Decimal) -> str:
    """Decimal em reais → "mil e quinhentos reais e dez centavos"."""
    v = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negative = v < 0
    v = abs(v)
    reais = int(v)
    centavos = int((v - reais) * 100)
    parts: list[str] = []
    if reais or not centavos:
        text = integer_words(reais)
        # "um milhão de reais": escala redonda (milhão ou maior, sem grupos menores) pede "de"
        de = reais >= 1_000_000 and reais % 1_000_000 == 0
        parts.append(f"{text} {'de ' if de else ''}{'real' if reais == 1 else 'reais'}")
    if centavos:
        parts.append(f"{integer_words(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
    return ("menos " if negative else "") + " e ".join(parts)
