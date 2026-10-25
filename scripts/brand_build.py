"""Monta o kit de marca do DocFeito em SVG (vetorial, sem depender de fonte instalada).

Conceito (escolhido entre os estudos do Recraft em scripts/.media-originals/brand): a folha de documento com o canto
dobrado em verde e um check que sobe em direção à dobra — "documento feito". O check recorta a folha por máscara,
então o ícone funciona sobre fundo claro, escuro ou foto, e continua legível em 16 px. O nome é a Plus Jakarta Sans ExtraBold convertida em contornos.

Uso: python scripts/brand_build.py --font <PlusJakartaSans.woff2>
Saída: frontend/public/brand/*.svg (os PNGs saem de scripts/brand_export.cjs).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "brand"

PALETTE = {
    "tinta": "#0E1A2B",  # texto, folha do ícone, fundos escuros
    "verde": "#12B886",  # marca (check, "Feito")
    "verde_escuro": "#0B7A5A",  # botões/links (contraste 5,3:1 com branco)
    "verde_claro": "#E7F8F1",
    "verde_neon": "#3DDC97",  # "Feito" sobre fundo escuro
    "marca_texto": "#FFD43B",  # destaque dos campos
    "marca_texto_claro": "#FFF3BF",
    "papel": "#FAF8F3",
    "branco": "#FFFFFF",
}

# ícone em 64×64: folha 10..50 × 6..58, raio 8, canto superior direito dobrado (aba verde); check de (18,37) a (26,45) a (47,22)
DOC = "M18 6H35L50 21V50A8 8 0 0 1 42 58H18A8 8 0 0 1 10 50V14A8 8 0 0 1 18 6Z"
FLAP = "M35 6V16A5 5 0 0 0 40 21H50Z"
CHECK = "M18 37L26 45L47 22"


def icon_group(doc_fill: str, check: str, uid: str) -> str:
    return (
        f'<defs><mask id="m{uid}" maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">'
        f'<rect width="64" height="64" fill="#fff"/>'
        f'<path d="{CHECK}" fill="none" stroke="#000" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></mask></defs>'
        f'<path d="{DOC}" fill="{doc_fill}" mask="url(#m{uid})"/>'
        f'<path d="{FLAP}" fill="{check}"/>'
        f'<path d="{CHECK}" fill="none" stroke="{check}" stroke-width="7.5" stroke-linecap="round" stroke-linejoin="round"/>'
    )


def svg(w: float, h: float, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}" role="img" aria-label="{title}">'
        f"<title>{title}</title>{body}</svg>\n"
    )


class Wordmark:
    def __init__(self, font_path: Path) -> None:
        font = TTFont(str(font_path))
        if "fvar" in font:
            font = instancer.instantiateVariableFont(font, {"wght": 800})
        self.font = font
        self.gs = font.getGlyphSet()
        self.cmap = font.getBestCmap()
        self.upm = font["head"].unitsPerEm
        self.hmtx = font["hmtx"]
        os2 = font["OS/2"]
        self.cap = getattr(os2, "sCapHeight", 0) or 0.72 * self.upm

    def path(self, text: str, size: float, x: float, baseline: float, tracking: float = -0.02) -> tuple[str, float]:
        s = size / self.upm
        out = []
        for ch in text:
            name = self.cmap[ord(ch)]
            pen = SVGPathPen(self.gs)
            self.gs[name].draw(TransformPen(pen, (s, 0, 0, -s, x, baseline)))
            out.append(pen.getCommands())
            x += self.hmtx[name][0] * s + tracking * size
        return " ".join(out), x - tracking * size


def horizontal(wm: Wordmark, doc: str, check: str, doc_text: str, feito_text: str, uid: str, title: str) -> str:
    size = 44.0  # altura de maiúscula ≈ 32 = a "folha" do ícone sem as bordas
    cap = wm.cap * size / wm.upm
    baseline = 32 + cap / 2
    d1, x1 = wm.path("Doc", size, 66, baseline)
    d2, x2 = wm.path("Feito", size, x1, baseline)
    body = icon_group(doc, check, uid) + f'<path d="{d1}" fill="{doc_text}"/><path d="{d2}" fill="{feito_text}"/>'
    return svg(round(x2 + 4, 1), 64, body, title)


def stacked(wm: Wordmark, doc: str, check: str, doc_text: str, feito_text: str, uid: str, title: str) -> str:
    size = 34.0
    d1, x1 = wm.path("Doc", size, 0, 0)
    d2, x2 = wm.path("Feito", size, x1, 0)
    width = x2
    cap = wm.cap * size / wm.upm
    scale = 1.5
    ix = (max(width, 64 * scale) - 64 * scale) / 2
    tx = (max(width, 64 * scale) - width) / 2
    ty = 64 * scale + 14 + cap
    body = (
        f'<g transform="translate({ix:.2f} 0) scale({scale})">{icon_group(doc, check, uid)}</g>'
        f'<g transform="translate({tx:.2f} {ty:.2f})"><path d="{d1}" fill="{doc_text}"/><path d="{d2}" fill="{feito_text}"/></g>'
    )
    return svg(round(max(width, 64 * scale), 1), round(ty + 8, 1), body, title)


def app_icon(bg: str, doc: str, check: str, uid: str) -> str:
    # quadrado arredondado (ícone do app/favicon grande): folha clara sobre tinta
    body = f'<rect width="64" height="64" rx="14" fill="{bg}"/><g transform="translate(8.5 7) scale(0.75)">{icon_group(doc, check, uid)}</g>'
    return svg(64, 64, body, "DocFeito")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    a = ap.parse_args()
    wm = Wordmark(Path(a.font))
    P = PALETTE
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "docfeito-icone.svg": svg(64, 64, icon_group(P["tinta"], P["verde"], "i"), "DocFeito"),
        "docfeito-icone-negativo.svg": svg(64, 64, icon_group(P["branco"], P["verde_neon"], "n"), "DocFeito"),
        "docfeito-icone-app.svg": app_icon(P["tinta"], P["branco"], P["verde_neon"], "a"),
        "docfeito-logo.svg": horizontal(wm, P["tinta"], P["verde"], P["tinta"], P["verde"], "h", "DocFeito"),
        "docfeito-logo-negativo.svg": horizontal(wm, P["branco"], P["verde_neon"], P["branco"], P["verde_neon"], "hn", "DocFeito"),
        "docfeito-logo-mono-tinta.svg": horizontal(wm, P["tinta"], P["tinta"], P["tinta"], P["tinta"], "mt", "DocFeito"),
        "docfeito-logo-mono-branco.svg": horizontal(wm, P["branco"], P["branco"], P["branco"], P["branco"], "mb", "DocFeito"),
        "docfeito-logo-vertical.svg": stacked(wm, P["tinta"], P["verde"], P["tinta"], P["verde"], "v", "DocFeito"),
        "docfeito-logo-vertical-negativo.svg": stacked(wm, P["branco"], P["verde_neon"], P["branco"], P["verde_neon"], "vn", "DocFeito"),
    }
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
    (OUT / "paleta.json").write_text(json.dumps(PALETTE, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(f"{OUT.name}/{n}" for n in files))


if __name__ == "__main__":
    main()
