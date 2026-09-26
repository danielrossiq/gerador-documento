"""Nomes de arquivo: padrão configurável, sanitização (Windows/Linux/ZIP) e nomes repetidos."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

TOKEN_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_LEN = 120


def sanitize_filename(name: str, max_len: int = MAX_LEN) -> str:
    name = unicodedata.normalize("NFC", name)
    name = INVALID_CHARS.sub("-", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"\.{2,}", ".", name)
    name = name.strip(" ._-")
    if not name:
        name = "documento"
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        name = f"_{name}"
    return name[:max_len].rstrip(" ._-") or "documento"


def render_pattern(pattern: str, tokens: Mapping[str, str]) -> str:
    """Troca {token} pelo valor; token desconhecido vira vazio. O resultado é sempre um nome seguro."""
    return sanitize_filename(TOKEN_RE.sub(lambda m: str(tokens.get(m.group(1), "")), pattern))


def dedupe(names: Iterable[str]) -> list[str]:
    """Garante unicidade sem diferenciar maiúsculas (Windows): repetidos ganham _2, _3…"""
    seen: dict[str, int] = {}
    used: set[str] = set()
    out: list[str] = []
    for n in names:
        key = n.lower()
        if key not in used:
            used.add(key)
            seen[key] = 1
            out.append(n)
            continue
        i = seen.get(key, 1)
        while True:
            i += 1
            cand = f"{n}_{i}"
            if cand.lower() not in used:
                break
        seen[key] = i
        used.add(cand.lower())
        out.append(cand)
    return out


def content_disposition(filename: str) -> str:
    """Cabeçalho RFC 6266 com fallback ASCII."""
    from urllib.parse import quote

    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode() or "arquivo"
    ascii_name = ascii_name.replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
