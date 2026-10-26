"""Quanto custa GERAR documentos a partir de um modelo aceito com ~240 MB descomprimidos (240 partes de 1 MB - 1
de zeros, abaixo do limiar da checagem de razão de compressão). Usa o stack local.

    python scripts/stress/bomb_generation.py [--rows 5]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import payloads as P
from lib import API, MemoryProbe, Session, fake_email, random_ip


async def main_async(rows: int, demo: bool) -> None:
    async with Session(API, xff=random_ip()) as s:
        await s.register(fake_email("bomba"))
        gid = (await s.post("/generators", json={"name": "Bomba"})).json()["id"]
        data = P.demo_docx() if demo else P.sub_threshold_bomb_docx()
        up = await s.post(f"/generators/{gid}/template", files={"file": ("contrato.docx", data, "application/octet-stream")})
        print(f"upload ({len(data) // 1024} KB) -> {up.status_code}")
        f = await s.post(f"/generators/{gid}/fields", json={"label": "Nome", "type": "text_short"})
        print("campo ->", f.status_code)
        with MemoryProbe() as probe:
            t = time.perf_counter()
            r = await s.post(f"/generators/{gid}/batches", json={"rows": [{"nome": f"Pessoa {i}"} for i in range(rows)]})
            print("lote ->", r.status_code, r.text[:200] if r.status_code >= 400 else "")
            if r.status_code < 300:
                jid = r.json()["id"]
                while True:
                    j = (await s.get(f"/jobs/{jid}")).json()
                    if j["status"] not in ("queued", "processing"):
                        break
                    await asyncio.sleep(1)
                took = time.perf_counter() - t
                sizes = [x.get("size_bytes") for x in j.get("files") or []]
                print(f"job {j['status']} em {took:.1f}s para {rows} linha(s); arquivos: {sizes}")
        print(f"memória da API: {probe.start_mb} -> pico {probe.peak_mb} MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--demo", action="store_true", help="mesmo teste com o contrato de demonstração (comparação)")
    a = ap.parse_args()
    asyncio.run(main_async(a.rows, a.demo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
