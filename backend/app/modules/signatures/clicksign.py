"""Clicksign, API v3 (formato JSON:API; https://developers.clicksign.com).

Envio em passos: cria o envelope → anexa o documento (base64) → cria cada signatário → cria os requisitos
(qualificação "assinar" e autenticação por e-mail/SMS/WhatsApp) → ativa o envelope (`status: running`); a Clicksign
avisa os signatários. Situação pelo envelope (`running`, `closed` = todos assinaram, `canceled`); o PDF assinado vem
do link `files.signed` do documento. Cancelar: envelope com `status: canceled`.

Webhook: cabeçalho `Content-Hmac: sha256=<hex>` = HMAC-SHA256 do corpo com o segredo que a Clicksign mostra ao criar
o webhook. Sem segredo configurado, o webhook é recusado (fica a consulta periódica).

Pontos a conferir no sandbox (a documentação não estava acessível nesta sessão): o cabeçalho de autenticação
(token puro em `Authorization`), os nomes dos requisitos, onde o id do envelope vem no corpo do webhook e o host do
link `files.signed`.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
from typing import Any

from app.modules.signatures import http
from app.modules.signatures.base import (
    Envelope,
    EnvelopeOptions,
    EnvelopeStatus,
    ProviderError,
    SignedDocument,
    Signer,
    WebhookEvent,
    WebhookRejected,
    body_key,
    check_response,
    parse_dt,
)

BASE_URLS = {
    "sandbox": "https://sandbox.clicksign.com/api/v3",
    "production": "https://app.clicksign.com/api/v3",
}
DOWNLOAD_HOSTS = (".clicksign.com", ".amazonaws.com")
JSONAPI = "application/vnd.api+json"
STATUS = {"running": "sent", "draft": "sent", "closed": "signed", "canceled": "cancelled"}


def _data(payload: Any) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise ProviderError("SIGNATURE_PROVIDER_BAD_RESPONSE", 200)
    return data


def _rel(kind: str, id_: str) -> dict[str, Any]:
    return {"data": {"type": kind, "id": id_}}


class Clicksign:
    name = "clicksign"

    def __init__(self, api_token: str, environment: str, *, max_download_bytes: int) -> None:
        self._base = BASE_URLS[environment]
        self._token = api_token
        self._max = max_download_bytes

    def _client(self):  # type: ignore[no-untyped-def]
        return http.client(
            self._base, {"Authorization": self._token, "Content-Type": JSONAPI, "Accept": JSONAPI}
        )

    def create_envelope(
        self, pdf: bytes, filename: str, signers: list[Signer], options: EnvelopeOptions
    ) -> Envelope:
        with self._client() as c:
            env = _data(
                check_response(
                    c.post(
                        "/envelopes",
                        json={
                            "data": {
                                "type": "envelopes",
                                "attributes": {
                                    "name": filename[:200],
                                    "locale": "pt-BR",
                                    "auto_close": True,
                                    "remind_interval": 3,
                                    "block_after_refusal": True,
                                },
                            }
                        },
                    ),
                    what="create",
                )
            )
            env_id = str(env["id"])
            try:
                self._fill(c, env_id, pdf, filename, signers, options)
            except ProviderError:
                # envelope pela metade não fica no provedor: cancela (e se nem isso der, o rascunho não é enviado)
                with contextlib.suppress(ProviderError):
                    self._set_status(c, env_id, "canceled")
                raise
        # a Clicksign avisa cada signatário por e-mail/SMS/WhatsApp; a API v3 não devolve um link por signatário
        return Envelope(external_id=env_id, signer_links=[None] * len(signers), provider_status="running")

    def _fill(
        self, c, env_id: str, pdf: bytes, filename: str, signers: list[Signer], options: EnvelopeOptions
    ) -> None:  # type: ignore[no-untyped-def]
        doc = _data(
            check_response(
                c.post(
                    f"/envelopes/{env_id}/documents",
                    json={
                        "data": {
                            "type": "documents",
                            "attributes": {
                                "filename": filename[:200],
                                "content_base64": "data:application/pdf;base64,"
                                + base64.b64encode(pdf).decode(),
                            },
                        }
                    },
                ),
                what="create",
            )
        )
        for s in signers:
            attrs: dict[str, Any] = {
                "name": s.name,
                "email": s.email,
                "refusable": True,
                "group": s.order if options.sequential else 1,
                "communicate_events": {
                    "signature_request": s.auth,
                    "signature_reminder": "email",
                    "document_signed": "email",
                },
            }
            if s.phone:
                attrs["phone_number"] = s.phone
            if s.cpf:
                attrs.update(has_documentation=True, documentation=f"{s.cpf[:3]}.{s.cpf[3:6]}.{s.cpf[6:9]}-{s.cpf[9:]}")
            signer = _data(
                check_response(
                    c.post(f"/envelopes/{env_id}/signers", json={"data": {"type": "signers", "attributes": attrs}}),
                    what="create",
                )
            )
            rels = {"document": _rel("documents", str(doc["id"])), "signer": _rel("signers", str(signer["id"]))}
            for req_attrs in ({"action": "agree", "role": "sign"}, {"action": "provide_evidence", "auth": s.auth}):
                check_response(
                    c.post(
                        f"/envelopes/{env_id}/requirements",
                        json={"data": {"type": "requirements", "attributes": req_attrs, "relationships": rels}},
                    ),
                    what="create",
                )
        self._set_status(c, env_id, "running")

    @staticmethod
    def _set_status(c, env_id: str, status: str) -> None:  # type: ignore[no-untyped-def]
        check_response(
            c.patch(
                f"/envelopes/{env_id}",
                json={"data": {"id": env_id, "type": "envelopes", "attributes": {"status": status}}},
            ),
            what="update",
        )

    def status(self, external_id: str) -> EnvelopeStatus:
        with self._client() as c:
            env = _data(check_response(c.get(f"/envelopes/{external_id}"), what="status"))
        raw = str((env.get("attributes") or {}).get("status") or "")
        return EnvelopeStatus(status=STATUS.get(raw, "sent"), provider_status=raw[:40])  # type: ignore[arg-type]

    def download_signed(self, external_id: str) -> SignedDocument:
        with self._client() as c:
            payload = check_response(c.get(f"/envelopes/{external_id}/documents"), what="status")
        docs = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(docs, list) or not docs or not isinstance(docs[0], dict):
            raise ProviderError("SIGNATURE_PROVIDER_BAD_RESPONSE", 200)
        files = ((docs[0].get("links") or {}).get("files") or {}) if isinstance(docs[0].get("links"), dict) else {}
        url = files.get("signed") if isinstance(files, dict) else None
        if not isinstance(url, str):
            raise ProviderError("SIGNATURE_NOT_SIGNED_YET", 200)
        return SignedDocument(pdf=http.fetch(url, DOWNLOAD_HOSTS, self._max))

    def cancel(self, external_id: str) -> None:
        with self._client() as c:
            self._set_status(c, external_id, "canceled")

    def test_connection(self) -> None:
        with self._client() as c:
            check_response(c.get("/envelopes", params={"page[size]": 1}), what="test")

    @staticmethod
    def parse_webhook(headers: dict[str, str], body: bytes, secret: str | None) -> WebhookEvent:
        sent = {k.lower(): v for k, v in headers.items()}.get("content-hmac", "")
        if not secret or not sent.startswith("sha256="):
            raise WebhookRejected("assinatura do webhook ausente")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sent.removeprefix("sha256=").strip().lower()):
            raise WebhookRejected("assinatura do webhook inválida")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise WebhookRejected("corpo ilegível") from exc
        if not isinstance(data, dict):
            raise WebhookRejected("corpo ilegível")
        event = data.get("event") if isinstance(data.get("event"), dict) else {}
        return WebhookEvent(
            event_key=str(event.get("id") or body_key(body))[:100],
            event_type=str(event.get("name") or "desconhecido")[:60],
            external_id=_envelope_id(data, event),
            occurred_at=parse_dt(event.get("occurred_at")),
        )


def _envelope_id(data: dict[str, Any], event: dict[str, Any]) -> str | None:
    """O id do envelope pode vir em lugares diferentes conforme o evento; tenta os conhecidos."""
    candidates = [
        (data.get("envelope") or {}).get("id") if isinstance(data.get("envelope"), dict) else None,
        ((event.get("data") or {}).get("envelope") or {}).get("id")
        if isinstance(event.get("data"), dict) and isinstance(event["data"].get("envelope"), dict)
        else None,
        (data.get("document") or {}).get("envelope_id") if isinstance(data.get("document"), dict) else None,
    ]
    found = next((c for c in candidates if isinstance(c, str) and c), None)
    return found[:120] if found else None
