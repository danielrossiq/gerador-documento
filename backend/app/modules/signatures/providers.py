"""Provedores disponíveis e montagem do adaptador com a credencial já decifrada."""

from __future__ import annotations

from app.core.config import get_settings
from app.modules.signatures.base import SignatureProvider
from app.modules.signatures.clicksign import Clicksign
from app.modules.signatures.zapsign import ZapSign

ADAPTERS: dict[str, type] = {"zapsign": ZapSign, "clicksign": Clicksign}
LABELS = {"zapsign": "ZapSign", "clicksign": "Clicksign", "govbr": "gov.br (Assinador do ITI)"}


def build(provider: str, api_token: str, environment: str) -> SignatureProvider:
    max_bytes = get_settings().signature_max_pdf_mb * 1024 * 1024
    return ADAPTERS[provider](api_token, environment, max_download_bytes=max_bytes)  # type: ignore[no-any-return]
