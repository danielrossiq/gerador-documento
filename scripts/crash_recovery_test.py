"""Teste real de queda do worker: cria um lote grande (DOCX+PDF), mata o worker com SIGKILL no meio,
religa e verifica que o job é retomado sozinho, termina 100 % e não deixa arquivos duplicados.

Pré-requisito: `docker compose up -d` (projeto padrão `minuta`) e os dados de demonstração (`SEED_DEMO=true`).
Uso:  python scripts/crash_recovery_test.py [linhas=400] [matar_apos=100]
Variáveis: API_BASE (padrão http://localhost:8100/api/v1), COMPOSE_PROJECT (padrão minuta).
Só usa a biblioteca padrão. Sai com código 0 se a retomada funcionou.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("API_BASE", "http://localhost:8100/api/v1")
PROJECT = os.environ.get("COMPOSE_PROJECT", "minuta")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
KILL_AT = int(sys.argv[2]) if len(sys.argv) > 2 else 100
TIMEOUT = 420  # s após o crash; o esperado é ≈ 90 s (JOB_STALE_SECONDS + WATCHDOG_INTERVAL_SECONDS + retomada)

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
csrf: dict[str, str | None] = {"v": None}
t0 = time.time()


def log(msg: str) -> None:
    print(f"[t={time.time() - t0:6.1f}s] {msg}", flush=True)


def call(method: str, path: str, body: object = None, headers: dict[str, str] | None = None):
    h = {"Content-Type": "application/json", "Origin": "http://localhost:3000"}
    if csrf["v"]:
        h["X-CSRF-Token"] = csrf["v"]
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with opener.open(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT, *args], capture_output=True, text=True, cwd=ROOT, check=False
    )


def psql(sql: str) -> str:
    r = compose("exec", "-T", "postgres", "psql", "-U", "minuta", "-d", "minuta", "-At", "-c", sql)
    return r.stdout.strip()


def main() -> int:
    st, me = call("POST", "/auth/login", {"email": "demo@minuta.app", "password": "demo12345"})
    assert st == 200, me
    csrf["v"] = me["csrf_token"]
    st, gens = call("GET", "/generators")
    gid = (gens if isinstance(gens, list) else gens["items"])[0]["id"]
    rows = [
        {
            "nome_do_contratante": f"Cliente {i:04d}",
            "cpf_do_contratante": "529.982.247-25",
            "cnpj_da_contratada": "11.222.333/0001-81",
            "tipo_de_servico": "Suporte técnico mensal",
            "valor_mensal": "1.234,50",
            "data_de_inicio": "15/11/2026",
            "renovacao_automatica": "Não",
        }
        for i in range(1, N + 1)
    ]
    st, job = call(
        "POST",
        f"/generators/{gid}/batches",
        {"rows": rows, "format": "both"},
        {"Idempotency-Key": f"crash-{int(time.time())}"},
    )
    assert st == 202, (st, job)
    jid = job["id"]
    log(f"job {jid[:8]} criado: {N} linhas, DOCX+PDF")

    while True:
        _, j = call("GET", f"/jobs/{jid}")
        done = j["succeeded_items"] + j["failed_items"]
        if done >= KILL_AT or j["status"] not in ("queued", "processing"):
            break
        time.sleep(0.5)
    log(f"progresso {done}/{N} status={j['status']} -> MATANDO o worker (SIGKILL)")
    if j["status"] != "processing":
        log("o lote terminou antes de matar o worker; aumente as linhas")
        return 1
    t_kill = time.time()
    compose("kill", "worker")  # SIGKILL: sem shutdown gracioso

    time.sleep(3)
    _, j = call("GET", f"/jobs/{jid}")
    log(f"logo após o crash: status={j['status']} feitos={j['succeeded_items'] + j['failed_items']}/{N} (parado)")
    compose("start", "worker")
    log("worker religado; aguardando o watchdog detectar o heartbeat velho e reenfileirar...")

    final, last = None, None
    while time.time() - t_kill < TIMEOUT:
        _, j = call("GET", f"/jobs/{jid}")
        cur = (j["status"], j["succeeded_items"] + j["failed_items"])
        if cur != last:
            log(f"status={cur[0]} feitos={cur[1]}/{N}")
            last = cur
        if j["status"] not in ("queued", "processing"):
            final = j
            break
        time.sleep(2)
    if final is None:
        log("TIMEOUT: o job não foi retomado")
        return 1

    log(
        f"FINAL: {final['status']} ok={final['succeeded_items']} falhas={final['failed_items']} "
        f"| recuperação após o crash: {time.time() - t_kill:.0f}s"
    )
    print("tentativas do job:", psql(f"select attempts from generation_jobs where id='{jid}'"))
    print("arquivos por tipo (linhas | itens distintos):")
    print(
        psql(
            f"select kind, count(*), count(distinct item_id) from generated_files "
            f"where job_id='{jid}' group by kind order by kind"
        )
    )
    dup = psql(
        f"select count(*) from (select item_id, kind from generated_files where job_id='{jid}' "
        f"and item_id is not null group by 1,2 having count(*)>1) x"
    )
    print("itens com arquivo duplicado:", dup)
    ok = final["status"] == "succeeded" and final["succeeded_items"] == N and dup == "0"
    print("RESULTADO:", "OK — retomou sem duplicar" if ok else "FALHOU")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
