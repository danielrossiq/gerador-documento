"""Cliente mínimo da API REST da Stripe (form-encoded) + verificação de assinatura do webhook.

Sem SDK: são 3 chamadas (Checkout, portal do cliente, assinatura) e a verificação HMAC documentada pela Stripe
(https://docs.stripe.com/webhooks#verify-manually). A chave secreta só vai no cabeçalho Authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

API = "https://api.stripe.com/v1"
TOLERANCE_S = 300


class StripeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """{"a": {"b": 1}, "l": ["x"]} → [("a[b]", "1"), ("l[0]", "x")] (formato da API da Stripe)."""
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if v is None:
            continue
        if isinstance(v, dict):
            out += _flatten(v, key)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    out += _flatten(item, f"{key}[{i}]")
                else:
                    out.append((f"{key}[{i}]", str(item)))
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        else:
            out.append((key, str(v)))
    return out


class StripeClient:
    def __init__(self, secret_key: str, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self.secret_key = secret_key
        self._client = client
        self.timeout = timeout

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(
                f"{API}/{path}",
                data=_flatten(data),
                headers={"Authorization": f"Bearer {self.secret_key}"},  # versão da API = a padrão da conta
                timeout=self.timeout,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise StripeError("BILLING_UNAVAILABLE", "Não foi possível falar com o processador de pagamentos.") from exc
        finally:
            if self._client is None:
                client.close()
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            msg = (body.get("error") or {}).get("message") or f"HTTP {resp.status_code}"
            raise StripeError("BILLING_REJECTED", f"O processador de pagamentos recusou a operação: {msg[:200]}")
        return body

    def checkout_session(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._post("checkout/sessions", data)

    def portal_session(self, customer: str, return_url: str) -> dict[str, Any]:
        return self._post("billing_portal/sessions", {"customer": customer, "return_url": return_url})


def verify_webhook(payload: bytes, header: str | None, secret: str, now: float | None = None) -> dict[str, Any]:
    """Valida o cabeçalho Stripe-Signature (t=..., v1=...) e devolve o evento. Falha → StripeError."""
    if not header or not secret:
        raise StripeError("BILLING_BAD_SIGNATURE", "Assinatura do webhook ausente.")
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        k, _, v = item.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        ts = int(parts.get("t", ["0"])[0])
    except ValueError:
        ts = 0
    if not ts or abs((now or time.time()) - ts) > TOLERANCE_S:
        raise StripeError("BILLING_BAD_SIGNATURE", "Webhook fora da janela de tempo.")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise StripeError("BILLING_BAD_SIGNATURE", "Assinatura do webhook inválida.")
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StripeError("BILLING_BAD_SIGNATURE", "Corpo do webhook inválido.") from exc
    if not isinstance(event, dict) or "type" not in event:
        raise StripeError("BILLING_BAD_SIGNATURE", "Evento sem tipo.")
    return event


def sign_for_tests(payload: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"
