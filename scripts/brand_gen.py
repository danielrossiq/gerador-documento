"""Gera imagens da identidade visual do DocFeito pela OpenRouter, com orçamento controlado.

Orçamento aprovado pelo Daniel: US$ 5 no total (BRAND_BUDGET_USD). Cada chamada tem teto próprio (MAX_CALL_USD); o
custo vem da própria resposta e é gravado num manifesto antes de qualquer outra checagem (imagem paga não se perde).
A chave é lida de ~/.minuta/openrouter.key (ou OPENROUTER_KEY_FILE) e nunca é impressa.

Uso:
  python scripts/brand_gen.py --name logo-a --model recraft/recraft-v4.1-vector --prompt "..." [--aspect 1:1] [--n 2]
  python scripts/brand_gen.py --status
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scripts" / ".media-originals" / "brand"
MANIFEST = OUT / "manifest.json"
BUDGET_USD = float(os.environ.get("BRAND_BUDGET_USD", "5.0"))
MAX_CALL_USD = 0.50


def key() -> str:
    path = Path(os.environ.get("OPENROUTER_KEY_FILE") or Path.home() / ".minuta" / "openrouter.key")
    return path.read_text(encoding="utf-8").strip()


def load() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"budget_usd": BUDGET_USD, "spent_usd": 0.0, "calls": []}


def save(m: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def ext_of(raw: bytes) -> str:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    head = raw[:300].lstrip().lower()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return "svg"
    return "bin"


def generate(name: str, model: str, prompt: str, aspect: str, n: int, resolution: str) -> None:
    m = load()
    if m["spent_usd"] + MAX_CALL_USD * n > BUDGET_USD + 1e-9:
        raise SystemExit(f"Orçamento: gasto US$ {m['spent_usd']:.4f} + até US$ {MAX_CALL_USD * n:.2f} passaria de US$ {BUDGET_USD:.2f}.")
    body = {"model": model, "prompt": prompt, "aspect_ratio": aspect, "n": n}
    if resolution:
        body["resolution"] = resolution
    t0 = time.time()
    r = httpx.post(
        "https://openrouter.ai/api/v1/images",
        json=body,
        headers={"Authorization": f"Bearer {key()}", "X-Title": "DocFeito (marca)"},
        timeout=300,
    )
    try:
        resp = r.json()
    except ValueError:
        resp = {}
    if r.status_code >= 400:
        raise SystemExit(f"{name}: HTTP {r.status_code} {str(resp.get('error') or resp)[:300]}")
    cost = (resp.get("usage") or {}).get("cost")
    cost = float(cost) if cost is not None else MAX_CALL_USD * n  # sem custo informado: conta o teto
    files = []
    OUT.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(resp.get("data") or []):
        raw = base64.b64decode(item["b64_json"]) if item.get("b64_json") else httpx.get(item["url"], timeout=120).content if item.get("url") else b""
        if not raw:
            continue
        dst = OUT / f"{name}-{i + 1}.{ext_of(raw)}"
        dst.write_bytes(raw)
        files.append(dst.name)
    m["spent_usd"] = round(m["spent_usd"] + cost, 6)
    m["calls"].append({"name": name, "model": model, "prompt": prompt, "aspect": aspect, "n": n, "cost_usd": cost, "seconds": round(time.time() - t0, 1), "files": files})
    save(m)
    print(f"{name}: {', '.join(files) or 'SEM IMAGEM'} · US$ {cost:.4f} · total US$ {m['spent_usd']:.4f} de {BUDGET_USD:.2f}")
    if cost > MAX_CALL_USD * n + 1e-9:
        raise SystemExit(f"{name}: custo acima do teto por chamada; parando.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--model")
    ap.add_argument("--prompt")
    ap.add_argument("--aspect", default="1:1")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--resolution", default="")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        m = load()
        print(f"gasto US$ {m['spent_usd']:.4f} de {BUDGET_USD:.2f} em {len(m['calls'])} chamadas")
        return
    generate(a.name, a.model, a.prompt, a.aspect, a.n, a.resolution)


if __name__ == "__main__":
    main()
