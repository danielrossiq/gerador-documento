"""Stack local de TESTE, sem Docker: IA falsa + API (SQLite, jobs em thread) + front (next dev --webpack).

Use pelo atalho `scripts/stack_local.sh` (acha o venv da pasta principal) ou direto com o Python do venv:

    scripts/stack_local.sh up [--fresh] [--no-web] [--no-seed] [--ai "--latency-ms 2000 --rate-429 0.1"]
    scripts/stack_local.sh down        derruba a árvore de processos de cada serviço
    scripts/stack_local.sh status      o que está no ar + contadores da IA falsa
    scripts/stack_local.sh seed        dados de demonstração (demo@docfeito.com.br / demo12345)
    scripts/stack_local.sh logs api    últimas linhas do log (ai | api | web | seed)
    scripts/stack_local.sh env         variáveis da API (para rodar CLI/pytest contra o mesmo banco)

Portas (padrão: as do agente de testes na sprint), pelo ambiente: API_PORT=8150 WEB_PORT=3350 AI_PORT=8151.
Estado e logs em backend/data/stack/ (fora do git); banco em backend/data/stack/stack.db (--fresh apaga).

- A API sobe com `--no-proxy-headers` (o IP real vem de app.core.net + TRUSTED_PROXIES; o Next acrescenta o
  endereço do socket ao X-Forwarded-For).
- Variáveis TRIAL_*, TURNSTILE_*, TRUSTED_*, AI_*, CLIENT_REQUEST_*, SIGNATURE_* e LOG_* do ambiente passam para a API
  (ex.: TRIAL_LIMIT_IP_HOUR=1000 scripts/stack_local.sh restart-api).
- Nunca usa a chave real da OpenRouter: OPENROUTER_KEY_FILE fica vazio e a chave é uma falsa apontando para a IA
  falsa (scripts/fake_openrouter.py).
- Os serviços sobem destacados e sem herdar os handles do terminal: `up` volta assim que tudo responde, mesmo
  quando a saída é um pipe (CI, agentes).
- Windows: o front usa `--webpack` porque o Turbopack recusa `node_modules` por junção.
"""

# ruff: noqa: S110, S603, S607, SIM105, UP031 — ferramenta de teste local (sorteio não criptográfico, subprocessos fixos)
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "backend" / "data" / "stack"
WIN = os.name == "nt"
API_PORT = int(os.environ.get("API_PORT", "8150"))
WEB_PORT = int(os.environ.get("WEB_PORT", "3350"))
AI_PORT = int(os.environ.get("AI_PORT", "8151"))
FAKE_KEY = "sk-or-v1-falsa-000000000000000000000000000000"


def api_env() -> dict[str, str]:
    env = {
        "DATABASE_URL": "sqlite:///./data/stack/stack.db",
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_DIR": "./data/stack/storage",
        "JOB_BACKEND": "thread",
        "PDF_CONVERTER": "none",
        "PDF_IMPORT_ENABLED": "true",
        "APP_ENV": "development",
        "PUBLIC_WEB_URL": f"http://localhost:{WEB_PORT}",
        "ALLOWED_ORIGINS": f"http://localhost:{WEB_PORT},http://127.0.0.1:{WEB_PORT}",
        "SEED_DEMO_PASSWORD": "demo12345",
        "EXTERNAL_AI_ENABLED": "true",
        "AI_PROVIDER": "openrouter",
        "OPENROUTER_API_KEY": FAKE_KEY,
        "OPENROUTER_KEY_FILE": "",
        "OPENROUTER_BASE_URL": f"http://127.0.0.1:{AI_PORT}/api/v1",
        "TRIAL_ENABLED": "true",
        "LOG_JSON": "true",
        "LOG_LEVEL": "INFO",
    }
    env.update({k: v for k, v in os.environ.items() if k.startswith(PASSTHROUGH)})
    return env


PASSTHROUGH = ("TRIAL_", "TURNSTILE_", "TRUSTED_", "AI_", "CLIENT_REQUEST_", "SIGNATURE_", "LOG_", "EXTERNAL_AI_")


def _pidfile(name: str) -> Path:
    return STATE / f"{name}.json"


def _alive(pid: int) -> bool:
    if WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _running(name: str) -> int | None:
    f = _pidfile(name)
    if not f.exists():
        return None
    pid = json.loads(f.read_text())["pid"]
    return pid if _alive(pid) else None


def _spawn(name: str, cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    if pid := _running(name):
        print(f"  {name} já está no ar (pid {pid})")
        return
    log = open(STATE / f"{name}.log", "wb")  # noqa: SIM115 — o filho herda o handle; fechamos aqui depois
    kw: dict = {"cwd": str(cwd), "stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
                "env": {**os.environ, **(env or {})}, "close_fds": True}
    if WIN:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    log.close()
    _pidfile(name).write_text(json.dumps({"pid": proc.pid, "cmd": cmd}))
    print(f"  {name} iniciado (pid {proc.pid}; log backend/data/stack/{name}.log)")


def _listener_pid(port: int) -> int | None:
    """PID que escuta na porta (para derrubar o que sobrou sem pidfile)."""
    if WIN:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
                return int(parts[4])
        return None
    if shutil.which("lsof"):
        out = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        return int(out.split()[0]) if out.split() else None
    return None


def _kill_tree(pid: int) -> None:
    if WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def _wait(url: str, secs: int, name: str) -> bool:
    deadline = time.time() + secs
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 — só localhost
                if r.status < 500:
                    print(f"  {name} pronto ({url})")
                    return True
        except Exception:
            time.sleep(1)
    print(f"  {name} NÃO respondeu em {secs}s — veja backend/data/stack/{name}.log", file=sys.stderr)
    return False


def cmd_seed(_: argparse.Namespace | None = None) -> int:
    with open(STATE / "seed.log", "wb") as log:
        r = subprocess.run([sys.executable, "-m", "app.cli", "seed"], cwd=ROOT / "backend", stdout=log,
                           stderr=subprocess.STDOUT, env={**os.environ, **api_env()})
    print("  seed ok (demo@docfeito.com.br / demo12345)" if r.returncode == 0 else
          "  seed falhou: backend/data/stack/seed.log")
    return r.returncode


def cmd_down(_: argparse.Namespace | None = None) -> int:
    for name, port in (("web", WEB_PORT), ("api", API_PORT), ("ai", AI_PORT)):
        f = _pidfile(name)
        if f.exists():
            _kill_tree(json.loads(f.read_text())["pid"])
            f.unlink()
        for _ in range(10):  # o que ainda escuta na porta (filho órfão, execução antiga)
            pid = _listener_pid(port)
            if pid is None:
                break
            _kill_tree(pid)
            time.sleep(0.5)
        print(f"  {name} parado")
    return 0


def _spawn_api() -> None:
    _spawn(
        "api",
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT),
         "--no-proxy-headers", "--timeout-keep-alive", "30"],
        ROOT / "backend",
        api_env(),
    )


def cmd_restart_api(_: argparse.Namespace) -> int:
    """Reinicia só a API (zera o limitador em memória e relê TRIAL_* etc. do ambiente)."""
    f = _pidfile("api")
    if f.exists():
        _kill_tree(json.loads(f.read_text())["pid"])
        f.unlink()
    while (pid := _listener_pid(API_PORT)) is not None:
        _kill_tree(pid)
        time.sleep(0.5)
    _spawn_api()
    return 0 if _wait(f"http://127.0.0.1:{API_PORT}/health", 60, "api") else 1


def cmd_up(args: argparse.Namespace) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        cmd_down()
        for p in ("stack.db", "stack.db-wal", "stack.db-shm"):
            (STATE / p).unlink(missing_ok=True)
        shutil.rmtree(STATE / "storage", ignore_errors=True)
        print("  banco e arquivos zerados")
    print(f"Subindo: IA falsa :{AI_PORT}, API :{API_PORT}, web :{WEB_PORT} (python {sys.executable})")
    _spawn("ai", [sys.executable, "scripts/fake_openrouter.py", "--port", str(AI_PORT), *shlex.split(args.ai or "")], ROOT)
    _spawn_api()
    ok = _wait(f"http://127.0.0.1:{AI_PORT}/health", 20, "ai") and _wait(f"http://127.0.0.1:{API_PORT}/health", 60, "api")
    if ok and not args.no_seed:
        cmd_seed()
    if ok and not args.no_web:
        npx = ["cmd", "/c", "npx"] if WIN else ["npx"]
        _spawn(
            "web",
            [*npx, "next", "dev", "--webpack", "-p", str(WEB_PORT)],
            ROOT / "frontend",
            {"API_INTERNAL_URL": f"http://127.0.0.1:{API_PORT}", "NEXT_TELEMETRY_DISABLED": "1"},
        )
        ok = _wait(f"http://127.0.0.1:{WEB_PORT}/login", 300, "web")
    cmd_status()
    return 0 if ok else 1


def cmd_status(_: argparse.Namespace | None = None) -> int:
    for name in ("ai", "api", "web"):
        pid = _running(name)
        print(f"  {name}: {'no ar (pid %d)' % pid if pid else 'parado'}")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{AI_PORT}/__stats", timeout=3) as r:
            s = json.load(r)
        print(f"  IA falsa: {s['calls']} chamadas, custo simulado US$ {s['cost_usd']}, status {s['by_status']}")
    except Exception:
        pass
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    f = STATE / f"{args.name}.log"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f.exists() else []
    print("\n".join(lines[-args.n:]))
    return 0


def cmd_env(_: argparse.Namespace) -> int:
    for k, v in api_env().items():
        print(f"{k}={v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stack local de teste (IA falsa + API + front)")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up")
    up.add_argument("--fresh", action="store_true", help="apaga banco e arquivos antes")
    up.add_argument("--no-web", action="store_true")
    up.add_argument("--no-seed", action="store_true")
    up.add_argument("--ai", default="", help='argumentos da IA falsa, ex.: "--latency-ms 2000 --rate-429 0.1"')
    up.set_defaults(fn=cmd_up)
    sub.add_parser("down").set_defaults(fn=cmd_down)
    sub.add_parser("restart-api").set_defaults(fn=cmd_restart_api)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    sub.add_parser("env").set_defaults(fn=cmd_env)
    lg = sub.add_parser("logs")
    lg.add_argument("name", nargs="?", default="api", choices=["ai", "api", "web", "seed"])
    lg.add_argument("-n", type=int, default=60)
    lg.set_defaults(fn=cmd_logs)
    args = p.parse_args(argv)
    STATE.mkdir(parents=True, exist_ok=True)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
