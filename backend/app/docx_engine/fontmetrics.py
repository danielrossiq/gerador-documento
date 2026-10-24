"""Compensação de largura de fontes ausentes no servidor que gera o PDF.

O PDF é gerado pelo LibreOffice do worker, que não tem as fontes do Windows/Office nem as que vêm dentro de PDFs. A
fonte substituta (fonts-local.conf) é do mesmo tipo, mas raramente da mesma largura: Consolas → Liberation Mono é
8% mais larga, Georgia → Liberation Serif 9% mais estreita… As linhas quebram em outros lugares e o documento pode
ganhar uma página (a assinatura vai parar sozinha na folha seguinte).

Solução: na hora de gerar o PDF — e só ali — o texto numa fonte ausente recebe a escala horizontal (w:w) que
devolve a largura original. O .docx que a pessoa baixa não muda: no Word dela, com a fonte de verdade, ele já está
certo. A proporção vem de:
  * uma tabela medida para fontes comuns do Windows/Office (`STATIC_RATIOS`), para .docx enviados;
  * o próprio PDF, na conversão: largura dos caracteres no PDF ÷ largura na Liberation equivalente
    (`liberation_widths.json`), gravada no .docx como variável de documento (`minutaFontScale`).
"""

from __future__ import annotations

import functools
import io
import json
import re
import subprocess
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
DOC_VAR = "minutaFontScale"
MIN_DIFF = 0.015  # abaixo disso (1,5%) a diferença não muda quebra de linha que valha a distorção

# largura de um parágrafo-padrão em português (fonte original ÷ substituta do worker), medida com as fontes do
# Windows 11 e as do worker (ver docs/FIDELIDADE.md). Fontes com equivalente de mesma métrica (Arial, Times New
# Roman, Courier New, Calibri, Cambria, Helvetica) e as instaladas no worker não precisam de compensação.
STATIC_RATIOS: dict[str, float] = {
    "consolas": 0.917,
    "segoe ui": 0.973,
    "tahoma": 0.984,
    "georgia": 1.090,
    "century gothic": 1.069,
    "garamond": 0.969,
    "book antiqua": 1.089,
    "palatino linotype": 1.088,
    "bookman old style": 1.212,
    "arial narrow": 0.821,
    "candara": 0.921,
    "corbel": 0.905,
    "constantia": 1.058,
}
METRIC_COMPATIBLE = {
    "arial",
    "helvetica",
    "times new roman",
    "times",
    "courier new",
    "courier",
    "calibri",
    "cambria",
}


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


@functools.cache
def _liberation() -> dict[str, dict[str, int]]:
    data = json.loads((Path(__file__).parent / "data" / "liberation_widths.json").read_text(encoding="utf-8"))
    data.pop("_doc", None)
    return data


def substitute_width(text: str, kind: str, bold: bool, italic: bool) -> float:
    """Largura (em milésimos de em) do texto na Liberation do mesmo tipo ("sans" | "serif" | "mono")."""
    if kind == "mono":
        suffix = "-bold" if bold else ""
    else:
        suffix = "-bolditalic" if bold and italic else "-bold" if bold else "-italic" if italic else ""
    table = _liberation().get(kind + suffix) or _liberation()[kind]
    avg = sum(table.values()) / len(table)
    return float(sum(table.get(ch, avg) for ch in text))


def ratio_from_samples(orig_width: float, subst_width: float, chars: int) -> float | None:
    """Proporção original ÷ substituta, se houver amostra suficiente e diferença que importe."""
    if chars < 40 or subst_width <= 0:
        return None
    r = orig_width / subst_width
    if abs(r - 1) < MIN_DIFF or not 0.6 <= r <= 1.6:
        return None
    return round(r, 3)


# ------------------------------------------------------------------ variável de documento (conversão de PDF)


def write_scale_var(docx: bytes, ratios: dict[str, float]) -> bytes:
    """Grava {família: proporção} em word/settings.xml (w:docVars), que o Word preserva e o worker lê."""
    if not ratios:
        return docx
    zin = zipfile.ZipFile(io.BytesIO(docx))
    root = etree.fromstring(zin.read("word/settings.xml"))
    value = ";".join(f"{fam}={r}" for fam, r in sorted(ratios.items()))
    dvs = root.find(_w("docVars"))
    if dvs is None:
        dvs = etree.Element(_w("docVars"))
        # ordem do esquema (CT_Settings): docVars vem depois de compat e antes de rsids/mathPr/themeFontLang…
        after = [
            "rsids", "mathPr", "attachedSchema", "themeFontLang", "clrSchemeMapping", "doNotIncludeSubdocsInStats",
            "doNotAutoCompressPictures", "forceUpgrade", "captions", "readModeInkLockDown", "smartTagType",
            "schemaLibrary", "shapeDefaults", "doNotEmbedSmartTags", "decimalSymbol", "listSeparator",
        ]  # fmt: skip
        nxt = next((el for el in root if etree.QName(el).localname in after), None)
        if nxt is not None:
            nxt.addprevious(dvs)
        else:
            root.append(dvs)
    for dv in dvs.findall(_w("docVar")):
        if dv.get(_w("name")) == DOC_VAR:
            dvs.remove(dv)
    dv = etree.SubElement(dvs, _w("docVar"))
    dv.set(_w("name"), DOC_VAR)
    dv.set(_w("val"), value)
    return _replace_parts(
        zin,
        {"word/settings.xml": etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)},
    )


def read_scale_var(zin: zipfile.ZipFile) -> dict[str, float]:
    try:
        root = etree.fromstring(zin.read("word/settings.xml"))
    except KeyError:
        return {}
    for dv in root.iter(_w("docVar")):
        if dv.get(_w("name")) == DOC_VAR:
            out = {}
            for part in (dv.get(_w("val")) or "").split(";"):
                fam, _, val = part.rpartition("=")
                try:
                    out[fam.strip().lower()] = float(val)
                except ValueError:
                    continue
            return out
    return {}


def _replace_parts(zin: zipfile.ZipFile, parts: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, parts.get(info.filename, zin.read(info.filename)))
    return out.getvalue()


# ------------------------------------------------------------------ compensação (worker, antes do LibreOffice)


@functools.cache
def installed_families() -> frozenset[str]:
    """Famílias de fonte instaladas neste servidor (fontconfig)."""
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=15).stdout  # noqa: S607
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    fams = {f.strip().lower() for line in out.splitlines() for f in line.split(",") if f.strip()}
    return frozenset(fams)


def _theme_fonts(zin: zipfile.ZipFile) -> dict[str, str]:
    for name in zin.namelist():
        if name.startswith("word/theme/") and name.endswith(".xml"):
            root = etree.fromstring(zin.read(name))
            out = {}
            for kind in ("major", "minor"):
                el = root.find(f".//{{{A_NS}}}{kind}Font/{{{A_NS}}}latin")
                if el is not None and el.get("typeface"):
                    out[kind] = el.get("typeface")
            return out
    return {}


def _rfonts_name(rpr: Any, theme: dict[str, str]) -> str | None:
    if rpr is None:
        return None
    rf = rpr.find(_w("rFonts"))
    if rf is None:
        return None
    name = rf.get(_w("ascii")) or rf.get(_w("hAnsi"))
    if name:
        return name
    t = rf.get(_w("asciiTheme")) or rf.get(_w("hAnsiTheme"))
    if t:
        return theme.get("major" if t.startswith("major") else "minor")
    return None


def compensate_widths(docx: bytes, installed: Iterable[str] | None = None) -> bytes:
    """Aplica a escala horizontal (w:w) ao texto em fontes ausentes no servidor, com a proporção medida.

    Nunca levanta exceção: em qualquer problema devolve o .docx como veio (o PDF sai, só sem a compensação)."""
    try:
        return _compensate(
            docx, frozenset(f.lower() for f in installed) if installed is not None else installed_families()
        )
    except Exception:
        return docx


def _compensate(docx: bytes, installed: frozenset[str]) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(docx))
    ratios = {**STATIC_RATIOS, **read_scale_var(zin)}

    def scale_for(font: str | None) -> float | None:
        if not font:
            return None
        f = font.strip().lower()
        if f in installed or f in METRIC_COMPATIBLE:
            return None
        r = ratios.get(f)
        return r if r and abs(r - 1) >= MIN_DIFF else None

    theme = _theme_fonts(zin)
    styles_root = (
        etree.fromstring(zin.read("word/styles.xml")) if "word/styles.xml" in zin.namelist() else None
    )
    style_font: dict[str, str | None] = {}
    based: dict[str, str | None] = {}
    default_font: str | None = None
    default_para_style: str | None = None
    if styles_root is not None:
        dd = styles_root.find(f"{_w('docDefaults')}/{_w('rPrDefault')}/{_w('rPr')}")
        default_font = _rfonts_name(dd, theme)
        for st in styles_root.findall(_w("style")):
            sid = st.get(_w("styleId"))
            style_font[sid] = _rfonts_name(st.find(_w("rPr")), theme)
            b = st.find(_w("basedOn"))
            based[sid] = b.get(_w("val")) if b is not None else None
            if st.get(_w("type")) == "paragraph" and st.get(_w("default")) in ("1", "true"):
                default_para_style = sid

    def resolve(style_id: str | None) -> str | None:
        seen = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            if style_font.get(style_id):
                return style_font[style_id]
            style_id = based.get(style_id)
        return None

    changed: dict[str, bytes] = {}
    targets = [
        n
        for n in zin.namelist()
        if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", n)
    ]
    for name in targets:
        root = etree.fromstring(zin.read(name))
        touched = False
        for p in root.iter(_w("p")):
            ppr = p.find(_w("pPr"))
            ps = ppr.find(_w("pStyle")) if ppr is not None else None
            para_font = (
                resolve(ps.get(_w("val")) if ps is not None else default_para_style)
                or resolve(default_para_style)
                or default_font
            )
            for r in p.iter(_w("r")):
                if r.find(_w("t")) is None:
                    continue
                rpr = r.find(_w("rPr"))
                rs = rpr.find(_w("rStyle")) if rpr is not None else None
                font = (
                    _rfonts_name(rpr, theme)
                    or (resolve(rs.get(_w("val"))) if rs is not None else None)
                    or para_font
                )
                scale = scale_for(font)
                if scale is None:
                    continue
                if rpr is None:
                    rpr = etree.Element(_w("rPr"))
                    r.insert(0, rpr)
                ww = rpr.find(_w("w"))
                base = (
                    int(ww.get(_w("val"))) if ww is not None and (ww.get(_w("val")) or "").isdigit() else 100
                )
                if ww is None:
                    ww = etree.Element(_w("w"))
                    _insert_rpr_child(rpr, ww)
                ww.set(_w("val"), str(max(1, min(600, round(base * scale)))))  # Consolas: 100 × 0,917 = 92%
                touched = True
        if touched:
            changed[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return _replace_parts(zin, changed) if changed else docx


# ordem do esquema dentro de w:rPr: w:w vem depois de spacing/... e antes de kern/position/sz…
_RPR_AFTER_W = (
    "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs",
    "em", "lang", "eastAsianLayout", "specVanish", "oMath",
)  # fmt: skip


def _insert_rpr_child(rpr: Any, el: Any) -> None:
    nxt = next((c for c in rpr if etree.QName(c).localname in _RPR_AFTER_W), None)
    if nxt is not None:
        nxt.addprevious(el)
    else:
        rpr.append(el)
