"""Otimiza as capturas reais do produto para a landing (landing-spec-v2 §9) e grava o JSON que a página importa.

Uso (sem custo, com a stack local no ar):
    cd frontend && SITE_CAPTURES=/tmp/capturas npx playwright test e2e/site-captures.spec.ts
    python scripts/site_captures.py /tmp/capturas

Entrada: tela-editor-desktop.png, tela-editor-mobile.png e tela-preencher-mobile.png (DPR 2, dados fictícios da conta
de demonstração). Saída: AVIF/WebP sem metadados em frontend/public/site/ e
frontend/src/components/landing/site-captures.json (arquivos, dimensões e alt). Reaproveita a otimização do
gerador de mídia (scripts/generate_site_media.py); não chama nenhuma API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_site_media as gsm

OUT_JSON = gsm.ROOT / "frontend" / "src" / "components" / "landing" / "site-captures.json"

# Alt conforme os campos que aparecem de fato no modelo de demonstração (contrato de prestação de serviços).
CAPTURES = {
    "tela-editor-desktop": {
        "widths": [800, 1200, 1600, 2400],
        "alt": (
            "Editor do Minuta com um contrato de exemplo: campos como Nome do contratante, CPF do contratante e "
            "Valor mensal aparecem marcados no texto e listados ao lado."
        ),
    },
    "tela-editor-mobile": {
        "widths": [300, 600, 780],
        "alt": "Editor no celular com campos marcados no texto de um contrato de exemplo.",
    },
    "tela-preencher-mobile": {
        "widths": [300, 600, 780],
        "alt": "Formulário de preenchimento no celular com dados de exemplo.",
    },
}


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("uso: python scripts/site_captures.py <pasta com os PNGs>")
    src_dir = Path(sys.argv[1])
    data = {}
    for slug, spec in CAPTURES.items():
        src = src_dir / f"{slug}.png"
        if not src.is_file():
            raise SystemExit(f"captura ausente: {src}")
        gsm.check_image(src.read_bytes())
        variants = gsm.optimize_image(slug, src, spec["widths"])
        data[slug] = {
            "alt": spec["alt"],
            "variants": [{k: v[k] for k in ("file", "width", "height")} for v in variants],
        }
        print(
            f"ok {slug}: {', '.join(f'{v["width"]}w {v["bytes"] // 1024} KB' for v in variants if v['file'].endswith('.avif'))}"
        )
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
