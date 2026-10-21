"""Encaixa capturas REAIS do Minuta na tela magenta das cenas (scripts/site_scenes.py) e publica na landing.

Uso:
  python scripts/site_compose.py            # monta todas as composições cujas cenas e capturas existem
  python scripts/site_compose.py --debug    # também salva a máscara/cantos detectados em .media-originals/debug

Entradas: cenas em scripts/.media-originals/scenes (manifesto site_scenes.manifest.json) e capturas do app em
scripts/.media-originals/shots (scripts/site_shots.cjs). Saídas: frontend/public/site/<nome>-<largura>.{avif,webp}
e as entradas correspondentes em frontend/src/components/site/site-assets.json. Sem rede, sem custo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SCENES_DIR = ROOT / "scripts" / ".media-originals" / "scenes"
SHOTS_DIR = ROOT / "scripts" / ".media-originals" / "shots"
DEBUG_DIR = ROOT / "scripts" / ".media-originals" / "debug"
SCENES_MANIFEST = ROOT / "scripts" / "site_scenes.manifest.json"
PUBLIC = ROOT / "frontend" / "public" / "site"
ASSETS = ROOT / "frontend" / "src" / "components" / "site" / "site-assets.json"
WIDTHS = [640, 1024, 1600]

COMPOSITIONS = [
    {
        "name": "seg-advocacia",
        "scene": "seg-advocacia",
        "shot": "editor.png",
        "alt": "Advogada no escritório usando o Minuta no notebook: o contrato aberto com nome, CPF e valores marcados como campos.",
    },
    {
        "name": "seg-contabilidade",
        "scene": "seg-contabilidade",
        "shot": "lote.png",
        "alt": "Contador no computador com a tela de lote do Minuta: uma planilha com uma linha por cliente, pronta para gerar os documentos.",
    },
    {
        "name": "seg-imobiliaria",
        "scene": "seg-imobiliaria",
        "shot": "preencher.png",
        "alt": "Corretora mostrando no tablet o formulário do Minuta ao lado da prévia do recibo de aluguel preenchido.",
    },
    {
        "name": "seg-rh",
        "scene": "seg-rh",
        "shot": "kit.png",
        "alt": "Analista de RH no notebook usando um kit do Minuta: vários documentos do colaborador preenchidos de uma vez.",
    },
]


# ---------------------------------------------------------------------------------------------- geometria


def magenta_mask(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    raw = (r > 160) & (b > 110) & (g < 130) & (r - g > 80) & (b - g > 50)
    # densidade local (janela 15x15) para descartar pixels soltos rosados da cena
    k = 15
    ii = np.pad(raw.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    h, w = raw.shape
    y0 = np.clip(np.arange(h) - k // 2, 0, h)
    y1 = np.clip(np.arange(h) + k // 2 + 1, 0, h)
    x0 = np.clip(np.arange(w) - k // 2, 0, w)
    x1 = np.clip(np.arange(w) + k // 2 + 1, 0, w)
    area = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    s = ii[y1][:, x1] - ii[y0][:, x1] - ii[y1][:, x0] + ii[y0][:, x0]
    return raw & (s >= 0.92 * area)


def quad_corners(mask: np.ndarray) -> list[tuple[float, float]]:
    ys, xs = np.nonzero(mask)
    if len(xs) < 5000:
        raise SystemExit("Tela magenta não encontrada (ou pequena demais)")
    s, d = xs + ys, xs - ys
    tl = (xs[s.argmin()], ys[s.argmin()])
    br = (xs[s.argmax()], ys[s.argmax()])
    tr = (xs[d.argmax()], ys[d.argmax()])
    bl = (xs[d.argmin()], ys[d.argmin()])
    pts = np.array([tl, tr, br, bl], dtype=float)
    c = pts.mean(axis=0)
    # a máscara densa encolhe ~7 px nas bordas: devolve para fora, cobrindo também a franja anti-aliasing
    out = c + (pts - c) * (1 + 9 / np.linalg.norm(pts - c, axis=1)[:, None])
    return [tuple(p) for p in out]


def perspective_coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    """Coeficientes do Image.PERSPECTIVE: para cada ponto de saída (cena) devolve o ponto de entrada (captura)."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float)).tolist()


def defringe(img: Image.Image, corners: list[tuple[float, float]]) -> Image.Image:
    """Resto de magenta (anti-aliasing da borda da tela) vira a cor escura da moldura do aparelho."""
    band = Image.new("L", img.size, 0)
    ImageDraw.Draw(band).polygon(corners, fill=255)
    band = np.asarray(band.filter(ImageFilter.MaxFilter(31))) > 0  # ~15 px em volta da tela
    a = np.asarray(img).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    pink = band & (r - g > 45) & (b - g > 25)
    strength = np.clip(((r - g) - 45) / 80.0, 0.35, 1.0)[..., None]
    bezel = np.array([34, 34, 38], dtype=np.int16)
    out = np.where(pink[..., None], (a * (1 - strength) + bezel * strength).astype(np.int16), a)
    return Image.fromarray(out.astype(np.uint8))


def compose(scene: Image.Image, shot: Image.Image, debug_name: str | None) -> Image.Image:
    scene = scene.convert("RGB")
    corners = quad_corners(magenta_mask(scene))
    qw = max(np.hypot(corners[1][0] - corners[0][0], corners[1][1] - corners[0][1]), np.hypot(corners[2][0] - corners[3][0], corners[2][1] - corners[3][1]))
    # reduz a captura (2x) para ~1,5x o tamanho final da tela antes de distorcer: sem serrilhado
    target = int(qw * 1.5)
    shot = shot.convert("RGB")
    shot = shot.resize((target, int(target * shot.height / shot.width)), Image.Resampling.LANCZOS)
    src = [(0, 0), (shot.width, 0), (shot.width, shot.height), (0, shot.height)]
    warped = shot.transform(scene.size, Image.Transform.PERSPECTIVE, perspective_coeffs(corners, src), Image.Resampling.BICUBIC)
    # tela fotografada: um pouco menos de brilho/contraste e um reflexo suave do vidro
    warped = ImageEnhance.Brightness(warped).enhance(0.96)
    warped = ImageEnhance.Contrast(warped).enhance(0.95).filter(ImageFilter.GaussianBlur(0.35))
    mask = Image.new("L", scene.size, 0)
    ImageDraw.Draw(mask).polygon(corners, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))
    out = scene.copy()
    out.paste(warped, mask=mask)
    glare = Image.new("RGB", scene.size, (255, 255, 255))
    gmask = Image.new("L", scene.size, 0)
    gd = ImageDraw.Draw(gmask)
    (x0, y0), (x1, y1) = corners[0], corners[2]
    for i in range(40):  # faixa diagonal translúcida
        t = i / 40
        gd.polygon(
            [
                (x0 + (x1 - x0) * (0.55 + t * 0.12), y0),
                (x0 + (x1 - x0) * (0.62 + t * 0.12), y0),
                (x0 + (x1 - x0) * (0.30 + t * 0.12), y1),
                (x0 + (x1 - x0) * (0.23 + t * 0.12), y1),
            ],
            fill=int(10 * (1 - abs(t - 0.5) * 2)),
        )
    gmask = Image.composite(gmask, Image.new("L", scene.size, 0), mask)
    out = Image.composite(glare, out, gmask)
    out = defringe(out, corners)
    if debug_name:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        dbg = scene.copy()
        ImageDraw.Draw(dbg).polygon(corners, outline=(0, 255, 0), width=4)
        dbg.save(DEBUG_DIR / f"{debug_name}-quad.jpg", quality=85)
    return out


# ---------------------------------------------------------------------------------------------- saída


def publish(name: str, img: Image.Image, alt: str, assets: dict) -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    w, h = img.size
    widths = [x for x in WIDTHS if x < w] + [min(w, WIDTHS[-1])]
    widths = sorted(set(widths))
    for x in widths:
        y = round(h * x / w)
        im = img.resize((x, y), Image.Resampling.LANCZOS)
        im.save(PUBLIC / f"{name}-{x}.webp", "WEBP", quality=82, method=6)
        im.save(PUBLIC / f"{name}-{x}.avif", "AVIF", quality=60)
    largest = widths[-1]
    assets["images"][name] = {"base": f"/site/{name}", "widths": widths, "width": largest, "height": round(h * largest / w), "alt": alt}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    scenes = json.loads(SCENES_MANIFEST.read_text(encoding="utf-8"))["scenes"]
    assets = json.loads(ASSETS.read_text(encoding="utf-8"))
    done = 0
    for c in COMPOSITIONS:
        rec = scenes.get(c["scene"])
        shot = SHOTS_DIR / c["shot"]
        if not rec or not shot.exists():
            print(f"  {c['name']}: pulado (falta {'cena' if not rec else 'captura ' + c['shot']})")
            continue
        out = compose(Image.open(SCENES_DIR / rec["file"]), Image.open(shot), c["name"] if args.debug else None)
        publish(c["name"], out, c["alt"], assets)
        print(f"  {c['name']}: ok ({out.width}x{out.height})")
        done += 1
    ASSETS.write_text(json.dumps(assets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{done} composições publicadas em {PUBLIC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
