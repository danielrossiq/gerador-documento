"""Validade e limpeza do teste grátis no stack local (rode com TRIAL_TTL_MINUTES=1 na API).

    TRIAL_TTL_MINUTES=1 scripts/stack_local.sh restart-api
    python scripts/stress/trial_expiry.py [--wait 420]

Cria um teste, confere que vence (consulta e claim → 404) e espera a limpeza do watchdog (a cada 5 min) apagar
o arquivo e a linha. Usa o banco e o storage do stack (backend/data/stack/).
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
import payloads as P
from lib import API, ROOT, Session, fake_email, random_ip

DB = ROOT / "backend" / "data" / "stack" / "stack.db"
STORAGE = ROOT / "backend" / "data" / "stack" / "storage"


def row(token: str) -> tuple | None:
    """Linha do teste (o banco guarda só o hash do token)."""
    with sqlite3.connect(DB) as c:
        return c.execute(
            "select status, storage_key, expires_at from trials where token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()


def file_exists(key: str | None) -> bool:
    return bool(key) and (STORAGE / key).exists()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=420, help="segundos esperando a limpeza")
    args = ap.parse_args()
    c = httpx.Client(base_url=API, timeout=60, headers={"X-Forwarded-For": random_ip()})
    r = c.post("/api/v1/public/trials", files={"file": ("contrato.docx", P.demo_docx(), "application/octet-stream")})
    assert r.status_code == 202, r.text
    token = r.json()["token"]
    print("criado; vence em", r.json().get("expires_at"))
    for _ in range(60):
        st = c.get(f"/api/v1/public/trials/{token}").json()
        if st["status"] in ("done", "failed"):
            break
        time.sleep(1)
    first = row(token)
    key = first[1] if first else None
    print("status:", st["status"], "| linha:", first, "| arquivo existe:", file_exists(key))
    t0 = time.time()
    while time.time() - t0 < 75:
        if c.get(f"/api/v1/public/trials/{token}").status_code == 404:
            break
        time.sleep(5)
    print(f"consulta depois de {time.time() - t0:.0f}s ->", c.get(f"/api/v1/public/trials/{token}").status_code)
    import asyncio

    async def try_claim() -> int:
        async with Session(API, xff=random_ip()) as s:
            await s.register(fake_email("expira"))
            return (await s.post(f"/trials/{token}/claim")).status_code

    print("claim do teste vencido ->", asyncio.run(try_claim()))
    t1 = time.time()
    while time.time() - t1 < args.wait:
        if row(token) is None and not file_exists(key):
            print(f"limpeza concluída {time.time() - t1:.0f}s depois de vencer (linha e arquivo apagados)")
            return 0
        time.sleep(10)
    print(f"LIMPEZA NÃO ACONTECEU em {args.wait}s: linha={row(token)} arquivo existe={file_exists(key)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
