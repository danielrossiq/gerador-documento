"""Cloudflare Turnstile: validação no servidor do desafio "não sou um robô" do teste grátis (D38).

POST https://challenges.cloudflare.com/turnstile/v0/siteverify com `secret`, `response` (o token do widget, até 2.048
caracteres, válido por 5 minutos e de uso único) e `remoteip`. Resposta JSON com `success`, `error-codes`, `action`
e `hostname`. Se a Cloudflare não responder, o teste é recusado (falha fechada): sem o desafio, sobram só os
limites por IP, e o desafio existe justamente para quando eles não bastam.

Chaves de teste da Cloudflare (sem conta): site `1x00000000000000000000AA`, segredo que sempre aprova
`1x0000000000000000000000000000000AA` e segredo que sempre recusa `2x0000000000000000000000000000000AA`.
"""

from __future__ import annotations

import uuid

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
MAX_TOKEN_CHARS = 2048
ACTION = "trial"


def verify(
    token: str | None, remote_ip: str | None, *, secret: str, client: httpx.Client | None = None
) -> bool:
    if not token or len(token) > MAX_TOKEN_CHARS:
        return False
    form = {"secret": secret, "response": token, "idempotency_key": str(uuid.uuid4())}
    if remote_ip:
        form["remoteip"] = remote_ip
    http = client or httpx.Client(timeout=8)
    try:
        resp = http.post(SITEVERIFY_URL, data=form)
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("turnstile_indisponivel", extra={"error_type": type(exc).__name__})
        return False
    finally:
        if client is None:
            http.close()
    if not isinstance(body, dict) or body.get("success") is not True:
        codes = body.get("error-codes") if isinstance(body, dict) else None
        log.info("turnstile_recusado", extra={"codes": [str(c)[:40] for c in (codes or [])][:5]})
        return False
    # o widget da landing declara action="trial": um token emitido para outra página não serve aqui
    action = body.get("action")
    return not action or action == ACTION
