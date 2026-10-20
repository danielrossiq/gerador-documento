"""Gera as imagens e os vídeos da landing pública com a API da OpenRouter e otimiza tudo para a web.

Uso:
    python scripts/generate_site_media.py --dry-run          # plano, limites, preços ao vivo e custo estimado; sem chave
    python scripts/generate_site_media.py                    # gera só os assets ausentes, dentro do orçamento
    python scripts/generate_site_media.py --only <slug>      # restringe a um asset
    python scripts/generate_site_media.py --redo <slug>      # descarta um asset reprovado e gera de novo (conta no orçamento)
    python scripts/generate_site_media.py --retry-unknown <slug>  # chamada anterior caiu sem resultado: paga de novo
    python scripts/generate_site_media.py --optimize-only    # refaz AVIF/WebP/MP4/WebM a partir dos originais baixados

Entradas:
- scripts/site_media.json: assets da spec do Design (slug, modelo, parâmetros, prompt, alt, larguras).
- Chave: lida SOMENTE do arquivo em OPENROUTER_KEY_FILE ou ~/.minuta/openrouter.key, fora do repositório, e validada
  antes do uso (uma linha, prefixo sk-or-, até 1 KB). Nunca vai para argumentos, logs, manifest ou mensagens de erro.

Rede: só https://openrouter.ai (allowlist fixa) e nenhum redirect é seguido. Respostas JSON
exigem Content-Type application/json e têm teto de tamanho; o vídeo é baixado em streaming para um .part e só é movido
depois de conferidos Content-Type (video/mp4), tamanho e assinatura do arquivo. Uma execução por vez (trava em
scripts/.site_media.lock); uma chamada que caiu sem resultado conhecido não é paga de novo sem --retry-unknown.

Saídas:
- frontend/public/site/: <slug>-<w>.avif|webp, <slug>.webm|mp4 e pôster <slug>-poster-<w>.avif|webp (sem metadados)
- frontend/src/components/landing/site-media.json: só o que a landing usa (arquivos, dimensões, alt)
- scripts/site_media.manifest.json: prompt, modelo, parâmetros, ids, custo, data e checagens (sem chave, headers nem URLs)
- scripts/.media-originals/: originais baixados (ignorado pelo git)

Orçamento: US$ 3,00 no total (saldo de US$ 5 na conta; US$ 2 ficam reservados à avaliação da IA, decisão do PO
no plano ia-integrada-plano.md v0.3). Imagens: até 12 chamadas e 8 finais. Vídeo: até 4 chamadas,
2 finais e 8 s cada. Cada chamada é gravada no manifest antes de sair, e falhas também contam. Antes de cada chamada,
o gasto registrado (custo devolvido pela API ou, sem ele, a estimativa) mais a estimativa da próxima não pode passar
do teto. Antes da primeira chamada paga, os preços ao vivo dos modelos são conferidos; acima do aprovado, o script para.

Referências oficiais: https://openrouter.ai/docs/guides/overview/multimodal/image-generation,
https://openrouter.ai/docs/guides/overview/multimodal/video-generation e
https://openrouter.ai/docs/cookbook/video-generation/image-to-video
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts" / "site_media.json"
MANIFEST = ROOT / "scripts" / "site_media.manifest.json"
ORIGINALS = ROOT / "scripts" / ".media-originals"
PUBLIC = ROOT / "frontend" / "public" / "site"
UI_DATA = ROOT / "frontend" / "src" / "components" / "landing" / "site-media.json"

API = "https://openrouter.ai/api/v1"
API_HOST = "openrouter.ai"

BUDGET_USD = 3.00  # teto do site; os outros US$ 2 do saldo ficam para a avaliação da IA
LIMITS = {"image": {"calls": 12, "finals": 8}, "video": {"calls": 4, "finals": 2}}
MAX_VIDEO_SECONDS = 8

# Allowlist aprovada pelo PRODUCT OWNER. A spec escolhe entre estes modelos, mas não sobe preço nem limite.
IMAGE_MODELS = {
    # Preço por imagem na variante 2k do endpoint (pricing[].variant).
    "black-forest-labs/flux-3-image": {
        "resolutions": {"2K"},
        "estimate_usd": 0.10,
        "max_price": 0.10,
        "variant": "2k",
    },
    # Edição/variação com referência. Cobrado por token de saída (US$ 0,00003; ~1.700 tokens em 2K): estimativa folgada.
    "google/gemini-nano-banana-2.1": {
        "resolutions": {"1K", "2K"},
        "estimate_usd": 0.10,
        "max_price": 0.00003,
        "variant": None,
    },
}
VIDEO_MODELS = {
    "google/veo-3.1-fast": {"resolutions": {"1080p"}, "usd_per_s": 0.10},
    "google/veo-3.1-lite": {"resolutions": {"1080p"}, "usd_per_s": 0.05},
}
VIDEO_SKU = "duration_seconds_without_audio"  # 1080p sem áudio (720p e 4K têm SKUs próprios)

# Únicos hosts aceitos: a doc e as respostas (polling_url, unsigned_urls) só apontam para cá. Redirect nunca é seguido.
ALLOWED_HOSTS = frozenset({"openrouter.ai"})
KEY_RE = re.compile(r"^sk-or-[A-Za-z0-9_-]{20,200}$")
MAX_KEY_FILE_BYTES = 1024
MAX_JSON_BYTES = 64 * 1024 * 1024  # imagem 2K em base64 cabe com folga
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
LOCK = ROOT / "scripts" / ".site_media.lock"
HTTP_TIMEOUT_S = 300
POLL_INTERVAL_S = 20
POLL_TIMEOUT_S = 20 * 60
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_SIDE = 4096  # 2K fica bem abaixo; acima disso a resposta é recusada
# Vídeo 1080p de até 8 s: limites conferidos no original antes do ffmpeg e de novo na saída, antes de publicar.
VIDEO_CODECS = {"h264", "hevc", "vp9", "av1"}
MAX_VIDEO_LONG_SIDE, MAX_VIDEO_SHORT_SIDE, MAX_VIDEO_FPS = 1920, 1080, 60
FFMPEG_TIMEOUT_S = 15 * 60
MAX_VIDEO_BYTES = 300 * 1024 * 1024
FRAME_MAX_WIDTH = 1920  # quadro enviado ao vídeo (data URL JPEG): mesmo tamanho da saída 1080p


class ApiError(Exception):
    """Erro já sanitizado: status e mensagem curta da API. Nunca headers, chave, corpo da requisição ou URLs assinadas."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def fatal(self) -> bool:
        # Chave inválida, sem crédito ou sem permissão: não adianta tentar o próximo asset.
        return self.status in (401, 402, 403)


class PollTimeout(ApiError):
    """O job de vídeo continua na fila; o id fica no manifest e a próxima execução retoma o polling sem pagar outro."""


# --------------------------------------------------------------------------- chave e HTTP


def key_path() -> Path:
    return Path(os.environ.get("OPENROUTER_KEY_FILE") or Path.home() / ".minuta" / "openrouter.key")


def read_key() -> str:
    """Lê e valida a chave (uma linha, prefixo sk-or-, tamanho plausível). Nunca exibe o conteúdo."""
    path = key_path()
    if not path.is_file():
        raise SystemExit(f"Arquivo da chave não encontrado: {path}")
    if ROOT in path.resolve().parents:
        raise SystemExit("O arquivo da chave precisa ficar fora do repositório.")
    if path.stat().st_size > MAX_KEY_FILE_BYTES:
        raise SystemExit(f"Arquivo grande demais para ser a chave: {path}")
    try:
        key = path.read_text(encoding="utf-8-sig").strip()  # tolera BOM e quebra de linha no fim
    except UnicodeDecodeError:
        key = ""
    if not KEY_RE.match(key):  # uma linha só: \r ou \n no meio não passam na regex
        raise SystemExit(f"Arquivo da chave fora do formato esperado (uma linha com prefixo sk-or-): {path}")
    return key


_KEY_RE = re.compile(r"sk-or-[A-Za-z0-9_-]{6,}")
_DATA_URL_RE = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+")
_QUERY_RE = re.compile(r"(https?://[^\s?#\"']+)\?[^\s\"']*")


def scrub(text: str, key: str | None = None) -> str:
    """Remove chave, tokens com cara de chave, data URLs e query strings (assinaturas) de uma mensagem."""
    if key:
        text = text.replace(key, "***")
    text = _KEY_RE.sub("sk-or-***", text)
    text = _DATA_URL_RE.sub("data:…", text)
    return _QUERY_RE.sub(r"\1?…", text)


def allowed_url(url: str) -> bool:
    """https, host da allowlist fixa, porta padrão e sem credenciais na URL."""
    p = urllib.parse.urlsplit(url)
    return p.scheme == "https" and p.hostname in ALLOWED_HOSTS and p.port is None and not p.username


def api_url(path_or_url: str) -> str:
    """Normaliza o destino e garante que é a API da OpenRouter antes de anexar a chave."""
    url = urllib.parse.urljoin(API + "/", path_or_url)
    if not allowed_url(url) or not urllib.parse.urlsplit(url).path.startswith("/api/v1/"):
        raise ApiError("Destino fora da API da OpenRouter recusado")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A API não usa redirect: qualquer 3xx é recusado, então nada é buscado fora do destino conferido por api_url.
    # (O Authorization ainda vai como cabeçalho "unredirected", que o urllib nunca copia para outra requisição.)
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError(f"Redirect recusado (HTTP {code})", code)


def build_opener(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect(), *handlers)


_OPENER = build_opener()


def _request(
    method: str, path: str, key: str | None, body: dict | None
) -> tuple[urllib.request.Request, str]:
    url = api_url(path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - api_url só aceita https://openrouter.ai/api/v1/
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if key is not None:
        req.add_unredirected_header("Authorization", f"Bearer {key}")
    return req, url


def _http_error(e: urllib.error.HTTPError, method: str, url: str, key: str | None) -> ApiError:
    detail = ""
    try:
        payload = json.loads(e.read(4096).decode("utf-8", "replace"))
        err = payload.get("error") if isinstance(payload, dict) else None
        detail = str(err.get("message") or err.get("code") or "") if isinstance(err, dict) else str(err or "")
    except (ValueError, AttributeError, OSError):
        detail = ""  # corpo ilegível: fica só o status
    path = urllib.parse.urlsplit(url).path
    return ApiError(scrub(f"HTTP {e.code} em {method} {path}: {detail[:200]}".rstrip(": "), key), e.code)


def call_api(method: str, path: str, key: str | None = None, body: dict | None = None) -> dict:
    req, url = _request(method, path, key, body)
    where = f"{method} {urllib.parse.urlsplit(url).path}"
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT_S) as resp:
            ctype = resp.headers.get_content_type()
            if ctype != "application/json":
                raise ApiError(f"Resposta com Content-Type inesperado ({ctype}) em {where}")
            raw = resp.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise ApiError(f"Resposta acima de {MAX_JSON_BYTES // (1024 * 1024)} MB recusada em {where}")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _http_error(e, method, url, key) from None
    except (urllib.error.URLError, OSError) as e:
        raise ApiError(f"Falha de rede em {where}: {type(e).__name__}") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError(f"Resposta não JSON em {where}") from None


def is_mp4(head: bytes) -> bool:
    return head[4:8] == b"ftyp"


def download(path: str, dst: Path, key: str, max_bytes: int, content_types: set[str], magic) -> int:
    """Baixa conteúdo autenticado (unsigned_urls) em streaming para um temporário e só move para `dst` depois de
    conferir Content-Type, tamanho e assinatura do arquivo. As URLs assinadas ("urls") nunca são usadas."""
    req, url = _request("GET", path, key, None)
    where = urllib.parse.urlsplit(url).path
    part = dst.with_name(dst.name + ".part")
    total, head = 0, b""
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT_S) as resp:
            ctype = resp.headers.get_content_type()
            if ctype not in content_types:
                raise ApiError(f"Download com Content-Type inesperado ({ctype}) em {where}")
            with open(part, "wb") as f:
                while chunk := resp.read(1 << 20):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ApiError(f"Download acima de {max_bytes // (1024 * 1024)} MB recusado")
                    head += chunk[: max(0, 16 - len(head))]
                    f.write(chunk)
        if not magic(head):
            raise ApiError(f"Conteúdo baixado não confere com {', '.join(sorted(content_types))}")
    except urllib.error.HTTPError as e:
        part.unlink(missing_ok=True)
        raise _http_error(e, "GET", url, key) from None
    except ApiError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as e:
        part.unlink(missing_ok=True)
        raise ApiError(f"Falha de rede no download {where}: {type(e).__name__}") from None
    part.replace(dst)
    return total


# --------------------------------------------------------------------------- spec, manifest e orçamento


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_spec() -> dict:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    images, videos = spec.get("images", []), spec.get("videos", [])
    slugs = [a["slug"] for a in images + videos]
    if len(set(slugs)) != len(slugs):
        raise SystemExit("Slugs repetidos na spec")
    for a in images + videos:
        if not SLUG_RE.match(a["slug"]):
            raise SystemExit(f"Slug inválido: {a['slug']!r}")
    if len(images) > LIMITS["image"]["finals"] or len(videos) > LIMITS["video"]["finals"]:
        raise SystemExit("A spec pede mais assets finais que o autorizado (8 imagens e 2 vídeos)")
    by_slug = {a["slug"]: a for a in images}
    for a in images:
        model = IMAGE_MODELS.get(a["model"])
        if model is None:
            raise SystemExit(f"{a['slug']}: modelo fora da allowlist: {a['model']}")
        if a["resolution"] not in model["resolutions"]:
            raise SystemExit(f"{a['slug']}: resolução {a['resolution']} não aprovada para {a['model']}")
        for ref in a.get("references", []):
            if ref not in by_slug or ref == a["slug"]:
                raise SystemExit(f"{a['slug']}: referência desconhecida {ref!r}")
    for v in videos:
        for model_id in [v["model"], *([v["fallback"]] if v.get("fallback") else [])]:
            if model_id not in VIDEO_MODELS:
                raise SystemExit(f"{v['slug']}: modelo de vídeo fora da allowlist: {model_id}")
            if v["resolution"] not in VIDEO_MODELS[model_id]["resolutions"]:
                raise SystemExit(f"{v['slug']}: resolução {v['resolution']} não aprovada para {model_id}")
        if not 1 <= int(v["duration"]) <= MAX_VIDEO_SECONDS:
            raise SystemExit(f"{v['slug']}: duração acima de {MAX_VIDEO_SECONDS} s")
        if v.get("frame") and v["frame"] not in by_slug:
            raise SystemExit(f"{v['slug']}: quadro {v['frame']!r} não é uma imagem da spec")
        if v.get("frame") and by_slug[v["frame"]]["aspect_ratio"] != v["aspect_ratio"]:
            raise SystemExit(
                f"{v['slug']}: o quadro precisa ter a mesma proporção do vídeo ({v['aspect_ratio']})"
            )
        if v.get("loop") and not v.get("frame"):
            raise SystemExit(f"{v['slug']}: loop exige um quadro (first_frame = last_frame)")
    return spec


def empty_manifest() -> dict:
    return {
        "provider": "openrouter",
        "budget": {
            "usd": BUDGET_USD,
            **{f"{k}{n.title()}": v for k, lim in LIMITS.items() for n, v in lim.items()},
            "videoMaxSeconds": MAX_VIDEO_SECONDS,
        },
        "calls": [],
        "assets": {"images": {}, "videos": {}},
        "rejected": [],
        "keyUsage": [],
    }


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return empty_manifest()


def save_manifest(m: dict) -> None:
    tmp = MANIFEST.with_name(MANIFEST.name + ".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(MANIFEST)


def recorded_usd(m: dict) -> float:
    """Gasto conservador: custo informado pela API quando existe; senão a estimativa (falhas e pendências incluídas)."""
    return round(
        sum(c["costUsd"] if c.get("costUsd") is not None else c["estimateUsd"] for c in m["calls"]), 4
    )


def calls_of(m: dict, kind: str) -> int:
    return sum(1 for c in m["calls"] if c["kind"] == kind)


def image_estimate(item: dict) -> float:
    return IMAGE_MODELS[item["model"]]["estimate_usd"]


def video_estimate(model_id: str, item: dict) -> float:
    return round(VIDEO_MODELS[model_id]["usd_per_s"] * int(item["duration"]), 4)


def can_spend(m: dict, kind: str, estimate: float) -> str | None:
    """Motivo para não fazer a próxima chamada, ou None se ela cabe nos limites."""
    if calls_of(m, kind) >= LIMITS[kind]["calls"]:
        return f"limite de {LIMITS[kind]['calls']} chamadas de {kind} atingido"
    if recorded_usd(m) + estimate > BUDGET_USD + 1e-9:
        return f"orçamento: US$ {recorded_usd(m):.2f} registrados + US$ {estimate:.2f} passariam de US$ {BUDGET_USD:.2f}"
    return None


# --------------------------------------------------------------------------- preços ao vivo (endpoints públicos)


def check_live_prices(spec: dict) -> list[str]:
    """Confere preços e parâmetros nos endpoints públicos de modelos. Devolve a lista de problemas (vazia = ok)."""
    problems: list[str] = []
    for model_id in sorted({a["model"] for a in spec.get("images", [])}):
        rule = IMAGE_MODELS[model_id]
        eps = call_api("GET", f"images/models/{model_id}/endpoints").get("endpoints", [])
        prices = [
            p["cost_usd"]
            for e in eps
            for p in e.get("pricing", [])
            if p.get("billable") == "output_image"
            and (rule["variant"] is None or p.get("variant") == rule["variant"])
        ]
        if not prices:
            problems.append(f"{model_id}: preço da variante {rule['variant'] or 'padrão'} não encontrado")
        elif max(prices) > rule["max_price"] + 1e-12:
            problems.append(f"{model_id}: preço ao vivo {max(prices)} acima do aprovado {rule['max_price']}")
    video_ids = {mid for v in spec.get("videos", []) for mid in [v["model"], v.get("fallback")] if mid}
    if video_ids:
        live = {m["id"]: m for m in call_api("GET", "videos/models").get("data", [])}
        for v in spec.get("videos", []):
            for model_id in [v["model"], *([v["fallback"]] if v.get("fallback") else [])]:
                info = live.get(model_id)
                if info is None:
                    problems.append(f"{model_id}: modelo não listado em /videos/models")
                    continue
                price = float(info.get("pricing_skus", {}).get(VIDEO_SKU, "inf"))
                if price > VIDEO_MODELS[model_id]["usd_per_s"] + 1e-9:
                    problems.append(
                        f"{model_id}: {VIDEO_SKU} = {price} acima de {VIDEO_MODELS[model_id]['usd_per_s']}/s"
                    )
                if int(v["duration"]) not in info.get("supported_durations", []):
                    problems.append(f"{model_id}: duração {v['duration']} s não suportada")
                if v["resolution"] not in info.get("supported_resolutions", []):
                    problems.append(f"{model_id}: resolução {v['resolution']} não suportada")
                if v["aspect_ratio"] not in info.get("supported_aspect_ratios", []):
                    problems.append(f"{model_id}: proporção {v['aspect_ratio']} não suportada")
                needed = (
                    {"first_frame", "last_frame"}
                    if v.get("loop")
                    else ({"first_frame"} if v.get("frame") else set())
                )
                if not needed <= set(info.get("supported_frame_images") or []):
                    problems.append(f"{model_id}: não aceita {sorted(needed)}")
    return problems


def key_usage(key: str) -> dict:
    """Uso acumulado da chave (GET /key). Guarda só números: o campo label (chave mascarada) é descartado."""
    d = call_api("GET", "key", key).get("data", {})
    return {"usageUsd": d.get("usage"), "limitRemainingUsd": d.get("limit_remaining")}


# --------------------------------------------------------------------------- geração


def sniff_image(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    raise ApiError("Resposta não é PNG, JPEG nem WebP")


def data_url(path: Path, max_width: int = FRAME_MAX_WIDTH) -> str:
    """Original local como data URL JPEG, sem metadados (referência de imagem ou quadro do vídeo)."""
    from PIL import Image

    with Image.open(path) as im:
        rgb = im.convert("RGB")
    if rgb.width > max_width:
        rgb = rgb.resize((max_width, round(rgb.height * max_width / rgb.width)), Image.LANCZOS)
    buf = io.BytesIO()
    Image.frombytes("RGB", rgb.size, rgb.tobytes()).save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


_ORIGINAL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}\.(png|jpg|webp|mp4)$")


def inside(path: Path, base: Path) -> Path:
    """Devolve `path` só se, resolvido, ele ficar dentro de `base` (sem escapar por .., link ou caminho absoluto)."""
    root = base.resolve()
    if root not in path.resolve().parents:
        raise SystemExit(f"Caminho fora de {base.name}/ recusado: {path.name}")
    return path


def original_path(name: str) -> Path:
    """Caminho de um original baixado; o nome vem do manifest e não pode sair de scripts/.media-originals/."""
    if not _ORIGINAL_RE.match(name):
        raise SystemExit(f"Nome de original inválido no manifest: {name!r}")
    return inside(ORIGINALS / name, ORIGINALS)


def original_of(m: dict, slug: str) -> Path:
    rec = m["assets"]["images"].get(slug)
    if not rec:
        raise SystemExit(f"{slug}: gere esta imagem antes (é referência ou quadro de outro asset)")
    return original_path(rec["original"])


def image_body(item: dict, m: dict) -> dict:
    body = {
        "model": item["model"],
        "prompt": item["prompt"],
        "resolution": item["resolution"],
        "aspect_ratio": item["aspect_ratio"],
        "n": 1,
    }
    refs = item.get("references", [])
    if refs:
        body["input_references"] = [
            {"type": "image_url", "image_url": {"url": data_url(original_of(m, r), 2048)}} for r in refs
        ]
    return body


def check_image(raw: bytes) -> None:
    """Falha fechado se a imagem não abrir, estiver truncada ou passar das dimensões esperadas para 2K."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_SIDE * MAX_IMAGE_SIDE  # bomba de descompressão vira erro
    try:
        with Image.open(io.BytesIO(raw)) as im:
            width, height = im.size
            im.verify()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ApiError("Imagem recebida inválida ou corrompida") from None
    if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE):
        raise ApiError(f"Imagem com dimensões fora do limite ({width}x{height})")


def generate_image(key: str, item: dict, body: dict) -> tuple[Path, dict]:
    resp = call_api("POST", "images", key, body)
    data = resp.get("data") or []
    if not data or not data[0].get("b64_json"):
        err = resp.get("error")
        detail = str((err.get("message") if isinstance(err, dict) else err) or "")[:200]
        raise ApiError(scrub(f"Resposta sem imagem{': ' + detail if detail else ''}", key))
    media_type = data[0].get("media_type")
    if media_type is not None and media_type not in IMAGE_TYPES:
        raise ApiError(f"Imagem em formato inesperado: {str(media_type)[:40]}")
    if len(data[0]["b64_json"]) > MAX_IMAGE_BYTES * 4 // 3 + 4:
        raise ApiError("Imagem acima do tamanho máximo")
    raw = base64.b64decode(data[0]["b64_json"])
    ext = sniff_image(raw)  # a assinatura do arquivo precisa bater com o tipo declarado
    if media_type is not None and IMAGE_TYPES[media_type] != ext:
        raise ApiError(f"Imagem declarada como {media_type}, mas o conteúdo é {ext}")
    check_image(raw)
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    dst = inside(ORIGINALS / f"{item['slug']}.{ext}", ORIGINALS)
    part = dst.with_name(dst.name + ".part")
    part.write_bytes(raw)
    part.replace(dst)
    return dst, resp.get("usage") or {}


def video_body(item: dict, model_id: str, m: dict) -> dict:
    body = {
        "model": model_id,
        "prompt": item["prompt"],
        "duration": int(item["duration"]),
        "resolution": item["resolution"],
        "aspect_ratio": item["aspect_ratio"],
        "generate_audio": False,
    }
    if item.get("frame"):
        url = data_url(original_of(m, item["frame"]))
        frames = ["first_frame", "last_frame"] if item.get("loop") else ["first_frame"]
        body["frame_images"] = [
            {"type": "image_url", "image_url": {"url": url}, "frame_type": f} for f in frames
        ]
    if item.get("negative_prompt"):
        body["provider"] = {
            "options": {"google-vertex": {"parameters": {"negativePrompt": item["negative_prompt"]}}}
        }
    return body


def submit_video(key: str, body: dict) -> dict:
    job = call_api("POST", "videos", key, body)
    if not job.get("id"):
        raise ApiError("Resposta sem id do job")
    return job


def wait_video(key: str, job: dict) -> dict:
    job_id = job["id"]
    deadline = time.monotonic() + POLL_TIMEOUT_S
    current = job
    while True:
        status = current.get("status")
        if status == "completed":
            return current
        if status in ("failed", "cancelled", "expired"):
            raise ApiError(
                f"Vídeo {job_id} terminou como {status}: {scrub(str(current.get('error') or 'sem detalhe'), key)[:200]}"
            )
        if time.monotonic() > deadline:
            raise PollTimeout(
                f"Vídeo {job_id} passou de {POLL_TIMEOUT_S}s (status {status}); rode de novo para retomar"
            )
        time.sleep(POLL_INTERVAL_S)
        current = call_api("GET", current.get("polling_url") or f"videos/{job_id}", key)


def fetch_video(key: str, job: dict, slug: str) -> Path:
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    dst = inside(ORIGINALS / f"{slug}.mp4", ORIGINALS)
    unsigned = (job.get("unsigned_urls") or [f"videos/{job['id']}/content?index=0"])[0]
    download(unsigned, dst, key, MAX_VIDEO_BYTES, {"video/mp4"}, is_mp4)
    return dst


# --------------------------------------------------------------------------- otimização (sem metadados)


def assert_no_metadata(path: Path) -> None:
    from PIL import Image

    with Image.open(path) as im:
        leaked = {"exif", "xmp", "XML:com.adobe.xmp", "icc_profile"} & set(im.info)
        if leaked or len(im.getexif()):
            raise SystemExit(f"{path.name}: metadados não removidos ({sorted(leaked) or 'exif'})")


def optimize_image(slug: str, src: Path, widths: list[int]) -> list[dict]:
    from PIL import Image

    with Image.open(src) as im:
        rgb = im.convert("RGB")
    base = Image.frombytes("RGB", rgb.size, rgb.tobytes())  # só pixels: sem EXIF, XMP nem ICC
    PUBLIC.mkdir(parents=True, exist_ok=True)
    variants = []
    for w in sorted({min(w, base.width) for w in widths}):
        h = round(base.height * w / base.width)
        resized = base.resize((w, h), Image.LANCZOS)
        for fmt, ext, opts in (
            ("AVIF", "avif", {"quality": 55, "speed": 4}),
            ("WEBP", "webp", {"quality": 78, "method": 6}),
        ):
            dst = inside(PUBLIC / f"{slug}-{w}.{ext}", PUBLIC)
            part = dst.with_name(dst.name + ".part")
            resized.save(part, fmt, **opts)
            assert_no_metadata(part)  # confere antes de publicar em public/site/
            part.replace(dst)
            variants.append(
                {"file": f"/site/{dst.name}", "width": w, "height": h, "bytes": dst.stat().st_size}
            )
    return variants


def _tool(name: str) -> str:
    exe = os.environ.get(name.upper()) or shutil.which(name)
    if not exe:
        raise SystemExit(f"{name} não encontrado (instale o ffmpeg ou defina {name.upper()})")
    return exe


def _run(args: list[str]) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 - ffmpeg/ffprobe com argumentos montados aqui, sem shell
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=FFMPEG_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"{Path(args[0]).name} passou de {FFMPEG_TIMEOUT_S}s; nada foi publicado") from None
    if proc.returncode != 0:
        raise SystemExit(f"{Path(args[0]).name} falhou ({proc.returncode}): {proc.stderr.strip()[-400:]}")
    return proc.stdout


def probe(path: Path) -> dict:
    out = json.loads(
        _run(
            [
                _tool("ffprobe"),
                "-v",
                "error",
                "-count_frames",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ]
        )
    )
    video = next((s for s in out.get("streams", []) if s.get("codec_type") == "video"), None)
    try:
        return {
            "width": int(video["width"]),
            "height": int(video["height"]),
            "codec": video["codec_name"],
            "duration": float(out["format"]["duration"]),
            "frames": int(video.get("nb_read_frames") or video.get("nb_frames") or 0),
            "audio": any(s.get("codec_type") == "audio" for s in out["streams"]),
            "bytes": int(out["format"]["size"]),
        }
    except (TypeError, KeyError, ValueError):
        raise SystemExit(f"{path.name}: arquivo sem trilha de vídeo legível; nada foi publicado") from None


def check_video(
    info: dict,
    label: str,
    *,
    max_seconds: float,
    width: int | None = None,
    max_frames: int | None = None,
    max_bytes: int | None = None,
    audio_ok: bool = False,
) -> None:
    """Falha fechado se o vídeo sair dos limites aprovados (codec, duração, dimensões, quadros, áudio, tamanho)."""
    long_side, short_side = max(info["width"], info["height"]), min(info["width"], info["height"])
    fps_cap = int((MAX_VIDEO_SECONDS + 0.5) * MAX_VIDEO_FPS)
    problems = [
        msg
        for bad, msg in (
            (info["codec"] not in VIDEO_CODECS, f"codec {info['codec']}"),
            (not 0 < info["duration"] <= max_seconds, f"duração {info['duration']:.2f} s"),
            (
                not (0 < long_side <= MAX_VIDEO_LONG_SIDE and 0 < short_side <= MAX_VIDEO_SHORT_SIDE),
                f"dimensões {info['width']}x{info['height']}",
            ),
            (width is not None and info["width"] != width, f"largura {info['width']} (esperada {width})"),
            (not 0 < info["frames"] <= min(fps_cap, max_frames or fps_cap), f"{info['frames']} quadros"),
            (info["audio"] and not audio_ok, "trilha de áudio"),
            (
                max_bytes is not None and info["bytes"] > max_bytes,
                f"{info['bytes']} bytes (teto {max_bytes})",
            ),
        )
        if bad
    ]
    if problems:
        raise SystemExit(f"{label} fora dos limites: {', '.join(problems)}. Nada foi publicado.")


def frame_png(src: Path, dst: Path, index: int) -> None:
    _run(
        [
            _tool("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-vf",
            f"select=eq(n\\,{index})",
            "-frames:v",
            "1",
            "-map_metadata",
            "-1",
            str(dst),
        ]
    )


def loop_seam(src: Path, frames: int) -> float:
    """Diferença média (0–255) entre o primeiro e o último quadro: perto de 0 = loop sem salto visível."""
    from PIL import Image, ImageChops, ImageStat

    with tempfile.TemporaryDirectory() as tmp:
        first, last = Path(tmp) / "a.png", Path(tmp) / "b.png"
        frame_png(src, first, 0)
        frame_png(src, last, max(frames - 1, 0))
        with Image.open(first) as a, Image.open(last) as b:
            diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
            return round(sum(ImageStat.Stat(diff).mean) / 3, 2)


def encode_video(slug: str, src: Path, item: dict) -> dict:
    info = probe(src)
    # O original vem de fora: confere antes de qualquer codificação (o áudio é removido abaixo, por isso é aceito).
    check_video(info, f"{slug}: original", max_seconds=MAX_VIDEO_SECONDS + 0.5, audio_ok=True)
    width = min(int(item.get("output_width", 1920)), info["width"])
    target = int(item.get("target_bytes", 3_000_000))
    # Com first_frame = last_frame o último quadro repete o primeiro: corta-o para o loop não "engasgar".
    frames = info["frames"] - 1 if item.get("loop") and info["frames"] > 1 else info["frames"]
    duration = frames / (info["frames"] / info["duration"]) if info["frames"] else info["duration"]
    kbps = max(500, int(target * 8 / duration / 1000 * 0.92))
    ffmpeg = _tool("ffmpeg")
    base = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-frames:v",
        str(frames),
        "-vf",
        f"scale={width}:-2:flags=lanczos,format=yuv420p",
    ]
    mp4, webm = inside(PUBLIC / f"{slug}.mp4", PUBLIC), inside(PUBLIC / f"{slug}.webm", PUBLIC)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_mp4, tmp_webm = (
            Path(tmp) / mp4.name,
            Path(tmp) / webm.name,
        )  # só vão para public/ depois de conferidos
        log = str(Path(tmp) / "pass")
        h264 = [
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-profile:v",
            "high",
            "-b:v",
            f"{kbps}k",
            "-maxrate",
            f"{int(kbps * 1.5)}k",
            "-bufsize",
            f"{kbps * 2}k",
            "-passlogfile",
            log,
        ]
        _run([*base, *h264, "-pass", "1", "-f", "null", os.devnull])
        _run([*base, *h264, "-pass", "2", "-movflags", "+faststart", str(tmp_mp4)])
        vp9 = [
            "-c:v",
            "libvpx-vp9",
            "-b:v",
            f"{kbps}k",
            "-row-mt",
            "1",
            "-deadline",
            "good",
            "-passlogfile",
            log + "-vp9",
        ]
        _run([*base, *vp9, "-cpu-used", "4", "-pass", "1", "-f", "null", os.devnull])
        _run([*base, *vp9, "-cpu-used", "1", "-pass", "2", str(tmp_webm)])
        poster_src = Path(tmp) / "poster.png"
        frame_png(src, poster_src, 0)
        out_mp4, out_webm = probe(tmp_mp4), probe(tmp_webm)
        for out, label in ((out_mp4, "MP4"), (out_webm, "WebM")):
            check_video(
                out,
                f"{slug}: {label} gerado",
                max_seconds=MAX_VIDEO_SECONDS + 0.1,
                width=width,
                max_frames=frames,
                max_bytes=int(target * 1.1),
            )
        seam = loop_seam(tmp_mp4, out_mp4["frames"]) if item.get("loop") else None
        shutil.move(tmp_mp4, mp4)
        shutil.move(tmp_webm, webm)
        poster = optimize_image(f"{slug}-poster", poster_src, item.get("poster_widths", [640, 1280, 1920]))
    return {
        "width": out_mp4["width"],
        "height": out_mp4["height"],
        "duration": round(out_mp4["duration"], 2),
        "sources": [
            {"file": f"/site/{webm.name}", "type": "video/webm", "bytes": out_webm["bytes"]},
            {"file": f"/site/{mp4.name}", "type": "video/mp4", "bytes": out_mp4["bytes"]},
        ],
        "poster": poster,
        "checks": {
            "sourceAudio": info["audio"],
            "outputAudio": out_mp4["audio"] or out_webm["audio"],
            "durationS": round(out_mp4["duration"], 2),
            "maxDurationS": MAX_VIDEO_SECONDS,
            "targetBytes": target,
            "maxBytes": int(target * 1.1),
            "frames": out_mp4["frames"],
            "loopSeamMeanDiff": seam,
        },
    }


def write_ui_data(m: dict, spec: dict) -> None:
    """Gera o JSON que a landing importa: só arquivos, dimensões e textos alternativos."""
    alts = {a["slug"]: a.get("alt", "") for a in spec.get("images", []) + spec.get("videos", [])}
    images = {
        s: {
            "alt": alts.get(s, ""),
            "variants": [{k: v[k] for k in ("file", "width", "height")} for v in r["variants"]],
        }
        for s, r in m["assets"]["images"].items()
        if s in alts and r.get("variants")
    }
    videos = {}
    for s, r in m["assets"]["videos"].items():
        if s not in alts or not r.get("sources"):  # sem codificação concluída: rode --optimize-only
            continue
        videos[s] = {
            "alt": alts[s],
            "width": r["width"],
            "height": r["height"],
            "duration": r["duration"],
            "sources": [{k: x[k] for k in ("file", "type")} for x in r["sources"]],
            "poster": [{k: v[k] for k in ("file", "width", "height")} for v in r["poster"]],
        }
    UI_DATA.write_text(
        json.dumps({"images": images, "videos": videos}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- execução


def print_plan(spec: dict, m: dict, pending_images: list[dict], pending_videos: list[dict]) -> None:
    print(
        f"Gasto registrado: US$ {recorded_usd(m):.2f} de US$ {BUDGET_USD:.2f}; "
        f"imagens {calls_of(m, 'image')}/{LIMITS['image']['calls']} chamadas e {len(m['assets']['images'])}/"
        f"{LIMITS['image']['finals']} finais; vídeo {calls_of(m, 'video')}/{LIMITS['video']['calls']} chamadas e "
        f"{len(m['assets']['videos'])}/{LIMITS['video']['finals']} finais"
    )
    total = 0.0
    for it in pending_images:
        est = image_estimate(it)
        total += est
        refs = f", refs {it['references']}" if it.get("references") else ""
        print(
            f"  imagem {it['slug']}: {it['model']} {it['resolution']} {it['aspect_ratio']}{refs} ~US$ {est:.2f}"
        )
    for v in pending_videos:
        est = video_estimate(v["model"], v)
        total += est
        fb = (
            f" (fallback {v['fallback']} ~US$ {video_estimate(v['fallback'], v):.2f})"
            if v.get("fallback")
            else ""
        )
        print(
            f"  vídeo {v['slug']}: {v['model']} {v['resolution']} {v['aspect_ratio']} {v['duration']} s, "
            f"quadro {v.get('frame') or '-'}{' em loop' if v.get('loop') else ''} ~US$ {est:.2f}{fb}"
        )
    worst_images = LIMITS["image"]["calls"] * max([r["estimate_usd"] for r in IMAGE_MODELS.values()])
    worst_videos = (
        LIMITS["video"]["calls"] * max(r["usd_per_s"] for r in VIDEO_MODELS.values()) * MAX_VIDEO_SECONDS
    )
    print(
        f"Estimativa desta rodada: US$ {total:.2f}. Pior caso com todos os limites usados: US$ "
        f"{worst_images + worst_videos:.2f} (teto rígido US$ {BUDGET_USD:.2f})."
    )


def _fail(call: dict, e: ApiError, key: str, m: dict) -> None:
    call.update(status="failed", error=scrub(str(e), key))
    save_manifest(m)
    print(f"ERRO {call['slug']} ({call['model']}): {call['error']}")


def _cost(usage: dict | None) -> tuple[float | None, str]:
    cost = (usage or {}).get("cost")
    return (float(cost), "api") if cost is not None else (None, "estimate")


@contextlib.contextmanager
def run_lock():
    """Uma execução por vez: chamadas pagas nunca saem em paralelo, nem de dois terminais."""
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(
            f"Outra execução está em andamento (ou terminou sem limpar {LOCK.name}). "
            "Confirme que nenhuma está rodando e apague o arquivo para continuar."
        ) from None
    try:
        os.write(fd, f"{os.getpid()} {now()}\n".encode())
        os.close(fd)
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def unknown_outcome(m: dict, slug: str, retry: set[str]) -> bool:
    """Chamada anterior que saiu sem resultado registrado (queda no meio) pode ter sido cobrada.
    Só gera de novo esse asset com --retry-unknown <slug>, depois de conferir o uso na OpenRouter."""
    stuck = [c for c in m["calls"] if c["slug"] == slug and c["status"] == "pending"]
    if not stuck:
        return False
    if slug in retry:
        for c in stuck:
            c["status"] = "unknown"  # continua contando no orçamento pela estimativa
        save_manifest(m)
        return False
    print(
        f"PULADO {slug}: uma chamada anterior terminou sem resultado conhecido e pode ter sido cobrada. "
        f"Confira o uso na OpenRouter e, para pagar de novo, rode com --retry-unknown {slug}."
    )
    return True


def run_image(key: str, it: dict, m: dict, retry: set[str] = frozenset()) -> str:
    """Gera uma imagem. Devolve "ok", "failed" (segue para o próximo asset) ou "stop" (limite, orçamento ou chave)."""
    if unknown_outcome(m, it["slug"], retry):
        return "failed"
    estimate = image_estimate(it)
    reason = can_spend(m, "image", estimate)
    if reason:
        print(f"PARADO antes de {it['slug']}: {reason}")
        return "stop"
    body = image_body(it, m)  # monta antes de registrar: erro local não consome orçamento
    call = {
        "kind": "image",
        "slug": it["slug"],
        "model": it["model"],
        "at": now(),
        "status": "pending",
        "estimateUsd": estimate,
        "costUsd": None,
    }
    m["calls"].append(call)
    save_manifest(m)  # registrada antes de sair: se falhar ou cair, conta no orçamento
    try:
        src, usage = generate_image(key, it, body)
    except ApiError as e:
        _fail(call, e, key, m)
        return "stop" if e.fatal else "failed"
    cost, source = _cost(usage)
    call.update(status="ok", costUsd=cost, costSource=source)
    rec = m["assets"]["images"][it["slug"]] = {
        "prompt": it["prompt"],
        "model": it["model"],
        "resolution": it["resolution"],
        "aspectRatio": it["aspect_ratio"],
        "references": it.get("references", []),
        "generatedAt": call["at"],
        "costUsd": cost,
        "costSource": source,
        "original": src.name,
        "variants": [],
    }
    save_manifest(m)  # o resultado pago fica registrado antes da otimização (se ela falhar: --optimize-only)
    rec["variants"] = optimize_image(it["slug"], src, it["widths"])
    save_manifest(m)
    print(f"ok {it['slug']}: US$ {cost if cost is not None else '?'} ({source})")
    return "ok"


def _finish_video(key: str, v: dict, m: dict, call: dict, job: dict) -> str | None:
    """Acompanha um job já enviado. Devolve "ok", "stop" (pausado ou chave) ou None (job falhou: tente o fallback)."""
    try:
        done = wait_video(key, job)
    except PollTimeout as e:
        print(f"PAUSADO {v['slug']}: {e}")
        return "stop"
    except ApiError as e:
        _fail(call, e, key, m)
        return "stop" if e.fatal else None
    cost, source = _cost(done.get("usage"))
    call.update(costUsd=cost, costSource=source, generationId=done.get("generation_id"))
    save_manifest(m)
    try:
        src = fetch_video(key, done, v["slug"])
    except ApiError as e:
        # O job terminou e foi cobrado: nada de fallback. O id continua no manifest e a próxima execução baixa de novo.
        print(
            f"PAUSADO {v['slug']}: download falhou ({scrub(str(e), key)}); rode de novo para baixar sem novo job"
        )
        return "stop"
    call.update(status="ok")
    rec = m["assets"]["videos"][v["slug"]] = {
        "prompt": v["prompt"],
        "model": call["model"],
        "resolution": v["resolution"],
        "aspectRatio": v["aspect_ratio"],
        "durationRequested": int(v["duration"]),
        "frame": v.get("frame"),
        "loop": bool(v.get("loop")),
        "jobId": call["jobId"],
        "generatedAt": call["at"],
        "costUsd": cost,
        "costSource": source,
        "original": src.name,
    }
    save_manifest(m)  # o resultado pago fica registrado antes da codificação (se ela falhar: --optimize-only)
    rec.update(encode_video(v["slug"], src, v))
    save_manifest(m)
    print(f"ok {v['slug']}: {call['model']}, US$ {cost if cost is not None else '?'} ({source})")
    return "ok"


def run_video(key: str, v: dict, m: dict, retry: set[str] = frozenset()) -> str:
    """Gera um vídeo (modelo principal e, se falhar, o fallback). Retoma job já enviado em vez de pagar outro."""
    submitted = next(
        (
            c
            for c in m["calls"]
            if c["kind"] == "video" and c["slug"] == v["slug"] and c["status"] == "submitted"
        ),
        None,
    )
    if submitted:
        print(f"  {v['slug']}: retomando job {submitted['jobId']}")
        result = _finish_video(key, v, m, submitted, {"id": submitted["jobId"], "status": "pending"})
        if result is not None:
            return result
    if unknown_outcome(m, v["slug"], retry):
        return "failed"
    for model_id in [v["model"], *([v["fallback"]] if v.get("fallback") else [])]:
        estimate = video_estimate(model_id, v)
        reason = can_spend(m, "video", estimate)
        if reason:
            print(f"PARADO antes de {v['slug']} ({model_id}): {reason}")
            return "stop"
        body = video_body(v, model_id, m)
        call = {
            "kind": "video",
            "slug": v["slug"],
            "model": model_id,
            "at": now(),
            "status": "pending",
            "estimateUsd": estimate,
            "costUsd": None,
        }
        m["calls"].append(call)
        save_manifest(m)
        try:
            job = submit_video(key, body)
        except ApiError as e:
            _fail(call, e, key, m)
            if e.fatal:
                return "stop"
            continue
        call.update(status="submitted", jobId=job["id"])
        save_manifest(m)  # com o id gravado, uma nova execução retoma o polling em vez de pagar outro job
        print(f"  {v['slug']}: job {job['id']} enviado ({model_id}); acompanhando a cada {POLL_INTERVAL_S}s")
        result = _finish_video(key, v, m, call, job)
        if result is not None:
            return result
    return "failed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--dry-run", action="store_true", help="mostra plano e custo; não lê a chave nem faz chamada paga"
    )
    ap.add_argument("--only", help="processa apenas este slug")
    ap.add_argument("--redo", help="descarta o asset aprovado anteriormente com este slug e gera de novo")
    ap.add_argument("--reason", default="reprovado na revisão visual", help="motivo registrado com --redo")
    ap.add_argument(
        "--retry-unknown",
        action="append",
        default=[],
        metavar="SLUG",
        help="gera de novo um asset cuja chamada anterior ficou sem resultado (pode pagar duas vezes)",
    )
    ap.add_argument(
        "--optimize-only", action="store_true", help="refaz variantes a partir dos originais baixados"
    )
    args = ap.parse_args()

    spec = load_spec()
    m = load_manifest()
    images = {a["slug"]: a for a in spec.get("images", [])}
    videos = {v["slug"]: v for v in spec.get("videos", [])}
    for slug in [args.redo, *args.retry_unknown]:
        if slug and slug not in images and slug not in videos:
            raise SystemExit(f"Slug desconhecido: {slug!r}")

    if args.optimize_only:
        with run_lock():
            for slug, rec in m["assets"]["images"].items():
                if slug in images:
                    rec["variants"] = optimize_image(
                        slug, original_path(rec["original"]), images[slug]["widths"]
                    )
            for slug, rec in m["assets"]["videos"].items():
                if slug in videos:
                    rec.update(encode_video(slug, original_path(rec["original"]), videos[slug]))
            save_manifest(m)
            write_ui_data(m, spec)
        print("Variantes refeitas a partir dos originais.")
        return 0

    done = {**m["assets"]["images"], **m["assets"]["videos"]}
    redo = {args.redo} if args.redo else set()
    wanted = (lambda s: s == args.only or s in redo) if args.only else (lambda s: True)
    pending_images = [a for s, a in images.items() if (s not in done or s in redo) and wanted(s)]
    pending_videos = [v for s, v in videos.items() if (s not in done or s in redo) and wanted(s)]
    if args.dry_run and redo:
        print(f"(dry-run: --redo {args.redo} descartaria o asset atual e o geraria de novo)")
    print_plan(spec, m, pending_images, pending_videos)

    try:
        problems = check_live_prices(spec)
    except ApiError as e:
        problems = [f"não foi possível conferir os preços ao vivo ({e})"]
    for p in problems:
        print(f"PREÇO/PARÂMETRO: {p}")
    if args.dry_run:
        print("Preços ao vivo conferidos: " + ("ok" if not problems else "com problemas (veja acima)"))
        return 1 if problems else 0
    if problems:
        print("Nada foi gerado: preço ou parâmetro fora do aprovado.")
        return 1
    if not pending_images and not pending_videos:
        write_ui_data(m, spec)
        return 0

    key = read_key()
    with run_lock():
        m = (
            load_manifest()
        )  # relê sob a trava: outra execução pode ter terminado enquanto esta conferia preços
        try:
            start = key_usage(key)  # também valida a chave antes de qualquer chamada paga
        except ApiError as e:
            print(f"Nada foi gerado: {scrub(str(e), key)}")
            return 1
        if args.redo:
            for kind in ("images", "videos"):
                rec = m["assets"][kind].pop(args.redo, None)
                if rec:
                    m["rejected"].append(
                        {
                            "slug": args.redo,
                            "kind": kind[:-1],
                            "at": now(),
                            "reason": args.reason,
                            "model": rec["model"],
                            "costUsd": rec.get("costUsd"),
                        }
                    )
        m["keyUsage"].append({"at": now(), "phase": "start", **start})
        save_manifest(m)

        done = {**m["assets"]["images"], **m["assets"]["videos"]}
        retry = set(args.retry_unknown)
        results = []
        for it in pending_images:
            if it["slug"] in done:
                continue
            results.append(run_image(key, it, m, retry))
            if results[-1] == "stop":
                break
        if "stop" not in results:
            for v in pending_videos:
                if v["slug"] in done:
                    continue
                results.append(run_video(key, v, m, retry))
                if results[-1] == "stop":
                    break

        try:
            m["keyUsage"].append({"at": now(), "phase": "end", **key_usage(key)})
        except ApiError as e:
            print(f"Aviso: uso final da chave indisponível ({scrub(str(e), key)})")
        save_manifest(m)
        write_ui_data(m, spec)
    first, last = m["keyUsage"][-2].get("usageUsd"), m["keyUsage"][-1].get("usageUsd")
    delta = (
        f"; uso da chave nesta rodada: US$ {last - first:.4f}"
        if all(isinstance(x, (int, float)) for x in (first, last))
        else ""
    )
    print(f"Total registrado: US$ {recorded_usd(m):.2f} de US$ {BUDGET_USD:.2f}{delta}")
    return 0 if all(r == "ok" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
