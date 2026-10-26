"""Assinatura eletrônica (D40): cifra das credenciais, adaptadores (ZapSign, Clicksign) com httpx.MockTransport,
webhook verificado e idempotente, anti-SSRF, fluxo gov.br assistido com verificação PAdES.

Sem rede: os provedores são simulados e qualquer HTTP real derruba o teste.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.config import reset_settings_cache

TEST_KEY = Fernet.generate_key().decode()  # chave descartável, gerada a cada execução


@pytest.fixture()
def fernet_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_KEY)
    reset_settings_cache()
    yield TEST_KEY
    reset_settings_cache()


# ---------------------------------------------------------------- credenciais cifradas (OBR-12)


def test_segredo_cifrado_volta_igual_e_nao_aparece_no_texto(fernet_key) -> None:  # type: ignore[no-untyped-def]
    from app.core import crypto

    token = crypto.encrypt_json({"api_token": "tok-secreto-123"})
    assert "tok-secreto-123" not in token
    assert crypto.decrypt_json(token) == {"api_token": "tok-secreto-123"}


def test_sem_chave_nao_guarda_em_texto_puro(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core import crypto

    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(crypto.EncryptionUnavailable) as exc:
        crypto.encrypt_text("x")
    assert exc.value.status_code == 503 and exc.value.code == "ENCRYPTION_KEY_MISSING"
    monkeypatch.setenv("ENCRYPTION_KEY", "nao-e-uma-chave-fernet")
    reset_settings_cache()
    assert not crypto.available()
    reset_settings_cache()


def test_troca_de_chave_mantem_o_que_ja_foi_guardado(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core import crypto

    monkeypatch.setenv("ENCRYPTION_KEY", TEST_KEY)
    reset_settings_cache()
    old = crypto.encrypt_text("segredo")
    new_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", f"{new_key},{TEST_KEY}")  # a nova cifra, a antiga ainda decifra
    reset_settings_cache()
    assert crypto.decrypt_text(old) == "segredo"
    monkeypatch.setenv("ENCRYPTION_KEY", new_key)  # a antiga saiu da lista: erro claro, nunca lixo
    reset_settings_cache()
    with pytest.raises(crypto.EncryptionUnavailable):
        crypto.decrypt_text(old)
    reset_settings_cache()
