"""Cifra dos segredos de terceiros guardados no banco (D40: tokens dos provedores de assinatura, segredos de webhook).

Fernet (AES-128-CBC + HMAC-SHA256, do pacote `cryptography`). A chave vem de ENCRYPTION_KEY ou ENCRYPTION_KEY_FILE,
nunca do repositório nem do banco. Sem chave configurada, guardar ou ler um segredo falha com um erro claro (503),
em vez de cair em texto puro. Gerar uma chave:
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.core.errors import ServiceUnavailable


class EncryptionUnavailable(ServiceUnavailable):
    code = "ENCRYPTION_KEY_MISSING"

    def __init__(self) -> None:
        super().__init__(
            "A chave de criptografia do servidor não está configurada. Fale com o suporte.",
            code=self.code,
        )


def _fernet():  # type: ignore[no-untyped-def]
    from cryptography.fernet import Fernet, MultiFernet

    keys = get_settings().encryption_keys
    if not keys:
        raise EncryptionUnavailable()
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except ValueError as exc:  # chave com formato errado: mesmo erro, sem citar a chave
        raise EncryptionUnavailable() from exc


def available() -> bool:
    try:
        _fernet()
    except EncryptionUnavailable:
        return False
    return True


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_text(token: str) -> str:
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # chave trocada sem manter a antiga na lista
        raise EncryptionUnavailable() from exc


def encrypt_json(data: dict[str, Any]) -> str:
    return encrypt_text(json.dumps(data, separators=(",", ":")))


def decrypt_json(token: str) -> dict[str, Any]:
    out = json.loads(decrypt_text(token))
    return out if isinstance(out, dict) else {}
