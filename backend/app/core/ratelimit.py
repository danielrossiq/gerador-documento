"""Limitador de taxa por chave. Redis quando disponível (multi-instância); memória caso contrário."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.config import get_settings
from app.core.errors import LimitExceeded


class _MemoryLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


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


def check(key: str, limit: int | None = None, window: int = 60) -> None:
    """Levanta LimitExceeded se `key` passou de `limit` requisições na janela (padrão: config de login)."""
    limit = limit or get_settings().login_rate_limit_per_minute
    r = _redis()
    if r is not None:
        try:
            k = f"rl:{key}:{int(time.time() // window)}"
            n = r.incr(k)
            if n == 1:
                r.expire(k, window + 1)
            allowed = n <= limit
        except Exception:
            allowed = _memory.hit(key, limit, window)
    else:
        allowed = _memory.hit(key, limit, window)
    if not allowed:
        raise LimitExceeded("Muitas tentativas. Aguarde um minuto e tente novamente.", code="RATE_LIMITED")


def reset_for_tests() -> None:
    _memory.reset()
