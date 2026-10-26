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


# ---------------------------------------------------------------- fluxo pela API (provedor simulado)


def _pdf_job(api, demo_docx):  # type: ignore[no-untyped-def]
    """Gera um documento em PDF (conversor de teste) e devolve o arquivo PDF da geração."""
    from tests.flows import build_generator
    from tests.test_api_flow import SAMPLE_VALUES

    gid = build_generator(api, demo_docx)["id"]
    job = api.post(f"/generators/{gid}/generate", json={"values": SAMPLE_VALUES, "format": "pdf"}).json()
    assert job["status"] == "succeeded", job
    return job, next(f for f in job["files"] if f["kind"] == "pdf")


ZAP = "sandbox.api.zapsign.com.br"


def _zap_routes(status: str = "pending") -> dict:  # type: ignore[type-arg]
    return {
        ("POST", ZAP + "/api/v1/docs/"): {
            "token": "doc-1",
            "status": "pending",
            "signers": [{"email": "ana@exemplo.test", "sign_url": "https://app.zapsign.com.br/verificar/s1"}],
        },
        ("GET", ZAP + "/api/v1/docs/doc-1/"): lambda req: httpx.Response(
            200,
            json={
                "token": "doc-1",
                "status": status,
                "signed_file": "https://zapsign.s3.amazonaws.com/doc-1/assinado.pdf" if status == "signed" else None,
                "signers": [{"email": "ana@exemplo.test", "status": "signed" if status == "signed" else "new"}],
            },
        ),
        ("GET", "zapsign.s3.amazonaws.com/doc-1/assinado.pdf"): SIGNED,
        ("DELETE", ZAP + "/api/v1/docs/doc-1/"): httpx.Response(200, json={}),
    }


def _setup_zapsign(api) -> dict:  # type: ignore[no-untyped-def]
    r = api.put("/signatures/providers/zapsign", json={"environment": "sandbox", "api_token": "tok-zap-segredo-1"})
    assert r.status_code == 200, r.text
    return r.json()


def _send(api, file_id: str, provider: str = "zapsign", **extra):  # type: ignore[no-untyped-def]
    body = {
        "file_id": file_id,
        "provider": provider,
        "signers": [{"name": "Ana Lima", "email": "ana@exemplo.test", "cpf": "529.982.247-25"}],
        **extra,
    }
    return api.post("/signatures", json=body)


def _webhook(api, provider: str, url: str, body: bytes, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    path = url.split("/api/v1", 1)[1]
    return api.tc.post(f"/api/v1{path}", content=body, headers={"Content-Type": "application/json", **headers})


def test_configurar_provedor_cifra_o_token_e_mostra_o_webhook_uma_vez(api, fernet_key) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.db.models import AuditEvent, SignatureProviderConfig
    from app.db.session import get_factory

    api.register()
    out = _setup_zapsign(api)
    assert out["credential_hint"] == "…do-1" and out["webhook_url"].startswith("http")
    assert out["webhook_header"]["name"] == "X-DocFeito-Webhook" and len(out["webhook_header"]["value"]) >= 30
    key = out["webhook_url"].rsplit("/", 1)[1]
    listed = api.get("/signatures/providers").text
    assert "tok-zap-segredo-1" not in listed and key not in listed and out["webhook_header"]["value"] not in listed
    with get_factory()() as db:
        row = db.scalar(select(SignatureProviderConfig))
        stored = str({c.name: getattr(row, c.name) for c in row.__table__.columns})
        audits = str([e.meta for e in db.scalars(select(AuditEvent)).all()])
    for secret in ("tok-zap-segredo-1", key, out["webhook_header"]["value"]):
        assert secret not in stored and secret not in audits
    # atualizar o token não troca a URL do webhook (o provedor já está configurado com ela)
    again = api.put("/signatures/providers/zapsign", json={"environment": "production", "api_token": "tok-novo-2222"})
    assert "webhook_url" not in again.json() and again.json()["environment"] == "production"


def test_so_o_proprietario_configura(api, fernet_key) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import update

    from app.db.models import WorkspaceMember
    from app.db.session import get_factory

    api.register()
    with get_factory()() as db:
        db.execute(update(WorkspaceMember).values(role="member"))
        db.commit()
    r = api.put("/signatures/providers/zapsign", json={"api_token": "tok-zap-segredo-1"})
    assert r.status_code == 403


def test_sem_chave_de_criptografia_nao_configura(api, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    reset_settings_cache()
    api.register()
    r = api.put("/signatures/providers/zapsign", json={"api_token": "tok-zap-segredo-1"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ENCRYPTION_KEY_MISSING"
    assert api.get("/signatures/providers").json()["encryption_ready"] is False


def test_testar_conexao_nao_ecoa_a_credencial(api, fernet_key, provider_net) -> None:  # type: ignore[no-untyped-def]
    api.register()
    _setup_zapsign(api)
    provider_net({("GET", ZAP + "/api/v1/docs/"): {"results": []}})
    assert api.post("/signatures/providers/zapsign/test").json() == {
        "ok": True, "code": None, "message": "Conexão funcionando."
    }
    provider_net({("GET", ZAP + "/api/v1/docs/"): httpx.Response(401, json={"detail": "tok-zap-segredo-1"})})
    r = api.post("/signatures/providers/zapsign/test")
    assert r.json()["ok"] is False and r.json()["code"] == "SIGNATURE_PROVIDER_AUTH"
    assert "tok-zap-segredo-1" not in r.text
    assert api.get("/signatures/providers").json()["configured"][0]["last_test_ok"] is False


def test_zapsign_envio_webhook_e_pdf_assinado_no_historico(api, demo_docx, fake_pdf, fernet_key, provider_net) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from app.db.models import SignatureEvent
    from app.db.session import get_factory
    from app.modules.signatures.zapsign import WEBHOOK_HEADER

    api.register()
    job, pdf = _pdf_job(api, demo_docx)
    cfg = _setup_zapsign(api)
    routes = _zap_routes("pending")
    fake = provider_net(routes)
    r = _send(api, pdf["id"], message="Assine, por favor")
    assert r.status_code == 201, r.text
    sig = r.json()
    assert sig["status"] == "sent" and sig["signers"][0]["sign_url"] == "https://app.zapsign.com.br/verificar/s1"
    assert sig["signers"][0]["cpf"] == "***.982.247-**"  # o CPF inteiro só vai ao provedor
    sent = json.loads(fake.calls[0].content)
    assert sent["external_id"] == sig["id"] and sent["signers"][0]["custom_message"] == "Assine, por favor"

    body = json.dumps({"event_type": "doc_signed", "token": "doc-1"}).encode()
    header = {WEBHOOK_HEADER: cfg["webhook_header"]["value"]}
    # sem o cabeçalho secreto: 401 e nada gravado
    assert _webhook(api, "zapsign", cfg["webhook_url"], body, {WEBHOOK_HEADER: "errado"}).status_code == 401
    with get_factory()() as db:
        assert db.scalar(select(func.count(SignatureEvent.id))) == 0
    # chave errada na URL: 404 igual ao de rota inexistente
    wrong = cfg["webhook_url"].rsplit("/", 1)[0] + "/" + "x" * 43
    assert _webhook(api, "zapsign", wrong, body, header).status_code == 404

    # o webhook diz "assinado", mas quem manda é a API do provedor: ainda pendente → nada muda
    assert _webhook(api, "zapsign", cfg["webhook_url"], body, header).json() == {"status": "ok"}
    assert api.get(f"/signatures/{sig['id']}").json()["status"] == "sent"
    # repetido: sem efeito
    assert _webhook(api, "zapsign", cfg["webhook_url"], body, header).json() == {"status": "duplicate"}

    routes.update(_zap_routes("signed"))
    body2 = json.dumps({"event_type": "doc_signed", "token": "doc-1", "n": 2}).encode()
    assert _webhook(api, "zapsign", cfg["webhook_url"], body2, header).json() == {"status": "ok"}
    done = api.get(f"/signatures/{sig['id']}").json()
    assert done["status"] == "signed" and done["signed_file"]["kind"] == "signed"
    assert done["signers"][0]["signed"] is True
    link = api.post(f"/files/{done['signed_file']['id']}/link").json()["url"]
    assert api.tc.get(link).content == SIGNED
    files = api.get(f"/jobs/{job['id']}").json()["files"]
    assert any(f["kind"] == "signed" and f["filename"].endswith("-assinado.pdf") for f in files)

    # evento fora de ordem depois de concluído: não regride nem baixa de novo
    calls = len(fake.calls)
    late = json.dumps({"event_type": "doc_refused", "token": "doc-1"}).encode()
    assert _webhook(api, "zapsign", cfg["webhook_url"], late, header).json() == {"status": "ok"}
    assert api.get(f"/signatures/{sig['id']}").json()["status"] == "signed" and len(fake.calls) == calls


def test_clicksign_webhook_sem_segredo_e_recusado_e_com_hmac_conclui(api, demo_docx, fake_pdf, fernet_key, provider_net) -> None:  # type: ignore[no-untyped-def]
    api.register()
    _, pdf = _pdf_job(api, demo_docx)
    cfg = api.put("/signatures/providers/clicksign", json={"api_token": "tok-click-segredo"}).json()
    assert "webhook_header" not in cfg and cfg["webhook_ready"] is False
    routes = _clicksign_routes("env-7")
    status = {"value": "running"}
    routes[("GET", "sandbox.clicksign.com/api/v3/envelopes/env-7")] = lambda req: httpx.Response(
        200, json={"data": {"id": "env-7", "attributes": {"status": status["value"]}}}
    )
    routes[("GET", "sandbox.clicksign.com/api/v3/envelopes/env-7/documents")] = {
        "data": [{"id": "doc-9", "links": {"files": {"signed": "https://cdn.clicksign.com/env-7.pdf"}}}]
    }
    routes[("GET", "cdn.clicksign.com/env-7.pdf")] = SIGNED
    provider_net(routes)
    sig = _send(api, pdf["id"], provider="clicksign").json()
    assert sig["status"] == "sent"
    body = json.dumps({"event": {"name": "auto_close"}, "envelope": {"id": "env-7"}}).encode()
    good = "sha256=" + hmac.new(b"segredo-da-clicksign", body, hashlib.sha256).hexdigest()
    assert _webhook(api, "clicksign", cfg["webhook_url"], body, {"Content-Hmac": good}).status_code == 401
    api.put("/signatures/providers/clicksign", json={"webhook_secret": "segredo-da-clicksign"})
    status["value"] = "closed"
    assert _webhook(api, "clicksign", cfg["webhook_url"], body, {"Content-Hmac": good}).json() == {"status": "ok"}
    assert api.get(f"/signatures/{sig['id']}").json()["status"] == "signed"


def test_consulta_periodica_cobre_webhook_perdido(api, demo_docx, fake_pdf, fernet_key, provider_net) -> None:  # type: ignore[no-untyped-def]
    from app.modules.signatures.service import poll_signatures

    api.register()
    _, pdf = _pdf_job(api, demo_docx)
    _setup_zapsign(api)
    routes = _zap_routes("pending")
    provider_net(routes)
    sig = _send(api, pdf["id"]).json()
    routes.update(_zap_routes("signed"))
    assert poll_signatures() == 1  # nunca consultado → entra na hora
    assert api.get(f"/signatures/{sig['id']}").json()["status"] == "signed"
    assert poll_signatures() == 0  # concluído sai da consulta


def test_falha_no_provedor_nao_conta_na_cota_e_cota_mensal(api, demo_docx, fake_pdf, fernet_key, provider_net) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from app.db.models import Workspace
    from app.db.session import get_factory

    me = api.register()
    _, pdf = _pdf_job(api, demo_docx)
    _setup_zapsign(api)
    with get_factory()() as db:
        db.get(Workspace, uuid.UUID(me["workspace"]["id"])).limits = {"max_signatures_per_month": 1}
        db.commit()
    routes = _zap_routes()
    routes[("POST", ZAP + "/api/v1/docs/")] = httpx.Response(500, json={"erro": "dados do signatário"})
    provider_net(routes)
    r = _send(api, pdf["id"])
    assert r.status_code == 502 and r.json()["error"]["code"] == "SIGNATURE_PROVIDER_CREATE_FAILED"
    assert "signatário" not in r.text
    provider_net(_zap_routes())
    assert _send(api, pdf["id"]).status_code == 201
    r = _send(api, pdf["id"])
    assert r.status_code == 429 and r.json()["error"]["code"] == "SIGNATURE_LIMIT"


def test_pedido_de_outro_espaco_nao_aparece(api, api2, demo_docx, fake_pdf, fernet_key, provider_net) -> None:  # type: ignore[no-untyped-def]
    api.register()
    _, pdf = _pdf_job(api, demo_docx)
    _setup_zapsign(api)
    provider_net(_zap_routes())
    sig = _send(api, pdf["id"]).json()
    api2.register()
    assert api2.get(f"/signatures/{sig['id']}").status_code == 404
    assert api2.post(f"/signatures/{sig['id']}/cancel").status_code == 404
    assert api2.get("/signatures").json()["total"] == 0
    assert _send(api2, pdf["id"], provider="govbr").status_code == 404  # arquivo de outro espaço


def test_cancelar_avisa_o_provedor(api, demo_docx, fake_pdf, fernet_key, provider_net) -> None:  # type: ignore[no-untyped-def]
    api.register()
    _, pdf = _pdf_job(api, demo_docx)
    _setup_zapsign(api)
    fake = provider_net(_zap_routes())
    sig = _send(api, pdf["id"]).json()
    assert api.post(f"/signatures/{sig['id']}/cancel").json()["status"] == "cancelled"
    assert fake.calls[-1].method == "DELETE"
    assert api.post(f"/signatures/{sig['id']}/cancel").status_code == 409
