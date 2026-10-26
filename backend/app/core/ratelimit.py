"""Limitador de taxa por chave. Redis quando disponível (multi-instância); memória caso contrário."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.config import get_settings
from app.core.errors import LimitExceeded

MAX_MEMORY_KEYS = 50_000  # rota pública com muitos IPs: a memória não cresce para sempre


class _MemoryLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._windows: dict[str, int] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > MAX_MEMORY_KEYS:
                self._prune(now)
            q = self._hits[key]
            self._windows[key] = window
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def _prune(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self._windows.get(k, 86400)]:
            self._hits.pop(k, None)
            self._windows.pop(k, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._windows.clear()


_memory = _MemoryLimiter()
_redis_client = None


def _redis():  # type: ignore[no-untyped-def]
    global _redis_client
    url = get_settings().redis_url
    if not url:
        return None
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
    return _redis_client


def hit(key: str, limit: int, window: int) -> bool:
    """Conta uma tentativa em `key`; False se já passou de `limit` na janela (fixa no Redis, deslizante em memória)."""
    r = _redis()
    if r is not None:
        try:
            k = f"rl:{key}:{int(time.time() // window)}"
            n = r.incr(k)
            if n == 1:
                r.expire(k, window + 1)
            return n <= limit
        except Exception:
            return _memory.hit(key, limit, window)
    return _memory.hit(key, limit, window)


def check(
    key: str,
    limit: int | None = None,
    window: int = 60,
    *,
    message: str = "Muitas tentativas. Aguarde um minuto e tente novamente.",
    code: str = "RATE_LIMITED",
) -> None:
    """Levanta LimitExceeded se `key` passou de `limit` requisições na janela (padrão: config de login)."""
    if not hit(key, limit or get_settings().login_rate_limit_per_minute, window):
        raise LimitExceeded(message, code=code)


def reset_for_tests() -> None:
    _memory.reset()
