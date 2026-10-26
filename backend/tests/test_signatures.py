"""Assinatura eletrônica (D40): cifra das credenciais, adaptadores (ZapSign, Clicksign) com httpx.MockTransport,
webhook verificado e idempotente, anti-SSRF, fluxo gov.br assistido com verificação PAdES.

Sem rede: os provedores são simulados e qualquer HTTP real derruba o teste.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
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


# ---------------------------------------------------------------- adaptadores com httpx.MockTransport

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"
SIGNED = b"%PDF-1.7\n% assinado\n%%EOF\n"


class Fake:
    """Provedor simulado: guarda as requisições e responde com o roteiro dado (método, caminho) → resposta."""

    def __init__(self, routes: dict[tuple[str, str], object]) -> None:
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, request.url.host + request.url.path)
        answer = self.routes.get(key)
        if answer is None:
            return httpx.Response(404, json={"erro": "rota não simulada", "rota": str(key)})
        if callable(answer):
            return answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, bytes):
            return httpx.Response(200, content=answer, headers={"Content-Type": "application/pdf"})
        return httpx.Response(200, json=answer)

    def json_of(self, i: int) -> dict:
        return json.loads(self.calls[i].content)


@pytest.fixture()
def provider_net(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Rede bloqueada; o transporte dos adaptadores é o MockTransport do teste e o DNS é simulado."""
    from app.modules.signatures import http

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("chamada de rede real durante o teste")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    monkeypatch.setattr(http, "resolve", lambda host: ["52.216.10.20"])

    def use(routes: dict) -> Fake:  # type: ignore[type-arg]
        fake = Fake(routes)
        http.set_transport(httpx.MockTransport(fake))
        return fake

    yield use
    http.set_transport(None)


def _signers():  # type: ignore[no-untyped-def]
    from app.modules.signatures.base import Signer

    return [
        Signer(name="Ana Lima", email="ana@exemplo.test", cpf="52998224725", order=1),
        Signer(name="Bruno Reis", email="bruno@exemplo.test", phone="11987654321", order=2, auth="whatsapp"),
    ]


def test_zapsign_cria_documento_com_bearer_e_devolve_links(provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures.base import EnvelopeOptions
    from app.modules.signatures.zapsign import ZapSign

    host = "sandbox.api.zapsign.com.br"
    fake = provider_net(
        {
            ("POST", host + "/api/v1/docs/"): {
                "token": "doc-123",
                "status": "pending",
                "signers": [
                    {"email": "ana@exemplo.test", "sign_url": "https://app.zapsign.com.br/verificar/s1"},
                    {"email": "BRUNO@exemplo.test", "sign_url": "https://app.zapsign.com.br/verificar/s2"},
                ],
            }
        }
    )
    env = ZapSign("tok-zap", "sandbox", max_download_bytes=1024).create_envelope(
        PDF, "contrato.pdf", _signers(), EnvelopeOptions(message="Oi", sequential=True, reference="ref-1")
    )
    assert env.external_id == "doc-123"
    assert env.signer_links == ["https://app.zapsign.com.br/verificar/s1", "https://app.zapsign.com.br/verificar/s2"]
    req = fake.calls[0]
    assert req.headers["Authorization"] == "Bearer tok-zap"
    body = fake.json_of(0)
    assert base64.b64decode(body["base64_pdf"]) == PDF and body["signature_order_active"] is True
    assert body["external_id"] == "ref-1"
    ana, bruno = body["signers"]
    assert ana["cpf"] == "529.982.247-25" and ana["auth_mode"] == "tokenEmail" and ana["order_group"] == 1
    assert bruno["auth_mode"] == "tokenWhatsapp" and bruno["phone_number"] == "11987654321"


def test_zapsign_situacao_e_pdf_assinado(provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures.zapsign import ZapSign

    host = "api.zapsign.com.br"
    detail = {
        "token": "doc-1",
        "status": "signed",
        "signed_file": "https://zapsign.s3.amazonaws.com/pdf/doc-1/assinado.pdf?X-Amz-Signature=abc",
        "signers": [{"email": "ana@exemplo.test", "status": "signed"}],
    }
    provider_net(
        {
            ("GET", host + "/api/v1/docs/doc-1/"): detail,
            ("GET", "zapsign.s3.amazonaws.com/pdf/doc-1/assinado.pdf"): SIGNED,
        }
    )
    z = ZapSign("tok", "production", max_download_bytes=1024)
    st = z.status("doc-1")
    assert (st.status, st.provider_status, st.signed_by) == ("signed", "signed", ["ana@exemplo.test"])
    assert z.download_signed("doc-1").pdf == SIGNED


def test_zapsign_erro_vira_codigo_sem_o_corpo_do_provedor(provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures.base import ProviderError
    from app.modules.signatures.zapsign import ZapSign

    provider_net(
        {
            ("GET", "api.zapsign.com.br/api/v1/docs/"): httpx.Response(401, json={"detail": "token tok-xyz inválido"}),
        }
    )
    with pytest.raises(ProviderError) as exc:
        ZapSign("tok-xyz", "production", max_download_bytes=1024).test_connection()
    assert exc.value.code == "SIGNATURE_PROVIDER_AUTH" and "tok-xyz" not in str(exc.value)


def test_zapsign_webhook_exige_o_cabecalho_secreto() -> None:
    from app.modules.signatures.base import WebhookRejected
    from app.modules.signatures.zapsign import WEBHOOK_HEADER, ZapSign

    body = json.dumps({"event_type": "doc_signed", "token": "doc-1"}).encode()
    ev = ZapSign.parse_webhook({WEBHOOK_HEADER: "segredo-1"}, body, "segredo-1")
    assert (ev.event_type, ev.external_id) == ("doc_signed", "doc-1") and len(ev.event_key) == 64
    for headers, secret in (({}, "segredo-1"), ({WEBHOOK_HEADER: "outro"}, "segredo-1"), ({WEBHOOK_HEADER: "x"}, None)):
        with pytest.raises(WebhookRejected):
            ZapSign.parse_webhook(headers, body, secret)


def _clicksign_routes(env_id: str = "env-1") -> dict:  # type: ignore[type-arg]
    host = "sandbox.clicksign.com/api/v3"
    counter = {"signer": 0}

    def signer(_req):  # type: ignore[no-untyped-def]
        counter["signer"] += 1
        return httpx.Response(201, json={"data": {"id": f"sig-{counter['signer']}", "type": "signers"}})

    return {
        ("POST", host + "/envelopes"): httpx.Response(201, json={"data": {"id": env_id, "type": "envelopes"}}),
        ("POST", host + f"/envelopes/{env_id}/documents"): httpx.Response(201, json={"data": {"id": "doc-9"}}),
        ("POST", host + f"/envelopes/{env_id}/signers"): signer,
        ("POST", host + f"/envelopes/{env_id}/requirements"): httpx.Response(201, json={"data": {"id": "r"}}),
        ("PATCH", host + f"/envelopes/{env_id}"): {"data": {"id": env_id, "attributes": {"status": "running"}}},
    }


def test_clicksign_monta_o_envelope_em_passos_e_ativa(provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures.base import EnvelopeOptions
    from app.modules.signatures.clicksign import Clicksign

    fake = provider_net(_clicksign_routes())
    env = Clicksign("tok-click", "sandbox", max_download_bytes=1024).create_envelope(
        PDF, "contrato.pdf", _signers(), EnvelopeOptions(sequential=True)
    )
    assert env.external_id == "env-1" and env.signer_links == [None, None]
    steps = [(c.method, c.url.path.removeprefix("/api/v3")) for c in fake.calls]
    assert steps == [
        ("POST", "/envelopes"),
        ("POST", "/envelopes/env-1/documents"),
        ("POST", "/envelopes/env-1/signers"),
        ("POST", "/envelopes/env-1/requirements"),
        ("POST", "/envelopes/env-1/requirements"),
        ("POST", "/envelopes/env-1/signers"),
        ("POST", "/envelopes/env-1/requirements"),
        ("POST", "/envelopes/env-1/requirements"),
        ("PATCH", "/envelopes/env-1"),
    ]
    assert all(c.headers["Authorization"] == "tok-click" for c in fake.calls)
    assert fake.calls[0].headers["Content-Type"] == "application/vnd.api+json"
    doc = fake.json_of(1)["data"]["attributes"]
    assert base64.b64decode(doc["content_base64"].split(",", 1)[1]) == PDF
    bruno = fake.json_of(5)["data"]["attributes"]
    assert bruno["group"] == 2 and bruno["communicate_events"]["signature_request"] == "whatsapp"
    auth = fake.json_of(7)["data"]
    assert auth["attributes"] == {"action": "provide_evidence", "auth": "whatsapp"}
    assert auth["relationships"]["signer"]["data"]["id"] == "sig-2"
    assert fake.json_of(8)["data"]["attributes"] == {"status": "running"}


def test_clicksign_envelope_pela_metade_e_cancelado(provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures.base import EnvelopeOptions, ProviderError
    from app.modules.signatures.clicksign import Clicksign

    routes = _clicksign_routes()
    routes[("POST", "sandbox.clicksign.com/api/v3/envelopes/env-1/signers")] = httpx.Response(422, json={})
    fake = provider_net(routes)
    with pytest.raises(ProviderError) as exc:
        Clicksign("tok", "sandbox", max_download_bytes=1024).create_envelope(PDF, "c.pdf", _signers(), EnvelopeOptions())
    assert exc.value.code == "SIGNATURE_PROVIDER_CREATE_FAILED"
    assert fake.json_of(len(fake.calls) - 1)["data"]["attributes"] == {"status": "canceled"}


def test_clicksign_situacao_e_pdf_assinado(provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures.clicksign import Clicksign

    host = "app.clicksign.com/api/v3"
    provider_net(
        {
            ("GET", host + "/envelopes/env-1"): {"data": {"id": "env-1", "attributes": {"status": "closed"}}},
            ("GET", host + "/envelopes/env-1/documents"): {
                "data": [{"id": "doc-9", "links": {"files": {"signed": "https://cdn.clicksign.com/doc-9/assinado.pdf"}}}]
            },
            ("GET", "cdn.clicksign.com/doc-9/assinado.pdf"): SIGNED,
        }
    )
    c = Clicksign("tok", "production", max_download_bytes=1024)
    assert c.status("env-1").status == "signed"
    assert c.download_signed("env-1").pdf == SIGNED


def test_clicksign_webhook_confere_o_hmac_do_corpo() -> None:
    from app.modules.signatures.base import WebhookRejected
    from app.modules.signatures.clicksign import Clicksign

    body = json.dumps(
        {"event": {"name": "auto_close", "occurred_at": "2026-10-26T12:00:00Z"}, "envelope": {"id": "env-1"}}
    ).encode()
    sig = "sha256=" + hmac.new(b"segredo", body, hashlib.sha256).hexdigest()
    ev = Clicksign.parse_webhook({"Content-Hmac": sig}, body, "segredo")
    assert (ev.event_type, ev.external_id) == ("auto_close", "env-1") and ev.occurred_at is not None
    bad = "sha256=" + hmac.new(b"outro", body, hashlib.sha256).hexdigest()
    for headers, secret in (({"Content-Hmac": bad}, "segredo"), ({}, "segredo"), ({"Content-Hmac": sig}, None)):
        with pytest.raises(WebhookRejected):
            Clicksign.parse_webhook(headers, body, secret)
    with pytest.raises(WebhookRejected):  # corpo alterado depois de assinado
        Clicksign.parse_webhook({"Content-Hmac": sig}, body.replace(b"env-1", b"env-2"), "segredo")


# ---------------------------------------------------------------- anti-SSRF no download (OBR-13)


@pytest.mark.parametrize(
    ("url", "ips"),
    [
        ("http://zapsign.s3.amazonaws.com/a.pdf", ["52.216.10.20"]),  # sem TLS
        ("https://169.254.169.254/latest/meta-data", ["169.254.169.254"]),  # metadados da nuvem
        ("https://evil.example.com/a.pdf", ["52.216.10.20"]),  # host fora da lista do provedor
        ("https://zapsign.s3.amazonaws.com.evil.test/a.pdf", ["52.216.10.20"]),
        ("https://zapsign.s3.amazonaws.com/a.pdf", ["10.0.0.5"]),  # DNS apontando para a rede interna
        ("https://zapsign.s3.amazonaws.com/a.pdf", ["127.0.0.1"]),
        ("https://zapsign.s3.amazonaws.com/a.pdf", ["::ffff:192.168.0.1"]),
        ("https://zapsign.s3.amazonaws.com:8443/a.pdf", ["52.216.10.20"]),  # outra porta
        ("https://user:pw@zapsign.s3.amazonaws.com/a.pdf", ["52.216.10.20"]),
    ],
)
def test_download_recusa_destino_inseguro(provider_net, monkeypatch, url, ips) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures import http
    from app.modules.signatures.base import ProviderError
    from app.modules.signatures.zapsign import DOWNLOAD_HOSTS

    fake = provider_net({})
    monkeypatch.setattr(http, "resolve", lambda host: ips)
    with pytest.raises(ProviderError) as exc:
        http.fetch(url, DOWNLOAD_HOSTS, 1024)
    assert exc.value.code == "SIGNATURE_UNSAFE_URL" and fake.calls == []


def test_download_nao_segue_redirecionamento_e_tem_teto(provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures import http
    from app.modules.signatures.base import ProviderError
    from app.modules.signatures.zapsign import DOWNLOAD_HOSTS

    fake = provider_net(
        {
            ("GET", "zapsign.s3.amazonaws.com/redir.pdf"): httpx.Response(
                302, headers={"Location": "http://169.254.169.254/latest/meta-data"}
            ),
            ("GET", "zapsign.s3.amazonaws.com/grande.pdf"): b"%PDF" + b"0" * 5000,
        }
    )
    with pytest.raises(ProviderError) as exc:
        http.fetch("https://zapsign.s3.amazonaws.com/redir.pdf", DOWNLOAD_HOSTS, 1024)
    assert exc.value.code == "SIGNATURE_DOWNLOAD_FAILED" and len(fake.calls) == 1
    with pytest.raises(ProviderError) as exc:
        http.fetch("https://zapsign.s3.amazonaws.com/grande.pdf", DOWNLOAD_HOSTS, 1024)
    assert exc.value.code == "SIGNATURE_FILE_TOO_LARGE"
