"""Teste real contra o SANDBOX dos provedores de assinatura (D40). Pulado sem as credenciais.

Para rodar: `ZAPSIGN_SANDBOX_TOKEN=... CLICKSIGN_SANDBOX_TOKEN=... pytest -q tests/test_signatures_sandbox.py`
(tokens das contas sandbox, nunca de produção; nada é commitado). Cria um envelope com um PDF de uma página para
um e-mail de teste, confere a situação e cancela. Serve para validar os pontos marcados "a conferir no sandbox"
nos adaptadores (formato das respostas, autenticação, cancelamento).
"""

from __future__ import annotations

import os

import pytest

from app.modules.signatures.base import EnvelopeOptions, Signer

SIGNER_EMAIL = os.environ.get("SIGNATURE_SANDBOX_EMAIL", "teste.assinatura@exemplo.com")


def _pdf() -> bytes:
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(595, 842)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("provider", "env_var"), [("zapsign", "ZAPSIGN_SANDBOX_TOKEN"), ("clicksign", "CLICKSIGN_SANDBOX_TOKEN")]
)
def test_sandbox_cria_consulta_e_cancela(provider: str, env_var: str) -> None:
    token = os.environ.get(env_var)
    if not token:
        pytest.skip(f"defina {env_var} (token da conta sandbox) para testar contra o provedor de verdade")
    from app.modules.signatures import providers

    adapter = providers.build(provider, token, "sandbox")
    adapter.test_connection()
    env = adapter.create_envelope(
        _pdf(),
        "teste-docfeito.pdf",
        [Signer(name="Teste DocFeito", email=SIGNER_EMAIL)],
        EnvelopeOptions(message="Teste automático do DocFeito (sandbox)", reference="teste-sandbox"),
    )
    assert env.external_id
    try:
        assert adapter.status(env.external_id).status == "sent"
    finally:
        adapter.cancel(env.external_id)
