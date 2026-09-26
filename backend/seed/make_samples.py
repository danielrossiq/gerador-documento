"""Gera os arquivos de demonstração em ../demo: contrato .docx, lote .xlsx (com 1 linha inválida) e lote .csv.

Uso: python -m seed.make_samples
"""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from app.modules.samples.documents import build_demo_contract
from seed.seed import SAMPLE_ROWS

HEADERS = [
    "Nome do contratante",
    "CPF do contratante",
    "Tipo de serviço",
    "Valor mensal",
    "Data de início",
    "Renovação automática",
]
KEYS = [
    "nome_do_contratante",
    "cpf_do_contratante",
    "tipo_de_servico",
    "valor_mensal",
    "data_de_inicio",
    "renovacao_automatica",
]


def main() -> None:
    out = Path(__file__).resolve().parents[2] / "demo"
    out.mkdir(exist_ok=True)
    (out / "contrato_prestacao_servicos.docx").write_bytes(build_demo_contract())
    wb = Workbook()
    ws = wb.active
    ws.title = "Lote"
    ws.append(HEADERS)
    for r in SAMPLE_ROWS:
        ws.append([r[k] for k in KEYS])
    wb.save(out / "lote_exemplo.xlsx")
    with (out / "lote_exemplo.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(HEADERS)
        for r in SAMPLE_ROWS:
            w.writerow([r[k] for k in KEYS])
    print(f"gerados em {out}: contrato_prestacao_servicos.docx, lote_exemplo.xlsx, lote_exemplo.csv")


if __name__ == "__main__":
    main()
