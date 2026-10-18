"""Gera as imagens da landing pública com a API da Runway (text-to-image) e otimiza para a web.

Uso:
    python scripts/generate_site_images.py --dry-run       # mostra o plano e o custo, sem chamar a API
    python scripts/generate_site_images.py                 # gera só as imagens ainda ausentes
    python scripts/generate_site_images.py --optimize-only # refaz webp/avif a partir dos originais baixados

Entradas:
- scripts/site_images.json: lista de imagens (slug, prompt, ratio, alt, widths).
- Chave da API: lida SOMENTE do arquivo em RUNWAY_KEY_FILE ou ~/.minuta/runway.key (fora do repo).
  A chave nunca vai para argumentos, logs, manifest ou mensagens de erro.

Saídas:
- frontend/public/site/<slug>-<w>.webp|avif (larguras responsivas)
- frontend/public/site/manifest.json (prompt, modelo, proporção, task id, créditos, data; sem chave nem headers)
- scripts/.runway-originals/<slug>.png (original baixado; ignorado pelo git)

Orçamento (autorizado pelo Daniel): no máximo 8 chamadas de geração e 6 imagens finais no total,
contabilizadas no manifest — reexecuções não ultrapassam o limite. Custo máximo por imagem: 10 créditos (US$ 0,10).
Referência oficial: https://docs.dev.runwayml.com/api/ (POST /v1/text_to_image, GET /v1/tasks/{id},
X-Runway-Version 2024-11-06) e https://docs.dev.runwayml.com/guides/pricing/ (gen4_image: 5 créditos em 720p,
8 em 1080p; 1 crédito = US$ 0,01).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts" / "site_images.json"
OUT = ROOT / "frontend" / "public" / "site"
MANIFEST = OUT / "manifest.json"
ORIGINALS = ROOT / "scripts" / ".runway-originals"

API = "https://api.dev.runwayml.com"
API_VERSION = "2024-11-06"
MODEL = "gen4_image"
MAX_CALLS = 8
MAX_IMAGES = 6
MAX_CREDITS_PER_IMAGE = 10
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300

# Créditos por imagem do gen4_image (guia de preços oficial): 720p = 5, 1080p = 8.
RATIOS_720P = {"1280:720", "720:1280", "720:720", "960:720", "720:960", "1680:720"}
RATIOS_1080P = {
    "1024:1024", "1080:1080", "1168:880", "1360:768", "1440:1080", "1080:1440",
    "1808:768", "1920:1080", "1080:1920", "2112:912",
}


class RunwayError(Exception):
    """Erro já sanitizado: só status e código/mensagem curta da API, nunca headers ou a chave."""


def credits_for(ratio: str) -> int:
    if ratio in RATIOS_720P:
        return 5
    if ratio in RATIOS_1080P:
        return 8
    raise SystemExit(f"Proporção não suportada pelo {MODEL}: {ratio}")


def read_key() -> str:
    path = Path(os.environ.get("RUNWAY_KEY_FILE") or Path.home() / ".minuta" / "runway.key")
    if not path.is_file():
        raise SystemExit(f"Arquivo da chave não encontrado: {path}")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"Arquivo da chave vazio: {path}")
    return key


def _request(method: str, url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("X-Runway-Version", API_VERSION)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            payload = json.loads(e.read().decode())
            detail = str(payload.get("error") or payload.get("code") or "")[:200]
        except Exception:
            pass
        raise RunwayError(f"HTTP {e.code} em {method} {url.removeprefix(API)} {detail}".replace(key, "***")) from None
    except urllib.error.URLError as e:
        raise RunwayError(f"Falha de rede em {method} {url.removeprefix(API)}: {type(e.reason).__name__}") from None


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"model": MODEL, "apiVersion": API_VERSION, "budget": {"maxCalls": MAX_CALLS, "maxImages": MAX_IMAGES}, "calls": [], "images": {}}


def save_manifest(m: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def optimize(slug: str, src: Path, widths: list[int]) -> list[dict]:
    from PIL import Image

    variants = []
    with Image.open(src) as im:
        im = im.convert("RGB")
        for w in sorted(set(widths)):
            w = min(w, im.width)
            h = round(im.height * w / im.width)
            resized = im.resize((w, h), Image.LANCZOS)
            for fmt, ext, opts in (("WEBP", "webp", {"quality": 78, "method": 6}), ("AVIF", "avif", {"quality": 55})):
                dst = OUT / f"{slug}-{w}.{ext}"
                resized.save(dst, fmt, **opts)
                variants.append({"file": f"/site/{dst.name}", "width": w, "height": h, "bytes": dst.stat().st_size})
    return variants


def generate_one(key: str, item: dict) -> tuple[str, float, Path]:
    body = {"model": MODEL, "promptText": item["prompt"], "ratio": item["ratio"]}
    if item.get("seed") is not None:
        body["seed"] = item["seed"]
    task = _request("POST", f"{API}/v1/text_to_image", key, body)
    task_id = task["id"]
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        time.sleep(POLL_INTERVAL_S)
        t = _request("GET", f"{API}/v1/tasks/{task_id}", key)
        status = t.get("status")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "CANCELLED"):
            raise RunwayError(f"Tarefa {task_id} terminou como {status} ({t.get('failureCode') or 'sem código'})")
        if time.monotonic() > deadline:
            raise RunwayError(f"Tarefa {task_id} excedeu {POLL_TIMEOUT_S}s (status {status})")
    credits = float((t.get("cost") or {}).get("credits", credits_for(item["ratio"])))
    url = t["output"][0]  # URL assinada e temporária: baixa já e não guarda em lugar nenhum
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    dst = ORIGINALS / f"{item['slug']}.png"
    with urllib.request.urlopen(url, timeout=120) as resp:  # sem Authorization: a URL já é assinada
        dst.write_bytes(resp.read())
    return task_id, credits, dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--optimize-only", action="store_true")
    ap.add_argument("--only", help="gera apenas este slug")
    args = ap.parse_args()

    items = json.loads(SPEC.read_text(encoding="utf-8"))["images"]
    if len(items) > MAX_IMAGES:
        raise SystemExit(f"{len(items)} imagens no spec; o limite autorizado é {MAX_IMAGES}")
    for it in items:
        if credits_for(it["ratio"]) > MAX_CREDITS_PER_IMAGE:
            raise SystemExit(f"{it['slug']}: custo acima de {MAX_CREDITS_PER_IMAGE} créditos")

    m = load_manifest()
    if args.optimize_only:
        for it in items:
            src = ORIGINALS / f"{it['slug']}.png"
            if src.is_file() and it["slug"] in m["images"]:
                m["images"][it["slug"]]["variants"] = optimize(it["slug"], src, it["widths"])
        save_manifest(m)
        print("Variantes regeneradas.")
        return 0

    pending = [it for it in items if it["slug"] not in m["images"] and (not args.only or it["slug"] == args.only)]
    used = len(m["calls"])
    print(f"Modelo {MODEL}; chamadas já feitas: {used}/{MAX_CALLS}; imagens prontas: {len(m['images'])}/{MAX_IMAGES}")
    for it in pending:
        print(f"  pendente: {it['slug']} ({it['ratio']}, ~{credits_for(it['ratio'])} créditos)")
    if args.dry_run or not pending:
        return 0

    key = read_key()
    failures = 0
    for it in pending:
        if len(m["calls"]) >= MAX_CALLS:
            print(f"Limite de {MAX_CALLS} chamadas atingido; parando.")
            failures += 1
            break
        call = {"slug": it["slug"], "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        m["calls"].append(call)
        save_manifest(m)  # registra a chamada antes de fazê-la: falha também conta no orçamento
        try:
            task_id, credits, src = generate_one(key, it)
        except RunwayError as e:
            call["error"] = str(e)
            save_manifest(m)
            print(f"ERRO {it['slug']}: {e}")
            failures += 1
            if str(e).startswith(("HTTP 401", "HTTP 402", "HTTP 403")):
                break  # chave inválida, sem créditos ou sem plano: não insiste
            continue
        call.update(taskId=task_id, credits=credits)
        m["images"][it["slug"]] = {
            "prompt": it["prompt"], "model": MODEL, "ratio": it["ratio"], "taskId": task_id, "credits": credits,
            "generatedAt": call["at"], "alt": it["alt"], "variants": optimize(it["slug"], src, it["widths"]),
        }
        save_manifest(m)
        print(f"ok {it['slug']}: task {task_id}, {credits:g} créditos")

    total = sum(c.get("credits", 0) for c in m["calls"])
    print(f"Total gasto registrado: {total:g} créditos (US$ {total / 100:.2f}); chamadas {len(m['calls'])}/{MAX_CALLS}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
