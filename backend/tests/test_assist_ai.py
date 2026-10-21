"""IA para quem usa o modelo (D33): trava geral, cota do plano, teto, preencher por texto, revisar e marcar campos.

Nenhum teste fala com a rede: a OpenRouter é simulada e qualquer chamada HTTP real derruba o teste.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.ai.openrouter import FIELDS_SCHEMA, ChatResult, OpenRouterChat
from app.core.config import reset_settings_cache
from tests.flows import build_generator, upload

FAKE_KEY = "sk-or-v1-" + "a" * 64


@pytest.fixture()
def no_network(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("chamada de rede real durante o teste")

    # só o transporte de rede de verdade (o cliente de teste do FastAPI usa um transporte próprio, em memória)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr("app.modules.assist.ai.model_prices", lambda model: (1e-7, 4e-7))


@pytest.fixture()
def ai_on(monkeypatch: pytest.MonkeyPatch, no_network):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("EXTERNAL_AI_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("AI_PROVIDER", "local")  # a análise de campos só usa a IA no teste dela (abaixo)
    reset_settings_cache()
    yield
    reset_settings_cache()


class FakeChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses: list[dict] = []

    def __call__(self, *args, **kw):  # type: ignore[no-untyped-def]
        self.calls.append(kw)
        data = self.responses.pop(0) if self.responses else {"suggestions": []}
        return ChatResult(data=data, model=kw["model"], tokens_in=500, tokens_out=200, cost_usd=0.0002, duration_ms=5)


@pytest.fixture()
def fake_chat(monkeypatch: pytest.MonkeyPatch) -> FakeChat:
    fake = FakeChat()
    monkeypatch.setattr(OpenRouterChat, "complete", fake)
    return fake


def test_ai_is_off_by_default_and_nothing_leaves(api, no_network):
    api.register()
    assert api.get("/assist/status").json()["enabled"] is False
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    r = api.post(f"/generators/{gid}/assist/fill", json={"text": "Maria, CPF 529.982.247-25"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "AI_DISABLED"


def test_fill_from_pasted_text_validates_each_value(api, demo_docx, ai_on, fake_chat):
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    fake_chat.responses.append(
        {
            "values": [
                {"name": "nome_do_contratante", "value": "Maria Souza", "evidence": "Oi, sou a Maria Souza"},
                {"name": "cpf_do_contratante", "value": "111.111.111-11", "evidence": "meu CPF 111.111.111-11"},
                {"name": "valor_mensal", "value": "1.234,50", "evidence": "R$ 1.234,50 por mês"},
                {"name": "data_de_inicio", "value": "01/02/2026", "evidence": "começa em fevereiro"},  # inventado
            ]
        }
    )
    out = api.post(f"/generators/{gid}/assist/fill", json={"text": "Oi, sou a Maria Souza, meu CPF 111.111.111-11, R$ 1.234,50 por mês"}).json()
    assert out["values"]["nome_do_contratante"] == "Maria Souza"
    assert "cpf_do_contratante" in out["invalid"]  # CPF inválido: vai para o campo, mas marcado
    assert out["evidence"]["valor_mensal"] == "R$ 1.234,50 por mês"
    assert "data_de_inicio" in out["missing"] and "data_de_inicio" not in out["values"]  # não estava no texto
    sent = fake_chat.calls[0]
    assert "nome_do_contratante" in sent["user"] and "Maria Souza" in sent["user"]
    assert sent["schema"]["properties"]["values"]["items"]["properties"]["name"]["enum"][0] == "nome_do_contratante"
    status = api.get("/assist/status").json()
    assert status == {"enabled": True, "actions_used": 1, "actions_limit": 200}


def test_quota_of_the_plan_blocks_after_the_limit(api, demo_docx, ai_on, fake_chat):
    from app.db.models import Workspace
    from app.db.session import get_factory

    api.register()
    gid = build_generator(api, demo_docx)["id"]
    ws_id = api.get("/auth/me").json()["workspace"]["id"]
    with get_factory()() as db:
        ws = db.get(Workspace, __import__("uuid").UUID(ws_id))
        ws.limits = {"max_ai_actions_per_month": 1}
        db.commit()
    fake_chat.responses.append({"values": []})
    assert api.post(f"/generators/{gid}/assist/fill", json={"text": "texto qualquer"}).status_code == 200
    second = api.post(f"/generators/{gid}/assist/fill", json={"text": "texto qualquer"})
    assert second.status_code == 409 and second.json()["error"]["code"] == "AI_QUOTA_EXCEEDED"
    assert len(fake_chat.calls) == 1  # a segunda nem chegou a sair


def test_grounding_accepts_reformatted_values_and_rejects_invented_ones():
    from app.modules.assist.service import _grounded

    src = "Sou a Ana Lúcia, CPF 52998224725, começo dia 10 de novembro. Fone (31) 98877-1122."
    assert _grounded(src, "529.982.247-25", "")  # mesmo número, outra formatação
    assert _grounded(src, "10/11/2026", "começo dia 10 de novembro")
    assert _grounded(src, "Ana Lúcia", "sou a ana lucia")  # sem acento/caixa
    assert not _grounded(src, "Consultoria em software", "Consultoria em software")  # opção escolhida sem base no texto
    assert not _grounded(src, "Rua das Flores, 10", "")


def test_monthly_budget_cap_stops_calls(api, demo_docx, ai_on, fake_chat, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_MONTHLY_BUDGET_USD", "0.000001")
    reset_settings_cache()
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    r = api.post(f"/generators/{gid}/assist/fill", json={"text": "Maria"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "AI_BUDGET_EXHAUSTED"
    assert fake_chat.calls == []


def test_review_points_out_inconsistencies_only_for_known_fields(api, demo_docx, ai_on, fake_chat):
    api.register()
    gid = build_generator(api, demo_docx)["id"]
    fake_chat.responses.append(
        {
            "issues": [
                {"field": "data_de_inicio", "severity": "alta", "message": "A data de início é anterior à assinatura."},
                {"field": "campo_inexistente", "severity": "baixa", "message": "Confira o nome."},
            ]
        }
    )
    out = api.post(f"/generators/{gid}/assist/review", json={"values": {"nome_do_contratante": "Ana Lima", "data_de_inicio": "01/01/2020"}}).json()
    assert "issues" in out, out
    assert out["issues"][0] == {"field": "data_de_inicio", "label": "Data de início", "severity": "alta", "message": "A data de início é anterior à assinatura."}
    assert out["issues"][1]["field"] == ""  # campo desconhecido não é inventado
    doc = fake_chat.calls[0]["user"]
    assert "⟦nome_do_contratante: Ana Lima⟧" in doc and "⟦data_de_inicio: 01/01/2020⟧" in doc


def test_field_analysis_uses_the_model_and_records_cost(api, demo_docx, ai_on, fake_chat, monkeypatch: pytest.MonkeyPatch):
    from sqlalchemy import select

    from app.db.models import AISpend
    from app.db.session import get_factory

    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    reset_settings_cache()
    fake_chat.responses.append(
        {"suggestions": [{"block": "body/p3", "text": "João da Silva", "name": "nome_contratante", "label": "Nome do contratante", "type": "text_short", "confidence": 0.95, "reason": "parte"}]}
    )
    api.register()
    gid = api.post("/generators", json={"name": "G"}).json()["id"]
    upload(api, gid, demo_docx)
    data = api.get(f"/generators/{gid}/suggestions").json()
    assert data["analysis"]["provider"] == "openrouter" and data["analysis"]["provider_label"] == "Campos encontrados pela IA"
    nome = next(g for g in data["items"] if g["suggested_name"] == "nome_contratante")
    assert nome["source"] == "ai"
    with get_factory()() as db:
        spend = db.scalars(select(AISpend)).all()
    assert [(s.purpose, s.status, float(s.cost_usd)) for s in spend] == [("analysis", "settled", 0.0002)]
    assert fake_chat.calls[0]["schema"] == FIELDS_SCHEMA


def test_openrouter_request_asks_for_private_providers_and_strict_json():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": '{"suggestions": []}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "cost": 0.00001}})

    chat = OpenRouterChat(FAKE_KEY, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    res = chat.complete(model="google/gemini-2.5-flash-lite", system="s", user="u", schema_name="campos", schema=FIELDS_SCHEMA, max_tokens=100)
    body = seen[0]
    assert body["provider"] == {"data_collection": "deny", "require_parameters": True}
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "temperature" not in body  # modelos de raciocínio recusam; com require_parameters daria 404
    assert res.cost_usd == 0.00001 and res.data == {"suggestions": []}


@pytest.mark.parametrize(("status", "code"), [(401, "AI_AUTH_FAILED"), (402, "AI_NO_CREDIT"), (404, "AI_REQUEST_REJECTED"), (429, "AI_RATE_LIMITED")])
def test_openrouter_errors_become_stable_codes(status, code):
    from app.adapters.ai.base import AIUnavailable

    chat = OpenRouterChat(FAKE_KEY, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"error": {"message": "x"}}))), sleep=lambda s: None)
    with pytest.raises(AIUnavailable) as exc:
        chat.complete(model="m", system="s", user="u", schema_name="x", schema={"type": "object"}, max_tokens=10)
    assert exc.value.code == code
