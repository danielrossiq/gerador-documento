"""Bancada de fidelidade de formatação: quanto do visual do documento do usuário sobrevive no documento gerado.

Para cada arquivo de uma pasta:
  * PDF  → converte para .docx (o mesmo `convert_pdf` do produto), faz a ida e volta do editor com campos nos trechos
           que as regras detectam (CPF, datas, valores…) preenchidos com o PRÓPRIO texto original, gera o PDF com o
           LibreOffice do worker e compara com o PDF original;
  * DOCX → mesma ida e volta (ler → campos → compilar → preencher com o texto original) e compara o PDF do original
           com o PDF do resultado (ambos pelo mesmo LibreOffice: a diferença é só o que o nosso caminho mudou).

Métricas por documento (todas de 0 a 1, maior = mais fiel):
  texto     semelhança da sequência de palavras;
  posição   fração das palavras (casadas) que ficaram a até 6 pt de onde estavam, na mesma página;
  estilo    negrito/itálico/tamanho/tipo de fonte (mono, serifa, sem serifa) iguais nas palavras casadas;
  visual    F1 da "tinta" das páginas (pixels escuros, com 1 mm de tolerância) a 50 dpi;
  páginas   mesmo número de páginas (1) ou não (0).

Uso (o LibreOffice é o do contêiner do worker, o mesmo que gera os PDFs em produção):
  python -m app.eval.fidelity --src ~/Downloads --out /tmp/fidelidade [--only nome] [--limit N]

Privacidade: tudo local. O relatório (relatorio.json/.md) usa ids anônimos (D01, D02…); o mapa id → arquivo fica só
em `mapa.json`, na pasta de saída, para quem rodou.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.docx_engine.fontmetrics import compensate_widths

MB = 1024 * 1024
WORKER = "minuta-fase0-worker-1"
DPI = 50


# ------------------------------------------------------------------ ida e volta pelo editor


def roundtrip_docx(original: bytes) -> tuple[bytes, int]:
    """Lê, marca como campo cada trecho que as regras detectam, compila e preenche com o texto original.

    Devolve (docx gerado, nº de campos). Se o caminho preservasse tudo, o resultado seria idêntico ao original.
    """
    from app.docx_engine.compile import BlockSpec, compile_docx
    from app.docx_engine.nodes import replace_range_with_field
    from app.docx_engine.parse import parse_docx
    from app.docx_engine.render import CompiledTemplate
    from app.modules.suggestions.rules import detect_rules, resolve_overlaps

    parsed = parse_docx(original)
    paragraphs = [(b.key, b.text) for b in parsed.blocks if b.kind == "paragraph" and b.text.strip()]
    hits = resolve_overlaps(list(detect_rules(paragraphs)))
    by_block: dict[str, list[Any]] = {}
    for h in hits:
        by_block.setdefault(h.block_key, []).append(h)
    names: dict[str, str] = {}
    values: dict[str, str] = {}
    specs = []
    n = 0
    for b in parsed.blocks:
        content = b.content
        if b.kind == "paragraph":
            for h in sorted(by_block.get(b.key, []), key=lambda h: h.start, reverse=True):
                fid, name = f"f{n}", f"c{n}"
                try:
                    content, _ = replace_range_with_field(content, h.start, h.end, fid)
                except Exception:  # noqa: S112 - trecho que o editor não consegue marcar: fica como texto
                    continue
                names[fid], values[name] = name, h.text
                n += 1
        specs.append(BlockSpec(b.key, b.container_key, b.ordinal, b.kind, "original", content, None))
    compiled = compile_docx(
        original, specs, names, nonce="0f1de117"
    ).data  # nonce hexadecimal, como o do produto
    return CompiledTemplate(compiled).render(values), n


# ------------------------------------------------------------------ LibreOffice do worker


_FONTS: dict[str, frozenset[str]] = {}


def _container_fonts(container: str) -> frozenset[str]:
    if container not in _FONTS:
        out = subprocess.run(  # noqa: S603 - comando fixo (docker exec fc-list)
            ["docker", "exec", container, "fc-list", ":", "family"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        _FONTS[container] = frozenset(
            f.strip().lower() for line in out.stdout.splitlines() for f in line.split(",") if f.strip()
        )
    return _FONTS[container]


def render_pdfs(
    docx_files: list[Path], out_dir: Path, container: str = WORKER, chunk: int = 15, compensate: bool = True
) -> None:
    """Converte .docx → .pdf com o soffice do contêiner do worker (mesmas fontes e substituições da produção)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(docx_files), chunk):
        part = docx_files[i : i + chunk]
        with tempfile.TemporaryDirectory() as tmp:
            for f in part:
                data = f.read_bytes()
                if compensate:  # como o worker faz antes do LibreOffice (fontes ausentes: largura original)
                    data = compensate_widths(data, _container_fonts(container))
                (Path(tmp) / f.name).write_bytes(data)
            run = lambda *a: subprocess.run(a, check=False, capture_output=True, timeout=900)  # noqa: E731, S603
            run(
                "docker",
                "exec",
                container,
                "sh",
                "-c",
                "rm -rf /tmp/fid && mkdir -p /tmp/fid/in /tmp/fid/out",
            )
            run("docker", "cp", f"{tmp}/.", f"{container}:/tmp/fid/in/")
            run(
                "docker", "exec", container, "sh", "-c",
                "cd /tmp/fid && soffice -env:UserInstallation=file:///tmp/fid/profile --headless "
                "--convert-to pdf --outdir /tmp/fid/out /tmp/fid/in/*.docx",
            )  # fmt: skip
            run("docker", "cp", f"{container}:/tmp/fid/out/.", str(out_dir))


# ------------------------------------------------------------------ comparação


_MONO = re.compile(r"mono|courier|consolas|console|menlo|monaco|inconsolata|code", re.I)
_SERIF = re.compile(
    r"times|serif|georgia|garamond|cambria|caladea|book|palatino|bookman|tinos|century(?!gothic)", re.I
)


def font_class(fontname: str) -> str:
    name = (fontname or "").split("+", 1)[-1]
    if _MONO.search(name):
        return "mono"
    if _SERIF.search(name) and not re.search(r"sans", name, re.I):
        return "serif"
    return "sans"


def _is_bold(fontname: str) -> bool:
    return bool(re.search(r"bold|black|heavy|semibold|demi", fontname or "", re.I))


def _is_italic(fontname: str) -> bool:
    return bool(re.search(r"italic|oblique|[-,](it|bi)$", fontname or "", re.I))


@dataclass
class Word:
    text: str
    page: int
    x: float
    y: float
    size: float
    font: str


def words_of(pdf_bytes: bytes, max_pages: int = 40) -> tuple[list[Word], int]:
    import pdfplumber

    out: list[Word] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages[:max_pages]):
            for w in page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False):
                out.append(
                    Word(
                        w["text"],
                        i,
                        (w["x0"] + w["x1"]) / 2,
                        (w["top"] + w["bottom"]) / 2,
                        w["size"],
                        w["fontname"],
                    )
                )
    return out, n


def _ink(pdf_bytes: bytes, max_pages: int) -> list[Any]:
    import numpy as np
    import pypdfium2 as pdfium

    pages = []
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        for i in range(min(len(doc), max_pages)):
            img = doc[i].render(scale=DPI / 72, grayscale=True).to_pil().convert("L")
            pages.append(np.asarray(img) < 160)
    finally:
        doc.close()
    return pages


def _dilate(mask: Any, r: int = 2) -> Any:
    import numpy as np

    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def visual_f1(a_pdf: bytes, b_pdf: bytes, max_pages: int = 40) -> tuple[float, list[float]]:

    a_pages, b_pages = _ink(a_pdf, max_pages), _ink(b_pdf, max_pages)
    scores = []
    for i in range(max(len(a_pages), len(b_pages))):
        if i >= len(a_pages) or i >= len(b_pages):
            scores.append(0.0)
            continue
        a, b = a_pages[i], b_pages[i]
        h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
        a, b = a[:h, :w], b[:h, :w]
        na, nb = int(a.sum()), int(b.sum())
        if na == 0 and nb == 0:
            scores.append(1.0)
            continue
        recall = float((a & _dilate(b)).sum()) / max(na, 1)
        precision = float((b & _dilate(a)).sum()) / max(nb, 1)
        scores.append(0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision))
    return (statistics.fmean(scores) if scores else 0.0), scores


@dataclass
class Scores:
    texto: float = 0.0
    posicao: float = 0.0
    estilo: float = 0.0
    visual: float = 0.0
    paginas: float = 0.0
    detalhes: dict[str, Any] = field(default_factory=dict)

    @property
    def geral(self) -> float:
        return round(
            0.25 * self.texto
            + 0.25 * self.posicao
            + 0.2 * self.estilo
            + 0.2 * self.visual
            + 0.1 * self.paginas,
            4,
        )


def match_words(a: list[Word], b: list[Word]) -> list[tuple[Word, Word]]:
    """Casa cada palavra do original com a MESMA palavra mais próxima no gerado (mesma página de preferência),
    sem depender da ordem de leitura — linhas com alturas quase iguais trocam de ordem na extração e isso não
    é perda de formatação."""
    pool: dict[str, list[Word]] = {}
    for w in b:
        pool.setdefault(w.text, []).append(w)
    candidates = []
    for i, wa in enumerate(a):
        for j, wb in enumerate(pool.get(wa.text, [])):
            d = abs(wa.x - wb.x) + abs(wa.y - wb.y) + (10_000 if wa.page != wb.page else 0)
            candidates.append((d, i, wa.text, j))
    candidates.sort(key=lambda t: t[0])
    used_a: set[int] = set()
    used_b: set[tuple[str, int]] = set()
    pairs = []
    for _, i, text, j in candidates:
        if i in used_a or (text, j) in used_b:
            continue
        used_a.add(i)
        used_b.add((text, j))
        pairs.append((a[i], pool[text][j]))
    return pairs


def compare(orig_pdf: bytes, out_pdf: bytes) -> Scores:
    a, na = words_of(orig_pdf)
    b, nb = words_of(out_pdf)
    pairs = match_words(a, b)
    common = sum((Counter(w.text for w in a) & Counter(w.text for w in b)).values())
    near = [
        p for p in pairs if p[0].page == p[1].page and abs(p[0].x - p[1].x) <= 6 and abs(p[0].y - p[1].y) <= 6
    ]
    same_style = [
        p
        for p in pairs
        if _is_bold(p[0].font) == _is_bold(p[1].font)
        and _is_italic(p[0].font) == _is_italic(p[1].font)
        and abs(p[0].size - p[1].size) <= 0.6
        and font_class(p[0].font) == font_class(p[1].font)
    ]
    vis, per_page = visual_f1(orig_pdf, out_pdf)
    dys = [p[1].y - p[0].y for p in pairs if p[0].page == p[1].page]
    dxs = [p[1].x - p[0].x for p in pairs if p[0].page == p[1].page]

    def frac(sub: list[Any]) -> float:
        return round(len(sub) / len(pairs), 4) if pairs else 0.0

    reasons: dict[str, float] = {}
    for kind, test in (
        ("negrito", lambda p: _is_bold(p[0].font) != _is_bold(p[1].font)),
        ("italico", lambda p: _is_italic(p[0].font) != _is_italic(p[1].font)),
        ("tamanho", lambda p: abs(p[0].size - p[1].size) > 0.6),
        ("tipo_fonte", lambda p: font_class(p[0].font) != font_class(p[1].font)),
    ):
        reasons[kind] = frac([p for p in pairs if test(p)])
    return Scores(
        texto=round(2 * common / (len(a) + len(b)), 4) if a or b else 1.0,
        posicao=frac(near),
        estilo=frac(same_style),
        visual=round(vis, 4),
        paginas=1.0 if na == nb else 0.0,
        detalhes={
            "paginas_original": na,
            "paginas_gerado": nb,
            "palavras_original": len(a),
            "palavras_gerado": len(b),
            "desvio_mediano_x_pt": round(statistics.median(dxs), 1) if dxs else None,
            "desvio_mediano_y_pt": round(statistics.median(dys), 1) if dys else None,
            "visual_por_pagina": [round(s, 3) for s in per_page],
            "diferencas_estilo": reasons,
        },
    )


def side_by_side(orig_pdf: bytes, out_pdf: bytes, page: int, dest: Path) -> None:
    import pypdfium2 as pdfium
    from PIL import Image

    imgs = []
    for data in (orig_pdf, out_pdf):
        doc = pdfium.PdfDocument(data)
        try:
            img = doc[min(page, len(doc) - 1)].render(scale=1.1).to_pil().convert("RGB")
        finally:
            doc.close()
        imgs.append(img)
    w = sum(i.width for i in imgs) + 20
    h = max(i.height for i in imgs)
    canvas = Image.new("RGB", (w, h), (120, 120, 120))
    canvas.paste(imgs[0], (0, 0))
    canvas.paste(imgs[1], (imgs[0].width + 20, 0))
    canvas.save(dest)


# ------------------------------------------------------------------ execução


@dataclass
class DocResult:
    id: str
    tipo: str  # pdf | docx
    status: str  # ok | recusado:<código> | erro:<tipo>
    paginas: int | None = None
    campos: int = 0
    segundos: float = 0.0
    scores: dict[str, Any] | None = None
    geral: float | None = None


def run(
    src: Path,
    out: Path,
    only: str | None = None,
    limit: int | None = None,
    container: str = WORKER,
    mode: str = "auto",
) -> list[DocResult]:
    from app.docx_engine.pdf_import import convert_pdf
    from app.docx_engine.safety import DocxRejected

    out.mkdir(parents=True, exist_ok=True)
    for sub in ("docx", "pdf", "orig_docx", "orig_pdf", "comparar"):
        (out / sub).mkdir(exist_ok=True)
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in (".pdf", ".docx") and p.is_file())
    if only:
        files = [p for p in files if re.search(only, p.name, re.I)]
    if limit:
        files = files[:limit]
    mapping = {f"D{i + 1:02d}": p.name for i, p in enumerate(files)}
    (out / "mapa.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    results: list[DocResult] = []
    to_render: list[Path] = []
    for (doc_id, _), path in zip(mapping.items(), files, strict=True):
        t0 = time.monotonic()
        kind = path.suffix.lower().lstrip(".")
        res = DocResult(doc_id, kind, "ok")
        try:
            data = path.read_bytes()
            if kind == "pdf":
                docx = convert_pdf(data, max_bytes=64 * MB, mode=mode).docx
            else:
                docx = data
                (out / "orig_docx" / f"{doc_id}.docx").write_bytes(data)
                to_render.append(out / "orig_docx" / f"{doc_id}.docx")
            final, res.campos = roundtrip_docx(docx)
            (out / "docx" / f"{doc_id}.docx").write_bytes(final)
            to_render.append(out / "docx" / f"{doc_id}.docx")
        except DocxRejected as exc:
            res.status = f"recusado:{exc.code}"
        except Exception as exc:
            res.status = f"erro:{type(exc).__name__}"
        res.segundos = round(time.monotonic() - t0, 1)
        results.append(res)
        print(f"{doc_id} {kind} {res.status} {res.segundos}s", flush=True)

    print(f"renderizando {len(to_render)} documentos no LibreOffice do worker…", flush=True)
    render_pdfs([p for p in to_render if "orig_docx" in str(p)], out / "orig_pdf", container)
    render_pdfs([p for p in to_render if "orig_docx" not in str(p)], out / "pdf", container)

    for res, path in zip(results, files, strict=True):
        if res.status != "ok":
            continue
        out_pdf = out / "pdf" / f"{res.id}.pdf"
        orig_pdf = (
            path.read_bytes()
            if res.tipo == "pdf"
            else (out / "orig_pdf" / f"{res.id}.pdf").read_bytes()
            if (out / "orig_pdf" / f"{res.id}.pdf").exists()
            else None
        )
        if not out_pdf.exists() or orig_pdf is None:
            res.status = "erro:render"
            continue
        try:
            sc = compare(orig_pdf, out_pdf.read_bytes())
        except Exception as exc:
            res.status = f"erro:comparar:{type(exc).__name__}"
            continue
        res.paginas = sc.detalhes["paginas_original"]
        res.scores = {**{k: v for k, v in asdict(sc).items() if k != "detalhes"}, **sc.detalhes}
        res.geral = sc.geral
        worst = min(
            range(len(sc.detalhes["visual_por_pagina"])),
            key=lambda i: sc.detalhes["visual_por_pagina"][i],
            default=0,
        )
        side_by_side(orig_pdf, out_pdf.read_bytes(), worst, out / "comparar" / f"{res.id}_p{worst + 1}.png")
    write_report(results, out)
    return results


def write_report(results: list[DocResult], out: Path) -> None:
    ok = [r for r in results if r.status == "ok" and r.scores]
    (out / "relatorio.json").write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# Fidelidade de formatação", ""]
    if ok:

        def avg(k: str, rs: list[DocResult]) -> float:
            return round(statistics.fmean(r.scores[k] for r in rs) * 100, 1)

        for kind in ("pdf", "docx"):
            rs = [r for r in ok if r.tipo == kind]
            if rs:
                lines.append(
                    f"**{kind.upper()}** ({len(rs)} docs): geral {round(statistics.fmean(r.geral for r in rs) * 100, 1)}% · "
                    f"texto {avg('texto', rs)}% · posição {avg('posicao', rs)}% · estilo {avg('estilo', rs)}% · "
                    f"visual {avg('visual', rs)}% · mesmas páginas {avg('paginas', rs)}%"
                )
        lines.append("")
    statuses: dict[str, int] = {}
    for r in results:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    lines += ["Status: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())), ""]
    lines += [
        "| id | tipo | pág. | campos | geral | texto | posição | estilo | visual | págs | dif. estilo |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in sorted(ok, key=lambda r: r.geral or 0):
        s = r.scores
        dif = ", ".join(f"{k} {round(v * 100)}%" for k, v in s["diferencas_estilo"].items() if v >= 0.02)
        lines.append(
            f"| {r.id} | {r.tipo} | {r.paginas} | {r.campos} | {round(r.geral * 100)}% | {round(s['texto'] * 100)}% | "
            f"{round(s['posicao'] * 100)}% | {round(s['estilo'] * 100)}% | {round(s['visual'] * 100)}% | "
            f"{s['paginas_original']}→{s['paginas_gerado']} | {dif} |"
        )
    (out / "relatorio.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:6]))


def rescore(src: Path, out: Path) -> None:
    """Recalcula as métricas de uma rodada já renderizada (ex.: depois de mudar a métrica)."""
    mapping = json.loads((out / "mapa.json").read_text(encoding="utf-8"))
    results = [
        DocResult(**r)
        for r in json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
    ]
    for res in results:
        out_pdf = out / "pdf" / f"{res.id}.pdf"
        if res.scores is None or not out_pdf.exists():
            continue
        orig = (
            (src / mapping[res.id]).read_bytes()
            if res.tipo == "pdf"
            else (out / "orig_pdf" / f"{res.id}.pdf").read_bytes()
        )
        sc = compare(orig, out_pdf.read_bytes())
        res.scores = {**{k: v for k, v in asdict(sc).items() if k != "detalhes"}, **sc.detalhes}
        res.geral = sc.geral
    write_report(results, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--container", default=WORKER)
    ap.add_argument("--mode", default="auto", choices=["auto", "flow", "layout"])
    ap.add_argument("--rescore", action="store_true", help="só recalcula as métricas de uma rodada existente")
    a = ap.parse_args(argv)
    if a.rescore:
        rescore(a.src, a.out)
    else:
        run(a.src, a.out, a.only, a.limit, a.container, a.mode)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(main())
