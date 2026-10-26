"""IA FALSA no formato da OpenRouter, para testes de segurança/custo sem gastar nada.

Só escuta em 127.0.0.1. Responde:
  GET  /api/v1/models            → tabela de preços (os mesmos preços de lista dos modelos usados no app)
  POST /api/v1/chat/completions  → JSON vazio válido para o schema pedido + `usage` com custo calculado
  GET  /stats                    → {"calls": n, "cost_usd": soma, "truncated": n}
  POST /reset                    → zera os contadores
  POST /mode {"mode": "truncate"} → liga/desliga o modo de falha sem reiniciar

Modo de falha (para medir "falhas não contam na cota"): FAKE_AI_MODE=truncate devolve finish_reason="length"
com o teto de saída inteiro como tokens gerados (é o que um provedor real cobraria).

Uso: python scripts/fake_openrouter.py 8169
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# US$/token, preços de lista públicos (podem mudar; servem para estimar ordem de grandeza)
PRICES = {
    "google/gemini-2.5-flash": (0.30e-6, 2.50e-6),
    "anthropic/claude-haiku-5.5": (1.00e-6, 5.00e-6),
}
_lock = threading.Lock()
STATS = {"calls": 0, "cost_usd": 0.0, "truncated": 0, "input_tokens": 0}


def _empty_for(schema: dict) -> dict:
    out: dict = {}
    for key in schema.get("required", []):
        prop = (schema.get("properties") or {}).get(key, {})
        out[key] = [] if prop.get("type") == "array" else ""
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.endswith("/models"):
            data = [{"id": m, "pricing": {"prompt": str(p), "completion": str(c)}} for m, (p, c) in PRICES.items()]
            self._send(200, {"data": data})
        elif self.path == "/stats":
            with _lock:
                self._send(200, dict(STATS))
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/reset":
            with _lock:
                STATS.update(calls=0, cost_usd=0.0, truncated=0, input_tokens=0)
            self._send(200, {"ok": True})
            return
        if self.path == "/mode":  # {"mode": "truncate"} ou {"mode": ""}: troca o modo sem reiniciar
            os.environ["FAKE_AI_MODE"] = str(json.loads(raw or b"{}").get("mode") or "")
            self._send(200, {"mode": os.environ["FAKE_AI_MODE"]})
            return
        if not self.path.endswith("/chat/completions"):
            self._send(404, {"error": {"message": "not found"}})
            return
        req = json.loads(raw or b"{}")
        model = req.get("model", "")
        pin, pout = PRICES.get(model, (1e-6, 5e-6))
        tokens_in = max(1, len(raw) // 4)  # aproximação: o corpo inteiro (texto + base64 dos anexos)
        truncate = os.environ.get("FAKE_AI_MODE") == "truncate"
        tokens_out = int(req.get("max_tokens") or 0) if truncate else 50
        cost = tokens_in * pin + tokens_out * pout
        schema = ((req.get("response_format") or {}).get("json_schema") or {}).get("schema") or {}
        with _lock:
            STATS["calls"] += 1
            STATS["cost_usd"] += cost
            STATS["input_tokens"] += tokens_in
            STATS["truncated"] += int(truncate)
        self._send(
            200,
            {
                "model": model,
                "choices": [
                    {
                        "finish_reason": "length" if truncate else "stop",
                        "message": {"content": "{" if truncate else json.dumps(_empty_for(schema))},
                    }
                ],
                "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out, "cost": round(cost, 8)},
            },
        )


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8169
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    print(f"IA falsa em http://127.0.0.1:{port}/api/v1", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
