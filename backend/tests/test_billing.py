"""Cobrança (Stripe): planos, limites por plano, webhook assinado (cartão e Pix), idempotência e checkout."""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.config import reset_settings_cache
from app.db.base import utcnow
from app.modules.billing import service as billing
from app.modules.billing.stripe_client import sign_for_tests

SECRET = "whsec_teste_123"
PRICES = {
    "STRIPE_PRICE_PROFISSIONAL_MENSAL": "price_pro_m",
    "STRIPE_PRICE_PROFISSIONAL_ANUAL": "price_pro_a",
    "STRIPE_PRICE_ESCRITORIO_MENSAL": "price_esc_m",
    "STRIPE_PRICE_ESCRITORIO_ANUAL": "price_esc_a",
}


@pytest.fixture()
def billing_on(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("BILLING_PIX_ENABLED", "true")
    for k, v in PRICES.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()
    yield
    reset_settings_cache()


def _webhook(api, event: dict, secret: str = SECRET):  # type: ignore[no-untyped-def]
    raw = json.dumps(event).encode()
    return api.tc.post("/api/v1/billing/webhook", content=raw, headers={"Stripe-Signature": sign_for_tests(raw, secret), "Content-Type": "application/json"})


def _workspace_id(api) -> str:  # type: ignore[no-untyped-def]
    return api.get("/auth/me").json()["workspace"]["id"]


def test_plans_match_the_site():
    backend = json.loads(Path(billing.__file__).with_name("plans.json").read_text(encoding="utf-8"))
    site = json.loads((Path(__file__).resolve().parents[2] / "frontend" / "src" / "content" / "plans.json").read_text(encoding="utf-8"))
    assert backend == site


def test_public_plans_and_checkout_off_by_default(api):
    r = api.tc.get("/api/v1/billing/plans")
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["plans"]] == ["gratis", "profissional", "escritorio"]
    assert r.json()["checkout"] == {"card": False, "pix": False}
    api.register()
    me = api.get("/billing").json()
    assert me["plan"] == "gratis" and me["billing_enabled"] is False
    assert me["limits"]["models"] == 200  # cobrança desligada: limites padrão, nada muda para quem já usa


def test_free_plan_limits_apply_when_billing_is_on(api, billing_on):
    api.register()
    assert api.get("/billing").json()["limits"] == {"docs_per_month": 20, "models": 3, "batch_rows": 10, "ai_actions_per_month": 5}
    for i in range(3):
        assert api.post("/generators", json={"name": f"M{i}"}).status_code == 201
    over = api.post("/generators", json={"name": "M4"})
    assert over.status_code == 429


def test_card_subscription_webhook_upgrades_and_cancel_keeps_until_period_end(api, billing_on):
    api.register()
    ws = _workspace_id(api)
    done = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {"object": {"mode": "subscription", "client_reference_id": ws, "customer": "cus_1", "subscription": "sub_1", "metadata": {"workspace_id": ws, "plan": "profissional", "cycle": "anual", "method": "card"}}},
    }
    assert _webhook(api, done).json() == {"status": "assinatura_cartao"}
    assert _webhook(api, done).json() == {"status": "repetido"}  # a Stripe reenvia: idempotente
    me = api.get("/billing").json()
    assert me["plan"] == "profissional" and me["limits"]["models"] == 10_000 and me["limits"]["docs_per_month"] == 300
    assert me["subscription"]["can_manage"] is True

    end = int(time.time()) + 10 * 86400
    deleted = {"id": "evt_2", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_1", "customer": "cus_1", "status": "canceled", "current_period_end": end, "items": {"data": [{"price": {"id": "price_pro_a"}}]}}}}
    assert _webhook(api, deleted).json() == {"status": "assinatura_atualizada"}
    me = api.get("/billing").json()
    assert me["subscription"]["status"] == "canceled" and me["plan"] == "profissional"  # vale até o fim do período


def test_subscription_update_from_portal_changes_plan_by_price(api, billing_on):
    api.register()
    ws = _workspace_id(api)
    created = {"id": "evt_c", "type": "customer.subscription.created", "data": {"object": {"id": "sub_9", "customer": "cus_9", "status": "active", "metadata": {"workspace_id": ws}, "items": {"data": [{"price": {"id": "price_esc_m"}, "current_period_end": int(time.time()) + 86400}]}}}}
    _webhook(api, created)
    me = api.get("/billing").json()
    assert me["plan"] == "escritorio" and me["subscription"]["cycle"] == "mensal"


def test_pix_payment_activates_the_period_and_a_second_pix_extends_it(api, billing_on):
    api.register()
    ws = _workspace_id(api)

    def paid(eid: str) -> dict:
        return {"id": eid, "type": "checkout.session.completed", "data": {"object": {"mode": "payment", "payment_status": "paid", "customer": "cus_p", "metadata": {"workspace_id": ws, "plan": "profissional", "cycle": "mensal", "method": "pix"}}}}

    pending = paid("evt_p0")
    pending["data"]["object"]["payment_status"] = "unpaid"
    assert _webhook(api, pending).json() == {"status": "ignorado"}  # Pix ainda não pago: nada muda
    assert _webhook(api, paid("evt_p1")).json() == {"status": "pix_pago"}
    first = api.get("/billing").json()["subscription"]
    assert first["method"] == "pix" and first["status"] == "active" and first["cancel_at_period_end"] is True
    _webhook(api, paid("evt_p2"))
    second = api.get("/billing").json()["subscription"]
    assert second["current_period_end"] > first["current_period_end"]  # renovação antecipada soma ao período


def test_bad_signature_is_refused(api, billing_on):
    r = _webhook(api, {"id": "evt_x", "type": "checkout.session.completed", "data": {"object": {}}}, secret="whsec_outro")
    assert r.status_code == 422 and r.json()["error"]["code"] == "BILLING_BAD_SIGNATURE"


def test_effective_plan_rules():
    from app.db.models import Subscription

    now = utcnow()
    sub = Subscription(workspace_id=uuid.uuid4(), plan_id="profissional", cycle="mensal", status="active", method="pix", current_period_end=now - timedelta(minutes=1), cancel_at_period_end=True)
    assert billing.effective_plan(sub, now) == "gratis"  # Pix vencido volta ao Grátis
    sub.method = "card"
    assert billing.effective_plan(sub, now) == "profissional"  # cartão: vale o status da Stripe
    sub.status, sub.current_period_end = "past_due", now - timedelta(days=8)
    assert billing.effective_plan(sub, now) == "gratis"  # atraso além da tolerância de 7 dias


def test_checkout_builds_stripe_sessions_for_card_and_pix(api, billing_on, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(self, path, data):  # type: ignore[no-untyped-def]
        calls.append((path, data))
        return {"url": "https://checkout.stripe.com/c/pay/cs_test_1"}

    monkeypatch.setattr("app.modules.billing.stripe_client.StripeClient._post", fake_post)
    api.register()
    r = api.post("/billing/checkout", json={"plan": "profissional", "cycle": "anual", "method": "card"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com/")
    path, data = calls[-1]
    assert path == "checkout/sessions" and data["mode"] == "subscription"
    assert data["line_items"] == [{"price": "price_pro_a", "quantity": 1}] and data["metadata"]["plan"] == "profissional"

    api.post("/billing/checkout", json={"plan": "escritorio", "cycle": "mensal", "method": "pix"})
    _, pix = calls[-1]
    assert pix["mode"] == "payment" and pix["payment_method_types"] == ["pix"]
    assert pix["line_items"][0]["price_data"]["unit_amount"] == 9990


def test_checkout_unavailable_without_configuration(api):
    api.register()
    r = api.post("/billing/checkout", json={"plan": "profissional", "cycle": "mensal", "method": "card"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "BILLING_NOT_CONFIGURED"
