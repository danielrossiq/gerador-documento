"""ZapSign (https://docs.zapsign.com.br): API REST com token Bearer.

* Criar: `POST /api/v1/docs/` com o PDF em base64 e os signatários; a resposta traz o `token` do documento e o
  `sign_url` de cada signatário (dá para mandar pelo WhatsApp).
* Situação: `GET /api/v1/docs/{token}/` (`status`: pending, signed, refused; `signed_file` com o link do PDF
  assinado, que já inclui o relatório de assinaturas). Cancelar: `DELETE /api/v1/docs/{token}/`.
* Webhook: a ZapSign NÃO assina o corpo (sem HMAC). Ela deixa configurar cabeçalhos próprios no webhook: o
  segredo do espaço vai no cabeçalho `X-DocFeito-Webhook`, a chave aleatória na URL, e a situação é sempre
  confirmada pela API antes de mudar qualquer coisa (o corpo do webhook só dispara a consulta).

Pontos a conferir no sandbox (a documentação não estava acessível nesta sessão): nomes de `auth_mode`, o
formato do corpo do webhook (`event_type`, `token`/`doc_token`) e os hosts do link `signed_file`.
"""

from __future__ import annotations

import base64
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
)

BASE_URLS = {
    "sandbox": "https://sandbox.api.zapsign.com.br",
    "production": "https://api.zapsign.com.br",
}
# de onde o PDF assinado pode ser baixado (o link vem da API da ZapSign: arquivos ficam no S3)
DOWNLOAD_HOSTS = (".zapsign.com.br", ".amazonaws.com")
WEBHOOK_HEADER = "X-DocFeito-Webhook"
AUTH_MODES = {"email": "tokenEmail", "sms": "tokenSms", "whatsapp": "tokenWhatsapp"}
STATUS = {"pending": "sent", "signed": "signed", "refused": "refused"}


def _cpf(digits: str) -> str:
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


class ZapSign:
    name = "zapsign"

    def __init__(self, api_token: str, environment: str, *, max_download_bytes: int) -> None:
        self._base = BASE_URLS[environment]
        self._token = api_token
        self._max = max_download_bytes

    def _client(self):  # type: ignore[no-untyped-def]
        return http.client(
            self._base, {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        )

    def create_envelope(
        self, pdf: bytes, filename: str, signers: list[Signer], options: EnvelopeOptions
    ) -> Envelope:
        body: dict[str, Any] = {
            "name": filename[:200],
            "base64_pdf": base64.b64encode(pdf).decode(),
            "lang": "pt-br",
            "signature_order_active": options.sequential,
            "signers": [self._signer(s, options) for s in signers],
        }
        if options.reference:
            body["external_id"] = options.reference
        with self._client() as c:
            data = check_response(c.post("/api/v1/docs/", json=body), what="create")
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise ProviderError("SIGNATURE_PROVIDER_BAD_RESPONSE", 200)
        returned = data.get("signers") or []
        by_email = {str(s.get("email", "")).lower(): s.get("sign_url") for s in returned if isinstance(s, dict)}
        links = [by_email.get(s.email.lower()) for s in signers]
        return Envelope(external_id=token, signer_links=links, provider_status=str(data.get("status") or ""))

    @staticmethod
    def _signer(s: Signer, options: EnvelopeOptions) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": s.name,
            "email": s.email,
            "auth_mode": AUTH_MODES[s.auth],
            "send_automatic_email": True,
            "send_automatic_whatsapp": False,
            "order_group": s.order,
            "lock_name": True,
            "lock_email": True,
        }
        if s.phone:
            out.update(phone_country="55", phone_number=s.phone, lock_phone=True)
        if s.cpf:
            out["cpf"] = _cpf(s.cpf)
        if options.message:
            out["custom_message"] = options.message
        return out

    def _detail(self, external_id: str) -> dict[str, Any]:
        with self._client() as c:
            data = check_response(c.get(f"/api/v1/docs/{external_id}/"), what="status")
        if not isinstance(data, dict):
            raise ProviderError("SIGNATURE_PROVIDER_BAD_RESPONSE", 200)
        return data

    def status(self, external_id: str) -> EnvelopeStatus:
        data = self._detail(external_id)
        raw = str(data.get("status") or "")
        signed_by = [
            str(s.get("email", "")).lower()
            for s in data.get("signers") or []
            if isinstance(s, dict) and s.get("status") == "signed"
        ]
        return EnvelopeStatus(status=STATUS.get(raw, "sent"), provider_status=raw[:40], signed_by=signed_by)  # type: ignore[arg-type]

    def download_signed(self, external_id: str) -> SignedDocument:
        data = self._detail(external_id)
        url = data.get("signed_file")
        if data.get("status") != "signed" or not isinstance(url, str):
            raise ProviderError("SIGNATURE_NOT_SIGNED_YET", 200)
        return SignedDocument(pdf=http.fetch(url, DOWNLOAD_HOSTS, self._max))

    def cancel(self, external_id: str) -> None:
        with self._client() as c:
            check_response(c.delete(f"/api/v1/docs/{external_id}/"), what="cancel")

    def test_connection(self) -> None:
        with self._client() as c:
            check_response(c.get("/api/v1/docs/", params={"page": 1}), what="test")

    @staticmethod
    def parse_webhook(headers: dict[str, str], body: bytes, secret: str | None) -> WebhookEvent:
        sent = {k.lower(): v for k, v in headers.items()}.get(WEBHOOK_HEADER.lower(), "")
        if not secret or not sent or not hmac.compare_digest(sent.encode(), secret.encode()):
            raise WebhookRejected("cabeçalho do webhook ausente ou errado")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise WebhookRejected("corpo ilegível") from exc
        if not isinstance(data, dict):
            raise WebhookRejected("corpo ilegível")
        doc = data.get("doc_token") or data.get("token")
        return WebhookEvent(
            event_key=body_key(body),
            event_type=str(data.get("event_type") or "desconhecido")[:60],
            external_id=str(doc)[:120] if doc else None,
        )
