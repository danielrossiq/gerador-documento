"""Base do estresse: sessão autenticada (cookie + CSRF), executor com concorrência, percentis e IA falsa.

Só usa httpx (já é dependência do backend). Nada aqui fala com a IA real: as contagens de chamadas e de custo
vêm do /__stats da IA falsa (scripts/fake_openrouter.py).
"""

# ruff: noqa: S311, S603, S607, SIM105 — ferramenta de teste local (sorteio não criptográfico, subprocessos fixos)
from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import subprocess
import threading
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "backend" / "data" / "stack" / "stress"
API = os.environ.get("STRESS_API", f"http://127.0.0.1:{os.environ.get('API_PORT', '8150')}")
WEB = os.environ.get("STRESS_WEB", f"http://127.0.0.1:{os.environ.get('WEB_PORT', '3350')}")
AI = os.environ.get("STRESS_AI", f"http://127.0.0.1:{os.environ.get('AI_PORT', '8151')}")
DEMO = ("demo@docfeito.com.br", "demo12345")
PASSWORD = "senha-forte-123"


def random_ip() -> str:
    return f"{random.randint(11, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def fake_email(tag: str = "estresse") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@exemplo.test"


# ------------------------------------------------------------------ sessão


class Session:
    """Cliente autenticado como o navegador: cookie de sessão + cabeçalho X-CSRF-Token nas mutações."""

    def __init__(self, base: str = API, *, xff: str | None = None, timeout: float = 120.0) -> None:
        headers = {"X-Forwarded-For": xff} if xff else {}
        limits = httpx.Limits(max_connections=500, max_keepalive_connections=100)
        self.client = httpx.AsyncClient(base_url=base, headers=headers, timeout=timeout, limits=limits)
        self.csrf: str | None = None

    async def __aenter__(self) -> Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.client.aclose()

    def _h(self, headers: dict[str, str] | None) -> dict[str, str]:
        h = dict(headers or {})
        if self.csrf:
            h.setdefault("X-CSRF-Token", self.csrf)
        return h

    async def login(self, email: str = DEMO[0], password: str = DEMO[1]) -> httpx.Response:
        r = await self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        if r.status_code == 200:
            self.csrf = r.json().get("csrf_token")
        return r

    async def register(self, email: str | None = None, name: str = "Pessoa Estresse") -> httpx.Response:
        r = await self.client.post(
            "/api/v1/auth/register", json={"name": name, "email": email or fake_email(), "password": PASSWORD}
        )
        if r.status_code == 201:
            self.csrf = r.json().get("csrf_token")
        return r

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self.client.get(f"/api/v1{path}", **kw)

    async def post(self, path: str, headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        return await self.client.post(f"/api/v1{path}", headers=self._h(headers), **kw)

    async def put(self, path: str, headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        return await self.client.put(f"/api/v1{path}", headers=self._h(headers), **kw)


# ------------------------------------------------------------------ IA falsa


def ai_stats() -> dict[str, Any]:
    try:
        return httpx.get(f"{AI}/__stats", timeout=5).json()
    except httpx.HTTPError:
        return {}


def ai_reset() -> None:
    try:
        httpx.post(f"{AI}/__reset", timeout=5)
    except httpx.HTTPError:
        pass


def ai_control(**cfg: Any) -> dict[str, Any]:
    return httpx.post(f"{AI}/__control", json=cfg, timeout=5).json()


# ------------------------------------------------------------------ memória do processo da API (pico)


def _listener_pid(port: int) -> int | None:
    if os.name != "nt":
        return None
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 5 and p[3] == "LISTENING" and p[1].endswith(f":{port}"):
            return int(p[4])
    return None


def rss_mb(pid: int) -> float | None:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True
        ).stdout
        try:
            kb = out.strip().split('","')[-1].replace('"', "").replace("K", "").replace(".", "").replace(",", "")
            return round(int(kb.strip()) / 1024, 1)
        except (ValueError, IndexError):
            return None
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


class MemoryProbe:
    """Amostra a memória do processo que escuta na porta da API enquanto o cenário roda."""

    def __init__(self, port: int | None = None, every: float = 0.3) -> None:
        port = port or int(API.rsplit(":", 1)[-1].split("/")[0])
        self.pid = _listener_pid(port)
        self.every = every
        self.start_mb = rss_mb(self.pid) if self.pid else None
        self.peak_mb = self.start_mb or 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set() and self.pid:
            v = rss_mb(self.pid)
            if v:
                self.peak_mb = max(self.peak_mb, v)
            self._stop.wait(self.every)

    def __enter__(self) -> MemoryProbe:
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._t.join(timeout=5)
        self.end_mb = rss_mb(self.pid) if self.pid else None


# ------------------------------------------------------------------ execução e métricas


@dataclass
class Result:
    name: str
    requests: int = 0
    concurrency: int = 0
    wall_s: float = 0.0
    rps: float = 0.0
    status: dict[str, int] = field(default_factory=dict)
    codes: dict[str, int] = field(default_factory=dict)
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    ai_calls: int = 0
    ai_cost_usd: float = 0.0
    ai_outcomes: dict[str, int] = field(default_factory=dict)
    mem_start_mb: float | None = None
    mem_peak_mb: float | None = None
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        st = " ".join(f"{k}:{v}" for k, v in sorted(self.status.items()))
        codes = " ".join(f"{k}:{v}" for k, v in sorted(self.codes.items(), key=lambda x: -x[1])[:5])
        mem = f" mem {self.mem_start_mb}->{self.mem_peak_mb}MB" if self.mem_peak_mb else ""
        return (
            f"{self.name:<34} n={self.requests:<5} c={self.concurrency:<3} {self.rps:7.1f} req/s  "
            f"p50={self.p50_ms:7.0f} p95={self.p95_ms:7.0f} p99={self.p99_ms:7.0f} max={self.max_ms:7.0f} ms  "
            f"[{st}] {codes}  IA={self.ai_calls} US${self.ai_cost_usd:.4f}{mem}"
        )


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[min(98, max(0, int(q) - 1))]


def _code(r: httpx.Response) -> str | None:
    try:
        body = r.json()
    except (ValueError, json.JSONDecodeError):
        return None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("code")
    return None


async def run(
    name: str,
    make: Callable[[int], Awaitable[httpx.Response]],
    *,
    requests: int,
    concurrency: int,
    memory: bool = False,
) -> Result:
    """Dispara `requests` chamadas de `make(i)` com no máximo `concurrency` simultâneas."""
    sem = asyncio.Semaphore(concurrency)
    lat: list[float] = []
    status: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    before = ai_stats()

    async def one(i: int) -> None:
        async with sem:
            t = time.perf_counter()
            try:
                r = await make(i)
                status[str(r.status_code)] += 1
                if r.status_code >= 400 and (c := _code(r)):
                    codes[c] += 1
            except httpx.TimeoutException:
                status["timeout"] += 1
            except httpx.HTTPError as exc:
                status[type(exc).__name__] += 1
            lat.append((time.perf_counter() - t) * 1000)

    probe = MemoryProbe() if memory else None
    if probe:
        probe.__enter__()
    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(requests)))
    wall = time.perf_counter() - t0
    if probe:
        probe.__exit__(None, None, None)
    after = ai_stats()
    lat.sort()
    res = Result(
        name=name,
        requests=requests,
        concurrency=concurrency,
        wall_s=round(wall, 2),
        rps=round(requests / wall, 1) if wall else 0,
        status=dict(status),
        codes=dict(codes),
        p50_ms=round(pct(lat, 50), 1),
        p95_ms=round(pct(lat, 95), 1),
        p99_ms=round(pct(lat, 99), 1),
        max_ms=round(lat[-1], 1) if lat else 0,
        ai_calls=after.get("calls", 0) - before.get("calls", 0),
        ai_cost_usd=round(after.get("cost_usd", 0) - before.get("cost_usd", 0), 6),
        ai_outcomes={
            k: v - (before.get("by_outcome") or {}).get(k, 0) for k, v in (after.get("by_outcome") or {}).items()
        },
        mem_start_mb=probe.start_mb if probe else None,
        mem_peak_mb=probe.peak_mb if probe else None,
    )
    res.ai_outcomes = {k: v for k, v in res.ai_outcomes.items() if v}
    return res


def save(results: list[Result], label: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.json"
    path.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    return path
