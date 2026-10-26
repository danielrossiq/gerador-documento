"""Link para o cliente preencher (D39): criação, página pública, envio validado, abertura, uso, cancelamento,
leitura de foto pela IA (simulada), isolamento entre espaços e limpeza.

Sem rede: a IA é simulada e qualquer chamada HTTP real derruba o teste.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest

from app.adapters.ai.openrouter import ChatResult, OpenRouterChat
from app.core.config import reset_settings_cache
from tests.flows import build_generator

FAKE_KEY = "sk-or-v1-" + "c" * 64


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()


def _token(url: str) -> str:
    return url.rsplit("/r/", 1)[1]


def _row(rid: str):  # type: ignore[no-untyped-def]
    from app.db.models import ClientRequest
    from app.db.session import get_factory

    with get_factory()() as db:
        return db.get(ClientRequest, uuid.UUID(rid))


@pytest.fixture()
def gen(api, demo_docx):  # type: ignore[no-untyped-def]
    me = api.register()
    g = build_generator(api, demo_docx)
    return {"id": g["id"], "me": me}


def create(api, gid: str, **body):  # type: ignore[no-untyped-def]
    r = api.post(f"/generators/{gid}/client-requests", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_link_defaults_to_required_fields_and_keeps_only_the_hash(api, gen):
    out = create(api, gen["id"], message="Oi! Preencha, por favor.")
    token = _token(out["url"])
    assert len(token) >= 40 and out["url"].startswith("http")
    # padrão: obrigatórios sem valor padrão, na ordem do formulário
    assert out["fields"] == [
        "nome_do_contratante",
        "cpf_do_contratante",
        "tipo_de_servico",
        "valor_mensal",
        "data_de_inicio",
    ]
    assert out["state"] == "open" and "token" not in out
    assert token in out["share_text"] and "Contrato de prestação de serviços" in out["share_text"]
    row = _row(out["id"])
    assert row.token_hash != token and len(row.token_hash) == 64
    r = api.post(f"/generators/{gen['id']}/client-requests", json={"fields": ["nao_existe"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REQUEST_UNKNOWN_FIELD"
    r = api.post(f"/generators/{gen['id']}/client-requests", json={"expires_days": 31})
    assert r.status_code == 422


def test_public_page_shows_only_what_was_asked(api, api2, gen):
    out = create(
        api,
        gen["id"],
        fields=["nome_do_contratante", "cpf_do_contratante", "tipo_de_servico"],
        message="Mensagem do escritório",
        prefill={"nome_do_contratante": "Maria Souza", "valor_mensal": "9.999,00"},
        prefill_mode="readonly",
    )
    page = api2.get(f"/public/requests/{_token(out['url'])}")  # outro navegador, sem sessão
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["state"] == "open" and body["document"] == "Contrato de prestação de serviços"
    assert body["workspace"] and body["message"] == "Mensagem do escritório"
    assert [f["name"] for f in body["fields"]] == [
        "nome_do_contratante",
        "cpf_do_contratante",
        "tipo_de_servico",
    ]
    assert all(f["example"] is None and f["default_value"] is None for f in body["fields"])  # nada do modelo
    assert body["fields"][2]["options"][0]["label"] == "Consultoria em desenvolvimento de software"
    assert body["prefill"] == {"nome_do_contratante": "Maria Souza"}  # só de campo pedido
    assert body["photos"] == {"allowed": False, "reads_left": 0}
    assert api2.get("/public/requests/" + "x" * 43).status_code == 404


def test_submit_is_validated_like_the_form_and_can_be_corrected_until_opened(api, api2, gen):
    out = create(api, gen["id"], fields=["nome_do_contratante", "cpf_do_contratante", "data_de_inicio"])
    token = _token(out["url"])
    bad = api2.post(
        f"/public/requests/{token}",
        json={"values": {"nome_do_contratante": "Ana", "cpf_do_contratante": "111.111.111-11"}},
    )
    assert bad.status_code == 422
    errors = bad.json()["error"]["details"]["field_errors"]
    assert set(errors) == {"cpf_do_contratante", "data_de_inicio"}  # CPF inválido e obrigatório vazio
    values = {
        "nome_do_contratante": "Ana Lima",
        "cpf_do_contratante": "529.982.247-25",
        "data_de_inicio": "10/11/2026",
        "valor_mensal": "1,00",  # não foi pedido: ignorado
    }
    ok = api2.post(f"/public/requests/{token}", json={"values": values})
    assert ok.status_code == 200 and ok.json() == {"state": "answered", "submissions": 1}
    # o cliente reabre o link e vê o que mandou; corrige e reenvia
    page = api2.get(f"/public/requests/{token}").json()
    assert page["state"] == "answered" and page["values"]["nome_do_contratante"] == "Ana Lima"
    values["nome_do_contratante"] = "Ana Lima Prado"
    assert api2.post(f"/public/requests/{token}", json={"values": values}).json()["submissions"] == 2

    assert api.get("/client-requests/summary").json() == {"new_answers": 1}
    opened = api.get(f"/client-requests/{out['id']}").json()
    assert opened["values"] == {k: v for k, v in values.items() if k != "valor_mensal"}
    assert api.get("/client-requests/summary").json() == {"new_answers": 0}
    # depois que o profissional abriu, o cliente não muda mais
    assert api2.post(f"/public/requests/{token}", json={"values": values}).status_code == 409
    assert api2.get(f"/public/requests/{token}").json() == {"state": "closed"}
    # gerou com a resposta: os dados saem do pedido
    used = api.post(f"/client-requests/{out['id']}/used").json()
    assert used["state"] == "used" and used["has_values"] is False
    assert _row(out["id"]).values is None


def test_readonly_prefill_cannot_be_changed_by_the_client(api, api2, gen):
    out = create(
        api,
        gen["id"],
        fields=["nome_do_contratante", "cpf_do_contratante"],
        prefill={"nome_do_contratante": "Maria Souza"},
        prefill_mode="readonly",
    )
    token = _token(out["url"])
    api2.post(
        f"/public/requests/{token}",
        json={"values": {"nome_do_contratante": "Outro Nome", "cpf_do_contratante": "529.982.247-25"}},
    )
    assert api.get(f"/client-requests/{out['id']}").json()["values"]["nome_do_contratante"] == "Maria Souza"


def test_cancel_expire_and_other_workspace(api, api2, gen):
    out = create(api, gen["id"])
    token = _token(out["url"])
    api2.register()
    assert api2.get(f"/client-requests/{out['id']}").status_code == 404  # outro espaço: 404
    assert api2.post(f"/client-requests/{out['id']}/cancel").status_code == 404
    assert api2.get("/client-requests").json()["total"] == 0
    assert api.post(f"/client-requests/{out['id']}/cancel").json()["state"] == "cancelled"
    assert api.get(f"/public/requests/{token}").status_code == 404

    out2 = create(api, gen["id"], expires_days=1)
    from app.db.base import utcnow
    from app.db.models import ClientRequest
    from app.db.session import get_factory

    with get_factory()() as db:
        db.get(ClientRequest, uuid.UUID(out2["id"])).expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    t2 = _token(out2["url"])
    assert api.get(f"/public/requests/{t2}").json() == {"state": "expired"}
    assert api.post(f"/public/requests/{t2}", json={"values": {}}).status_code == 409
    states = {i["id"]: i["state"] for i in api.get("/client-requests").json()["items"]}
    assert states == {out["id"]: "cancelled", out2["id"]: "expired"}


def test_kit_link_asks_shared_fields(api, demo_docx):
    api.register()
    kit = api.post("/samples/kit").json()
    form = api.get(f"/kits/{kit['id']}/form").json()
    names = [f["name"] for f in form["fields"]]
    assert len(names) >= 2
    r = api.post(f"/kits/{kit['id']}/client-requests", json={"fields": names[:2]})
    assert r.status_code == 201, r.text
    page = api.get(f"/public/requests/{_token(r.json()['url'])}").json()
    assert [f["name"] for f in page["fields"]] == names[:2]
    assert r.json()["target"]["type"] == "kit"


def test_rate_limit_on_the_public_page(app, api, gen):
    from fastapi.testclient import TestClient

    token = _token(create(api, gen["id"])["url"])
    with TestClient(app, client=("198.51.100.30", 4000)) as tc:
        codes = [tc.get(f"/api/v1/public/requests/{token}").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429


def test_audit_never_has_the_values(api, api2, gen):
    from sqlalchemy import select

    from app.db.models import AuditEvent
    from app.db.session import get_factory

    out = create(api, gen["id"], fields=["cpf_do_contratante"])
    token = _token(out["url"])
    api2.get(f"/public/requests/{token}")
    api2.post(f"/public/requests/{token}", json={"values": {"cpf_do_contratante": "529.982.247-25"}})
    api.get(f"/client-requests/{out['id']}")
    with get_factory()() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "client_request")).all()
    actions = [e.action for e in events]
    assert actions == [
        "client_request.create",
        "client_request.viewed",
        "client_request.submitted",
        "client_request.opened",
    ]
    assert all("529" not in str(e.meta) for e in events)
    assert all(
        e.ip is None for e in events if e.action in ("client_request.viewed", "client_request.submitted")
    )


def test_retention_purges_old_answers(api, api2, gen, monkeypatch):
    from app.db.base import utcnow
    from app.db.models import ClientRequest
    from app.db.session import get_factory
    from app.modules.requests.service import purge_requests

    out = create(api, gen["id"], fields=["cpf_do_contratante"])
    api2.post(
        f"/public/requests/{_token(out['url'])}", json={"values": {"cpf_do_contratante": "529.982.247-25"}}
    )
    assert purge_requests() == {"respostas": 0, "pedidos": 0}
    with get_factory()() as db:
        db.get(ClientRequest, uuid.UUID(out["id"])).answered_at = utcnow() - timedelta(days=31)
        db.commit()
    assert purge_requests()["respostas"] == 1
    row = _row(out["id"])
    assert row.values is None and row.purged_at is not None
    assert purge_requests()["respostas"] == 0  # JSON null não conta de novo


# ------------------------------------------------------------------ foto do documento pelo link (IA simulada)


def _photo(w: int = 400, h: int = 300) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (230, 230, 230)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def ai_on(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("chamada de rede real durante o teste")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr("app.modules.assist.ai.model_prices", lambda model: (1e-7, 4e-7))
    _env(monkeypatch, EXTERNAL_AI_ENABLED="true", OPENROUTER_API_KEY=FAKE_KEY, AI_PROVIDER="local")
    calls: list[dict] = []

    def fake(*args, **kw):  # type: ignore[no-untyped-def]
        calls.append(kw)
        data = {
            "values": [
                {"name": "cpf_do_contratante", "value": "529.982.247-25", "evidence": "RG, campo CPF"},
                {"name": "nome_do_contratante", "value": "Ana Lima", "evidence": "RG, campo nome"},
            ],
            "documents": ["RG"],
        }
        return ChatResult(
            data=data, model=kw["model"], tokens_in=900, tokens_out=100, cost_usd=0.0004, duration_ms=5
        )

    monkeypatch.setattr(OpenRouterChat, "complete", fake)
    yield calls
    reset_settings_cache()


def test_photo_read_uses_the_workspace_quota_and_is_limited_per_link(api, api2, gen, ai_on):
    from sqlalchemy import select

    from app.db.models import AISpend
    from app.db.session import get_factory

    out = create(
        api,
        gen["id"],
        fields=["nome_do_contratante", "cpf_do_contratante"],
        allow_photos=True,
        prefill={"nome_do_contratante": "Maria Souza"},
        prefill_mode="readonly",
    )
    token = _token(out["url"])
    page = api2.get(f"/public/requests/{token}").json()
    assert page["photos"] == {"allowed": True, "reads_left": 3}
    files = [("files", ("foto.jpg", _photo(), "image/jpeg"))]
    # arquivo recusado antes da IA não gasta leitura
    bad = api2.post(f"/public/requests/{token}/fill-files", files=[("files", ("x.txt", b"oi", "text/plain"))])
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "AI_FILE_TYPE"
    res = api2.post(f"/public/requests/{token}/fill-files", files=files)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["values"] == {"cpf_do_contratante": "529.982.247-25"}  # o nome fixado não vai para a IA
    assert body["reads_left"] == 2
    assert "nome_do_contratante" not in str(ai_on[0]["schema"])
    with get_factory()() as db:
        spend = db.scalars(select(AISpend)).all()
    assert [str(s.workspace_id) for s in spend] == [
        gen["me"]["workspace"]["id"]
    ]  # cota do espaço do profissional
    assert api2.post(f"/public/requests/{token}/fill-files", files=files).status_code == 200
    assert api2.post(f"/public/requests/{token}/fill-files", files=files).status_code == 200
    last = api2.post(f"/public/requests/{token}/fill-files", files=files)
    assert last.status_code == 429 and last.json()["error"]["code"] == "REQUEST_READS_USED"
    four = [("files", (f"f{i}.jpg", _photo(), "image/jpeg")) for i in range(4)]
    assert api2.post(f"/public/requests/{token}/fill-files", files=four).status_code == 422


def test_photos_need_permission_on_the_link(api, api2, gen, ai_on):
    token = _token(create(api, gen["id"])["url"])
    r = api2.post(
        f"/public/requests/{token}/fill-files", files=[("files", ("foto.jpg", _photo(), "image/jpeg"))]
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "REQUEST_PHOTOS_DISABLED"
    assert ai_on == []
