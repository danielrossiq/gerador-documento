"""Cenas realistas da landing (OpenRouter): pessoas usando notebook/tablet com a TELA EM MAGENTA LISO.

A tela magenta é depois trocada pela captura real do Minuta (scripts/site_compose.py), para a imagem mostrar o
produto de verdade — sem interface inventada pelo modelo de imagem.

Uso:
  python scripts/site_scenes.py --plan                 # só mostra o plano e o teto (sem rede)
  python scripts/site_scenes.py                        # gera as cenas que faltam
  python scripts/site_scenes.py --redo seg-rh          # gera de novo uma cena reprovada (conta no teto)

Chave: só do arquivo ~/.minuta/openrouter.key (ou OPENROUTER_KEY_FILE), fora do repositório; nunca impressa.
Teto: BUDGET_USD somando todas as execuções (registradas em scripts/site_scenes.manifest.json). Antes e depois de
cada chamada o uso real da chave é medido (GET /key); gasto não explicado ou acima do teto encerra a execução.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINALS = ROOT / "scripts" / ".media-originals" / "scenes"
MANIFEST = ROOT / "scripts" / "site_scenes.manifest.json"
API = "https://openrouter.ai/api/v1"
MODEL = "black-forest-labs/flux-3-image"
RESOLUTION = "2K"
MAX_CALL_USD = 0.12  # FLUX 3 a 2K custa até US$ 0,10 por imagem; folga para arredondamento
BUDGET_USD = 3.00  # teto das cenas (somando execuções)
KEY_RE = re.compile(r"^sk-or-[A-Za-z0-9_-]{20,200}$")

STYLE = (
    "Photorealistic editorial photograph, natural daylight, shallow depth of field, 35mm lens, realistic skin, "
    "warm and modern Brazilian workplace, clean composition. Absolutely no text, no letters, no logos, no watermarks. "
)
SCREEN = (
    "The device screen faces the camera and is fully visible and unobstructed; the entire screen area shows a "
    "flat, uniform, pure magenta color (#FF00FF), edge to edge, with no reflections, icons or content on it."
)

SCENES = [
    {
        "slug": "seg-advocacia",
        "aspect_ratio": "3:2",
        "prompt": STYLE
        + "Over-the-shoulder view from behind a Brazilian female lawyer in her thirties, wearing a blazer, sitting at a "
        "wooden desk in a bright modern law office with law books on shelves, working on an open laptop. " + SCREEN,
    },
    {
        "slug": "seg-contabilidade",
        "aspect_ratio": "3:2",
        "prompt": STYLE
        + "Over-the-shoulder view from behind a Brazilian male accountant in his forties at a tidy desk with a single "
        "large desktop monitor, a calculator and neat paper folders, modern accounting office with plants. " + SCREEN,
    },
    {
        "slug": "seg-imobiliaria",
        "aspect_ratio": "3:2",
        "prompt": STYLE
        + "A friendly Brazilian real estate agent woman in a bright furnished apartment living room, holding a tablet in "
        "landscape orientation turned towards the camera so its screen is clearly visible, keys on the coffee table. " + SCREEN,
    },
    {
        "slug": "seg-rh",
        "aspect_ratio": "3:2",
        "prompt": STYLE
        + "Over-the-shoulder view from behind a Brazilian HR analyst (young man with glasses) at a desk in an open-plan "
        "office with colleagues blurred in the background, working on an open laptop. " + SCREEN,
    },
]


# ---------------------------------------------------------------------------------------------- chave e HTTP


def read_key() -> str:
    path = Path(os.environ.get("OPENROUTER_KEY_FILE") or Path.home() / ".minuta" / "openrouter.key")
    if ROOT in path.resolve().parents:
        raise SystemExit("O arquivo da chave precisa ficar fora do repositório.")
    try:
        key = path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        raise SystemExit(f"Arquivo da chave não encontrado: {path}") from None
    if not KEY_RE.match(key):
        raise SystemExit(f"Arquivo da chave fora do formato esperado: {path}")
    return key


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # type: ignore[no-untyped-def]
        raise SystemExit("Redirect recusado")


_OPENER = urllib.request.build_opener(_NoRedirect())


def call(key: str, method: str, path: str, body: dict | None = None, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        f"{API}/{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Minuta (site)"},
    )
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read(64 * 1024 * 1024))
    except urllib.error.HTTPError as e:
        detail = e.read(2000).decode("utf-8", "replace").replace(key, "***")
        raise SystemExit(f"OpenRouter respondeu HTTP {e.code} em {path}: {detail[:300]}") from None


def key_usage(key: str) -> tuple[float, float | None]:
    d = call(key, "GET", "key")["data"]
    return float(d.get("usage") or 0), (float(d["limit_remaining"]) if d.get("limit_remaining") is not None else None)


# ---------------------------------------------------------------------------------------------- manifesto


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"budget_usd": BUDGET_USD, "spent_usd": 0.0, "calls": [], "scenes": {}}


def save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_png(raw: bytes) -> tuple[str, tuple[int, int]]:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 4096 * 4096
    with Image.open(io.BytesIO(raw)) as im:
        im.verify()
    with Image.open(io.BytesIO(raw)) as im:
        size = im.size
        fmt = (im.format or "png").lower()
    if not (0 < size[0] <= 4096 and 0 < size[1] <= 4096):
        raise SystemExit(f"Imagem com dimensões inesperadas: {size}")
    return {"jpeg": "jpg"}.get(fmt, fmt), size


def generate(key: str, scene: dict, m: dict, run: dict) -> None:
    if m["spent_usd"] + MAX_CALL_USD > BUDGET_USD + 1e-9:
        raise SystemExit(f"Teto de US$ {BUDGET_USD:.2f} atingido (gasto registrado US$ {m['spent_usd']:.2f}).")
    _, remaining = key_usage(key)
    if remaining is not None and remaining < MAX_CALL_USD:
        raise SystemExit("Crédito restante da chave menor que o máximo de uma chamada.")
    body = {"model": MODEL, "prompt": scene["prompt"], "resolution": RESOLUTION, "aspect_ratio": scene["aspect_ratio"], "n": 1}
    t0 = time.time()
    resp = call(key, "POST", "images", body)
    reported = (resp.get("usage") or {}).get("cost")
    # custo da chamada: o informado pela API; sem ele, conta o máximo (a medição da chave tem atraso)
    cost = float(reported) if reported is not None else MAX_CALL_USD
    attempt = sum(1 for c in m["calls"] if c["slug"] == scene["slug"]) + 1
    entry = {"slug": scene["slug"], "attempt": attempt, "model": MODEL, "cost_usd": cost, "seconds": round(time.time() - t0, 1)}
    m["spent_usd"] = round(m["spent_usd"] + cost, 6)
    m["calls"].append(entry)
    run["recorded"] += cost
    data = (resp.get("data") or [{}])[0]
    if data.get("b64_json"):  # grava antes de qualquer outra checagem: imagem paga não se perde
        raw = base64.b64decode(data["b64_json"])
        ext, size = check_png(raw)
        ORIGINALS.mkdir(parents=True, exist_ok=True)
        dst = ORIGINALS / f"{scene['slug']}-{attempt}.{ext}"
        dst.write_bytes(raw)
        entry["size"] = size
        m["scenes"][scene["slug"]] = {"file": dst.name, "prompt": scene["prompt"], "aspect_ratio": scene["aspect_ratio"], "size": size}
    save_manifest(m)
    if not data.get("b64_json"):
        raise SystemExit(f"{scene['slug']}: resposta sem imagem (custo registrado US$ {cost:.4f})")
    print(f"  {scene['slug']}: {dst.name} {size[0]}x{size[1]} · US$ {cost:.4f} · total US$ {m['spent_usd']:.4f}")
    if cost > MAX_CALL_USD + 1e-9:
        raise SystemExit(f"{scene['slug']}: custo US$ {cost:.4f} acima do máximo por chamada; execução encerrada.")


def check_run(key: str, run: dict) -> None:
    """Gasto da chave nesta execução (com atraso de atualização) não pode passar do registrado + 1 chamada."""
    used, _ = key_usage(key)
    delta = used - run["baseline"]
    print(f"Chave: US$ {delta:.4f} medidos nesta execução; US$ {run['recorded']:.4f} registrados.")
    if delta > run["recorded"] + MAX_CALL_USD + 1e-9:
        raise SystemExit("Gasto da chave não explicado pelo registro; verifique antes de continuar.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--redo", action="append", default=[])
    args = ap.parse_args()
    m = load_manifest()
    todo = [s for s in SCENES if s["slug"] not in m["scenes"] or s["slug"] in args.redo]
    print(f"Modelo {MODEL} {RESOLUTION}; teto US$ {BUDGET_USD:.2f}; gasto registrado US$ {m['spent_usd']:.4f}; a gerar: {[s['slug'] for s in todo]}")
    if args.plan or not todo:
        return 0
    key = read_key()
    run = {"baseline": key_usage(key)[0], "recorded": 0.0}
    for sc in todo:
        generate(key, sc, m, run)
    check_run(key, run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
