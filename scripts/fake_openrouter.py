"""IA FALSA para testes e estresse: imita a OpenRouter (`/api/v1/chat/completions` e `/api/v1/models`).

Nunca fala com a rede e não custa nada. Responde JSON no schema pedido (`response_format.json_schema`), com
respostas "plausíveis" para os schemas do DocFeito (campos do modelo, preencher por texto/foto, revisar) e uma
instância mínima válida para qualquer outro schema. Conta as chamadas e o custo SIMULADO (preços reais da
OpenRouter em out/2026), para medir quanto um ataque gastaria de verdade.

Uso (Python 3.12+, só biblioteca padrão):

    python scripts/fake_openrouter.py --port 8151
    python scripts/fake_openrouter.py --port 8151 --latency-ms 2500 --jitter-ms 500 --rate-429 0.1 --rate-500 0.05

Backend apontando para ela:

    EXTERNAL_AI_ENABLED=true OPENROUTER_API_KEY=sk-or-v1-falsa-0000000000000000000000 \
    OPENROUTER_BASE_URL=http://127.0.0.1:8151/api/v1

Controle em tempo de execução (o estresse usa isso entre cenários):

    GET  /__stats      contadores (chamadas, status, custo simulado, tokens, concorrência máxima, bytes)
    GET  /__config     configuração atual
    POST /__control    {"latency_ms": 0, "rate_429": 0.5, ...}  muda a configuração (campos de Config)
    POST /__reset      zera os contadores

Modos de falha (probabilidades de 0 a 1, sorteadas por chamada, nesta ordem):
    rate_401 / rate_402   credencial inválida / sem crédito (o backend não repete)
    rate_429 / rate_500   limite de taxa / erro do provedor (o backend repete com espera)
    rate_hang             segura a conexão por `hang_seconds` (testa o timeout do cliente)
    rate_truncate         responde 200 com finish_reason "length" e JSON cortado (custa como se tivesse saído)
    rate_invalid_json     responde 200 com conteúdo que não é JSON
    rate_no_cost          omite usage.cost (o backend fica só com a reserva)
Custo informado: `cost_usd` fixo por chamada (se dado) ou tokens × preço do modelo × `cost_multiplier`
(> 1 simula provedor cobrando acima da reserva).
"""

# ruff: noqa: S311 — ferramenta de teste local (sorteio não criptográfico, subprocessos fixos)
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Preços públicos da OpenRouter (US$/token) consultados em /api/v1/models em out/2026.
PRICES: dict[str, tuple[float, float]] = {
    "anthropic/claude-haiku-5.5": (0.10e-6, 0.50e-6),
    "anthropic/claude-haiku-4.5": (1.0e-6, 5.0e-6),
    "google/gemini-2.5-flash": (0.30e-6, 2.50e-6),
    "google/gemini-2.5-flash-lite": (0.10e-6, 0.40e-6),
}
DEFAULT_PRICE = (1.0e-6, 5.0e-6)
IMAGE_TOKENS = 1300  # ~ foto de documento reduzida a 2000 px (Gemini cobra por blocos de 768 px)
PDF_TOKENS_PER_30KB = 800


@dataclass
class Config:
    latency_ms: int = 300
    jitter_ms: int = 100
    rate_401: float = 0.0
    rate_402: float = 0.0
    rate_429: float = 0.0
    rate_500: float = 0.0
    rate_hang: float = 0.0
    hang_seconds: float = 120.0
    rate_truncate: float = 0.0
    rate_invalid_json: float = 0.0
    rate_no_cost: float = 0.0
    cost_usd: float | None = None
    cost_multiplier: float = 1.0
    output_tokens: int | None = None  # None = estimado pelo tamanho do JSON devolvido
    require_key: bool = True  # exige "Authorization: Bearer sk-or-..." (como a real; sem ela → 401)
    models_status: int = 200  # /models com erro testa o preço reserva (FALLBACK_PRICE) do backend


@dataclass
class Stats:
    started_at: float = field(default_factory=time.time)
    calls: int = 0
    models_calls: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_outcome: dict[str, int] = field(default_factory=dict)
    by_schema: dict[str, int] = field(default_factory=dict)
    by_model: dict[str, int] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0  # custo que a OpenRouter real teria cobrado (só respostas 200, inclusive cortadas)
    images: int = 0
    pdfs: int = 0
    request_bytes: int = 0
    max_request_bytes: int = 0
    in_flight: int = 0
    max_in_flight: int = 0
    latency_ms_total: float = 0.0


CONFIG = Config()
STATS = Stats()
LOCK = threading.Lock()
RNG = random.Random()


def _bump(d: dict[str, int], key: str) -> None:
    d[key] = d.get(key, 0) + 1


# ------------------------------------------------------------------ respostas plausíveis por schema

CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2} de [a-zç]+ de \d{4}\b", re.I)
MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?")
CEP_RE = re.compile(r"\b\d{5}-\d{3}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
PHONE_RE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b")
NAME_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+(?:da|de|do|dos|das|e)\s+|\s+)[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+"
    r"(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){0,3}"
)
BLOCK_LINE_RE = re.compile(r"^\[(?P<key>[^\]]+)\]\s+\((?P<loc>[^)]*)\)\s+(?P<text>.*)$", re.M)

# (palavra no nome do campo, regex, tipo) — a ordem importa (cnpj antes de cpf etc.)
FIELD_HINTS: list[tuple[tuple[str, ...], re.Pattern[str], str]] = [
    (("cnpj",), CNPJ_RE, "cnpj"),
    (("cpf",), CPF_RE, "cpf"),
    (("cep",), CEP_RE, "cep"),
    (("email", "e_mail"), EMAIL_RE, "email"),
    (("telefone", "fone", "celular", "whatsapp"), PHONE_RE, "phone"),
    (("data", "nascimento", "inicio", "termino", "vencimento"), DATE_RE, "date"),
    (("valor", "preco", "aluguel", "honorario", "salario", "multa"), MONEY_RE, "currency"),
    (("nome", "contratante", "contratado", "locador", "locatario", "outorgante", "cliente"), NAME_RE, "text_short"),
]

FAKE_DOC_VALUES = {
    "cnpj": "11.222.333/0001-81",
    "cpf": "529.982.247-25",  # CPF de teste com dígitos válidos (fictício)
    "cep": "01310-100",
    "email": "pessoa.ficticia@exemplo.test",
    "phone": "(11) 98765-4321",
    "date": "15/03/1988",
    "currency": "",  # documento pessoal não tem valor de contrato
    "text_short": "Renata Ficticia Duarte",
}


def _hint_for(name: str) -> tuple[re.Pattern[str], str] | None:
    low = name.lower()
    for words, rx, kind in FIELD_HINTS:
        if any(w in low for w in words):
            return rx, kind
    return None


def _enum_names(schema: dict[str, Any]) -> list[str]:
    try:
        return list(schema["properties"]["values"]["items"]["properties"]["name"]["enum"])
    except (KeyError, TypeError):
        return []


def _user_text(messages: list[dict[str, Any]]) -> tuple[str, int, int, int]:
    """Texto de todas as mensagens + (imagens, pdfs, tokens estimados dos anexos)."""
    texts: list[str] = []
    images = pdfs = extra = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                kind = part.get("type")
                if kind == "text":
                    texts.append(str(part.get("text") or ""))
                elif kind == "image_url":
                    images += 1
                    extra += IMAGE_TOKENS
                elif kind == "file":
                    pdfs += 1
                    data = str((part.get("file") or {}).get("file_data") or "")
                    extra += max(1, (len(data) * 3 // 4) // 30_000 + 1) * PDF_TOKENS_PER_30KB
    return "\n".join(texts), images, pdfs, extra


def _fields_answer(user: str) -> dict[str, Any]:
    """Schema "campos": marca CPFs, CNPJs, datas, valores, CEPs, e-mails e nomes encontrados nos parágrafos."""
    out: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    for m in BLOCK_LINE_RE.finditer(user):
        key, text = m.group("key"), m.group("text")
        for rx, kind, base, ftype in (
            (CNPJ_RE, "cnpj", "cnpj", "cnpj"),
            (CPF_RE, "cpf", "cpf", "cpf"),
            (DATE_RE, "date", "data", "date"),
            (MONEY_RE, "currency", "valor", "currency"),
            (CEP_RE, "cep", "cep", "cep"),
            (EMAIL_RE, "email", "email", "email"),
            (NAME_RE, "name", "nome", "text_short"),
        ):
            for hit in rx.finditer(text):
                counters[kind] = counters.get(kind, 0) + 1
                n = counters[kind]
                out.append(
                    {
                        "block": key,
                        "text": hit.group(0),
                        "name": f"{base}_{n}",
                        "label": f"{base.capitalize()} {n}",
                        "type": ftype if ftype != "cep" else "text_short",
                        "confidence": 0.9,
                        "reason": "padrão reconhecido pela IA falsa",
                    }
                )
                if len(out) >= 200:
                    return {"suggestions": out}
    return {"suggestions": out}


def _fill_answer(user: str, names: list[str]) -> dict[str, Any]:
    """Schema "preenchimento": procura no TEXTO COLADO o padrão de cada campo; a evidência é o próprio trecho."""
    text = user.split("TEXTO COLADO:", 1)[-1]
    values = []
    for name in names:
        hint = _hint_for(name)
        hit = hint[0].search(text) if hint else None
        values.append({"name": name, "value": hit.group(0) if hit else "", "evidence": hit.group(0) if hit else ""})
    return {"values": values}


def _files_answer(names: list[str], n_docs: int) -> dict[str, Any]:
    """Schema "preenchimento_documentos": dados FICTÍCIOS (a IA falsa não lê imagem)."""
    values = []
    for name in names:
        hint = _hint_for(name)
        v = FAKE_DOC_VALUES.get(hint[1], "") if hint else ""
        values.append({"name": name, "value": v, "evidence": f"documento 1, campo {name}" if v else ""})
    return {"values": values, "documents": ["RG"] * max(1, n_docs)}


def _minimal(schema: dict[str, Any]) -> Any:
    """Instância mínima válida para um schema JSON qualquer (fallback)."""
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object":
        props = schema.get("properties") or {}
        return {k: _minimal(props.get(k) or {}) for k in schema.get("required") or list(props)}
    if t == "array":
        return []
    if t == "string":
        return ""
    if t in ("number", "integer"):
        return 0
    if t == "boolean":
        return False
    return None


def answer_for(schema_name: str, schema: dict[str, Any], user: str, n_docs: int) -> dict[str, Any]:
    if schema_name == "campos":
        return _fields_answer(user)
    if schema_name == "preenchimento":
        return _fill_answer(user, _enum_names(schema))
    if schema_name == "preenchimento_documentos":
        return _files_answer(_enum_names(schema), n_docs)
    if schema_name == "revisao":
        return {"issues": []}
    return _minimal(schema)


# ------------------------------------------------------------------ servidor


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeOpenRouter/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # silencioso: o estresse faz milhares de chamadas
        return

    # -- utilitários
    def _send(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # o cliente desistiu (timeout): normal no modo "hang"

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # -- rotas
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/__stats":
            with LOCK:
                snap = asdict(STATS)
            snap["uptime_s"] = round(time.time() - snap.pop("started_at"), 1)
            ok = snap["by_status"].get("200", 0)
            snap["avg_latency_ms"] = round(snap.pop("latency_ms_total") / snap["calls"], 1) if snap["calls"] else 0
            snap["cost_usd"] = round(snap["cost_usd"], 6)
            snap["cost_per_ok_call_usd"] = round(snap["cost_usd"] / ok, 6) if ok else 0
            return self._send(200, snap)
        if path == "/__config":
            return self._send(200, asdict(CONFIG))
        if path in ("/api/v1/models", "/v1/models", "/models"):
            with LOCK:
                STATS.models_calls += 1
            if CONFIG.models_status != 200:
                return self._send(CONFIG.models_status, {"error": {"message": "falha simulada"}})
            data = [
                {"id": mid, "name": mid, "pricing": {"prompt": f"{pin:.10f}", "completion": f"{pout:.10f}"}}
                for mid, (pin, pout) in PRICES.items()
            ]
            return self._send(200, {"data": data})
        if path in ("", "/health"):
            return self._send(200, {"status": "ok"})
        return self._send(404, {"error": {"message": "rota desconhecida na IA falsa"}})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/__reset":
            self._body()
            global STATS
            with LOCK:
                STATS = Stats()
            return self._send(200, {"reset": True})
        if path == "/__control":
            try:
                changes = json.loads(self._body() or b"{}")
            except ValueError:
                return self._send(400, {"error": {"message": "JSON inválido"}})
            known = {f.name for f in fields(Config)}
            bad = [k for k in changes if k not in known]
            if bad:
                return self._send(400, {"error": {"message": f"campos desconhecidos: {bad}"}})
            with LOCK:
                for k, v in changes.items():
                    setattr(CONFIG, k, v)
            return self._send(200, asdict(CONFIG))
        if path in ("/api/v1/chat/completions", "/v1/chat/completions", "/chat/completions"):
            return self._chat()
        return self._send(404, {"error": {"message": "rota desconhecida na IA falsa"}})

    def _chat(self) -> None:
        started = time.monotonic()
        raw = self._body()
        cfg = Config(**asdict(CONFIG))  # cópia: mudanças no meio da chamada não a afetam
        with LOCK:
            STATS.calls += 1
            STATS.in_flight += 1
            STATS.max_in_flight = max(STATS.max_in_flight, STATS.in_flight)
            STATS.request_bytes += len(raw)
            STATS.max_request_bytes = max(STATS.max_request_bytes, len(raw))
        status, outcome = 200, "ok"
        try:
            auth = self.headers.get("Authorization") or ""
            if cfg.require_key and not auth.startswith("Bearer sk-or-"):
                status, outcome = 401, "no_key"
                return self._send(401, {"error": {"message": "No auth credentials found", "code": 401}})
            try:
                body = json.loads(raw)
            except ValueError:
                status, outcome = 400, "bad_request"
                return self._send(400, {"error": {"message": "corpo não é JSON", "code": 400}})
            model = str(body.get("model") or "")
            rf = (body.get("response_format") or {}).get("json_schema") or {}
            schema_name, schema = str(rf.get("name") or "-"), rf.get("schema") or {}
            text, images, pdfs, extra_tokens = _user_text(body.get("messages") or [])
            with LOCK:
                _bump(STATS.by_model, model or "-")
                _bump(STATS.by_schema, schema_name)
                STATS.images += images
                STATS.pdfs += pdfs

            delay = max(0.0, (cfg.latency_ms + RNG.uniform(-cfg.jitter_ms, cfg.jitter_ms)) / 1000)
            roll = RNG.random()
            acc = 0.0
            for rate, st, name in (
                (cfg.rate_401, 401, "auth"),
                (cfg.rate_402, 402, "no_credit"),
                (cfg.rate_429, 429, "rate_limited"),
                (cfg.rate_500, 500, "provider_error"),
            ):
                acc += rate
                if roll < acc:
                    time.sleep(min(delay, 0.2))
                    status, outcome = st, name
                    hdr = {"Retry-After": "1"} if st == 429 else None
                    return self._send(st, {"error": {"message": f"falha simulada ({name})", "code": st}}, hdr)
            acc += cfg.rate_hang
            if roll < acc:
                status, outcome = 0, "hang"
                time.sleep(cfg.hang_seconds)
                return self._send(504, {"error": {"message": "timeout simulado", "code": 504}})

            time.sleep(delay)
            data = answer_for(schema_name, schema, text, images + pdfs)
            content = json.dumps(data, ensure_ascii=False)
            finish = "stop"
            acc += cfg.rate_truncate
            if roll < acc:
                content, finish, outcome = content[: max(1, len(content) // 2)], "length", "truncated"
            elif roll < acc + cfg.rate_invalid_json:
                content, outcome = "Desculpe, não consigo responder em JSON agora.", "invalid_json"
            tokens_in = len(text) // 4 + extra_tokens
            max_tokens = int(body.get("max_tokens") or 4000)
            tokens_out = cfg.output_tokens or len(content) // 3 + 50
            if finish == "length":
                tokens_out = max_tokens  # cortou porque bateu no teto: cobra o teto inteiro
            tokens_out = min(tokens_out, max_tokens)
            pin, pout = PRICES.get(model, DEFAULT_PRICE)
            cost = cfg.cost_usd if cfg.cost_usd is not None else (tokens_in * pin + tokens_out * pout)
            cost *= cfg.cost_multiplier
            usage: dict[str, Any] = {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            }
            if RNG.random() >= cfg.rate_no_cost:
                usage["cost"] = round(cost, 8)
            with LOCK:
                STATS.tokens_in += tokens_in
                STATS.tokens_out += tokens_out
                STATS.cost_usd += cost
            payload = {
                "id": f"gen-falsa-{int(time.time() * 1000)}-{RNG.randrange(10**6)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "provider": "IA falsa",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": finish,
                        "native_finish_reason": finish,
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": usage,
            }
            return self._send(200, payload)
        finally:
            with LOCK:
                STATS.in_flight -= 1
                _bump(STATS.by_status, str(status))
                _bump(STATS.by_outcome, outcome)
                STATS.latency_ms_total += (time.monotonic() - started) * 1000


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8151)
    p.add_argument("--seed", type=int, default=None, help="semente do sorteio (reprodutível)")
    for f in fields(Config):
        flag = "--" + f.name.replace("_", "-")
        if f.type in ("bool", bool):
            p.add_argument(flag, type=lambda s: s.lower() in ("1", "true", "sim", "yes"), default=None)
        elif f.name in ("cost_usd",):
            p.add_argument(flag, type=float, default=None)
        elif f.name in ("output_tokens",):
            p.add_argument(flag, type=int, default=None)
        else:
            p.add_argument(flag, type=type(getattr(CONFIG, f.name)), default=None)
    args = p.parse_args(argv)
    for f in fields(Config):
        v = getattr(args, f.name)
        if v is not None:
            setattr(CONFIG, f.name, v)
    if args.seed is not None:
        RNG.seed(args.seed)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.request_queue_size = 256
    print(f"IA falsa (OpenRouter) em http://{args.host}:{args.port}/api/v1  config={asdict(CONFIG)}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
