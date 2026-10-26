"""Interface comum dos provedores de assinatura eletrônica (D40).

Cada adaptador recebe a credencial já decifrada, o ambiente (sandbox/produção) e um `httpx.Client` montado por
`app.modules.signatures.http` (base URL fixa no código, sem redirecionamento). Nos testes o cliente usa
`httpx.MockTransport`. Erros do provedor viram `ProviderError` com um código nosso: a resposta do provedor nunca é
repassada nem registrada em log (pode trazer nome, e-mail ou CPF dos signatários).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

import httpx

Status = Literal["sent", "signed", "refused", "cancelled", "expired"]
Auth = Literal["email", "sms", "whatsapp"]


@dataclass
class Signer:
    name: str
    email: str
    phone: str | None = None  # só dígitos, com DDD (sem o 55)
    cpf: str | None = None  # só dígitos
    order: int = 1
    auth: Auth = "email"


@dataclass
class EnvelopeOptions:
    message: str | None = None
    sequential: bool = False  # assinar na ordem
    reference: str | None = None  # id do pedido no DocFeito, guardado no provedor quando ele aceitar


@dataclass
class Envelope:
    external_id: str
    # link de assinatura de cada signatário, na ordem recebida (None quando o provedor só manda por e-mail)
    signer_links: list[str | None]
    provider_status: str | None = None


@dataclass
class EnvelopeStatus:
    status: Status
    provider_status: str
    signed_by: list[str] = field(default_factory=list)  # e-mails de quem já assinou


@dataclass
class SignedDocument:
    pdf: bytes
    audit_trail: bytes | None = None  # trilha/certificado separado, quando o provedor entrega à parte


@dataclass
class WebhookEvent:
    event_key: str  # id do evento no provedor ou SHA-256 do corpo
    event_type: str
    external_id: str | None
    occurred_at: datetime | None = None


class ProviderError(Exception):
    """Falha ao falar com o provedor. `code` é nosso; `status` é o HTTP do provedor (0 = sem resposta)."""

    def __init__(self, code: str, status: int = 0) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class WebhookRejected(Exception):
    """Webhook sem a assinatura do provedor, com assinatura errada ou corpo ilegível: recusado sem processar."""


class SignatureProvider(Protocol):
    name: str

    def create_envelope(
        self, pdf: bytes, filename: str, signers: list[Signer], options: EnvelopeOptions
    ) -> Envelope: ...

    def status(self, external_id: str) -> EnvelopeStatus: ...

    def download_signed(self, external_id: str) -> SignedDocument: ...

    def cancel(self, external_id: str) -> None: ...

    def test_connection(self) -> None: ...

    @staticmethod
    def parse_webhook(headers: dict[str, str], body: bytes, secret: str | None) -> WebhookEvent: ...


def body_key(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def check_response(resp: httpx.Response, *, what: str) -> Any:
    """JSON da resposta ou ProviderError com um código estável (sem o conteúdo da resposta)."""
    if resp.status_code in (401, 403):
        raise ProviderError("SIGNATURE_PROVIDER_AUTH", resp.status_code)
    if resp.status_code == 404:
        raise ProviderError("SIGNATURE_PROVIDER_NOT_FOUND", 404)
    if resp.status_code == 429:
        raise ProviderError("SIGNATURE_PROVIDER_BUSY", 429)
    if resp.status_code >= 400:
        raise ProviderError(f"SIGNATURE_PROVIDER_{what.upper()}_FAILED", resp.status_code)
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        raise ProviderError("SIGNATURE_PROVIDER_BAD_RESPONSE", resp.status_code) from exc


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
