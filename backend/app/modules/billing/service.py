"""Assinatura do workspace: plano efetivo, uso do mês, Checkout (cartão ou Pix), portal e webhook da Stripe."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import Ctx
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import AISpend, BillingEvent, DocumentGenerator, GenerationJob, Subscription
from app.modules.audit import service as audit
from app.modules.billing.plans import FREE, plan_limits, plans, price_cents
from app.modules.billing.stripe_client import StripeClient, StripeError

log = get_logger(__name__)

PERIOD = {"mensal": timedelta(days=31), "anual": timedelta(days=366)}
PAST_DUE_GRACE = timedelta(days=7)
STRIPE_STATUS = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete": "incomplete",
    "incomplete_expired": "expired",
    "paused": "canceled",
}


# ------------------------------------------------------------------ configuração


def price_ids() -> dict[tuple[str, str], str]:
    s = get_settings()
    raw = {
        ("profissional", "mensal"): s.stripe_price_profissional_mensal,
        ("profissional", "anual"): s.stripe_price_profissional_anual,
        ("escritorio", "mensal"): s.stripe_price_escritorio_mensal,
        ("escritorio", "anual"): s.stripe_price_escritorio_anual,
    }
    return {k: v for k, v in raw.items() if v}


def checkout_methods() -> dict[str, bool]:
    s = get_settings()
    configured = bool(s.billing_enabled and s.stripe_api_key)
    return {"card": configured and len(price_ids()) == 4, "pix": configured and s.billing_pix_enabled}


def _client() -> StripeClient:
    key = get_settings().stripe_api_key
    if not key:
        raise Conflict("Pagamentos ainda não configurados neste ambiente.", code="BILLING_NOT_CONFIGURED")
    return StripeClient(key)


# ------------------------------------------------------------------ plano efetivo e uso


def current_subscription(db: Session, workspace_id: uuid.UUID) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))


def effective_plan(sub: Subscription | None, now: datetime | None = None) -> str:
    """Plano que vale agora. Cartão: enquanto a Stripe disser ativo (atraso tem 7 dias de tolerância).
    Pix: até o fim do período pago."""
    if sub is None:
        return FREE
    now = now or utcnow()
    end = sub.current_period_end
    if sub.status == "active" and (sub.method == "card" or (end is not None and end > now)):
        return sub.plan_id
    if sub.status == "past_due" and end is not None and end + PAST_DUE_GRACE > now:
        return sub.plan_id
    if sub.status == "canceled" and end is not None and end > now:  # cancelada no fim do período: vale até lá
        return sub.plan_id
    return FREE


def workspace_plan_limits(db: Session, workspace_id: uuid.UUID) -> dict[str, int] | None:
    """Limites do plano quando a cobrança está ligada; None = usar os limites padrão (cobrança desligada)."""
    if not get_settings().billing_enabled:
        return None
    return plan_limits(effective_plan(current_subscription(db, workspace_id)))


def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(db: Session, workspace_id: uuid.UUID) -> dict[str, int]:
    since = month_start()
    docs = db.scalar(  # mesma conta da cota mensal da geração (generation.service._month_usage)
        select(func.coalesce(func.sum(GenerationJob.total_items), 0)).where(
            GenerationJob.workspace_id == workspace_id,
            GenerationJob.created_at >= since,
            GenerationJob.status != "cancelled",
        )
    )
    ai = db.scalar(
        select(func.count(AISpend.id)).where(
            AISpend.workspace_id == workspace_id, AISpend.created_at >= since, AISpend.purpose != "eval"
        )
    )
    models = db.scalar(
        select(func.count(DocumentGenerator.id)).where(
            DocumentGenerator.workspace_id == workspace_id, DocumentGenerator.deleted_at.is_(None)
        )
    )
    return {"docs_this_month": int(docs or 0), "ai_actions_this_month": int(ai or 0), "models": int(models or 0)}


def subscription_out(ctx: Ctx) -> dict[str, Any]:
    sub = current_subscription(ctx.db, ctx.workspace_id)
    plan_id = effective_plan(sub)
    return {
        "billing_enabled": get_settings().billing_enabled,
        "checkout": checkout_methods(),
        "plan": plan_id,
        "plan_name": plans()[plan_id]["name"],
        "subscription": None
        if sub is None
        else {
            "plan": sub.plan_id,
            "cycle": sub.cycle,
            "status": sub.status,
            "method": sub.method,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "can_manage": bool(sub.stripe_customer_id and sub.method == "card"),
        },
        "usage": usage(ctx.db, ctx.workspace_id),
        "limits": {
            "docs_per_month": ctx.limit("max_docs_per_month"),
            "models": ctx.limit("max_generators"),
            "batch_rows": ctx.limit("max_batch_rows"),
            "ai_actions_per_month": ctx.limit("max_ai_actions_per_month"),
        },
    }


# ------------------------------------------------------------------ Checkout e portal


def create_checkout(ctx: Ctx, plan_id: str, cycle: str, method: str) -> str:
    if not ctx.is_owner:
        raise Forbidden("Só o proprietário do espaço de trabalho pode assinar ou trocar o plano.")
    if plan_id not in plans() or plan_id == FREE or cycle not in PERIOD or method not in ("card", "pix"):
        raise ValidationFailed("Plano, ciclo ou forma de pagamento inválidos.", code="BILLING_INVALID_PLAN")
    if not checkout_methods()[method]:
        raise Conflict(
            "Esta forma de pagamento ainda não está disponível." if method == "pix" else "Pagamentos ainda não configurados.",
            code="BILLING_NOT_CONFIGURED",
        )
    s = get_settings()
    sub = current_subscription(ctx.db, ctx.workspace_id)
    base = s.public_web_url.rstrip("/")
    meta = {"workspace_id": str(ctx.workspace_id), "plan": plan_id, "cycle": cycle, "method": method}
    data: dict[str, Any] = {
        # a volta traz o id da sessão: a tela confirma na hora (sync_checkout), sem depender só do webhook
        "success_url": f"{base}/assinatura?status=sucesso&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/assinatura?status=cancelado",
        "client_reference_id": str(ctx.workspace_id),
        "locale": "pt-BR",
        "metadata": meta,
    }
    if sub and sub.stripe_customer_id:
        data["customer"] = sub.stripe_customer_id
    else:
        data["customer_email"] = ctx.user.email
    plan_name = plans()[plan_id]["name"]
    if method == "card":
        if sub and sub.method == "card" and sub.status in ("active", "past_due") and sub.stripe_subscription_id:
            raise Conflict("Você já tem uma assinatura no cartão. Troque de plano em “Gerenciar assinatura”.", code="BILLING_HAS_SUBSCRIPTION")
        data |= {
            "mode": "subscription",
            "line_items": [{"price": price_ids()[(plan_id, cycle)], "quantity": 1}],
            "subscription_data": {"metadata": meta},
            "allow_promotion_codes": True,
        }
    else:
        if "customer" not in data:
            data["customer_creation"] = "always"
        data |= {
            "mode": "payment",
            # a Stripe não aceita mais payment_method_types no Checkout: as formas vêm do painel. Assinatura no
            # Brasil só aceita cartão; no avulso, uma configuração só com Pix (STRIPE_PIX_PAYMENT_METHOD_CONFIGURATION)
            # evita que o fluxo "Pix" ofereça cartão.
            "payment_method_configuration": get_settings().stripe_pix_payment_method_configuration,
            "payment_method_options": {"pix": {"expires_after_seconds": 3600}},
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "brl",
                        "unit_amount": price_cents(plan_id, cycle),
                        "product_data": {"name": f"DocFeito {plan_name} — {'12 meses' if cycle == 'anual' else '1 mês'} (Pix)"},
                    },
                }
            ],
            "payment_intent_data": {"metadata": meta},
        }
    try:
        session = _client().checkout_session(data)
    except StripeError as exc:
        raise Conflict(str(exc), code=exc.code) from exc
    audit.record(ctx.db, "billing.checkout", ctx=ctx, entity_type="workspace", entity_id=ctx.workspace_id, meta={"plan": plan_id, "cycle": cycle, "method": method})
    ctx.db.commit()
    return str(session["url"])


def create_portal(ctx: Ctx) -> str:
    if not ctx.is_owner:
        raise Forbidden("Só o proprietário do espaço de trabalho pode gerenciar a assinatura.")
    sub = current_subscription(ctx.db, ctx.workspace_id)
    if not sub or not sub.stripe_customer_id:
        raise Conflict("Não há assinatura no cartão para gerenciar.", code="BILLING_NO_SUBSCRIPTION")
    try:
        s = get_settings()
        return_url = f"{s.public_web_url.rstrip('/')}/assinatura"
        session = _client().portal_session(sub.stripe_customer_id, return_url, s.stripe_portal_configuration)
    except StripeError as exc:
        raise Conflict(str(exc), code=exc.code) from exc
    return str(session["url"])


def sync_checkout(ctx: Ctx, session_id: str) -> dict[str, Any]:
    """Volta do Checkout: busca a sessão na API da Stripe (com a nossa chave; não confia no navegador) e aplica o
    mesmo tratamento do webhook. Idempotente (ids de evento fixos por sessão). O webhook continua valendo para
    renovações, cancelamentos e falhas de pagamento."""
    if not session_id.startswith("cs_") or len(session_id) > 255:
        raise ValidationFailed("Sessão de pagamento inválida.", code="BILLING_INVALID_SESSION")
    client = _client()
    try:
        session = client.retrieve_checkout_session(session_id)
    except StripeError as exc:
        raise Conflict(str(exc), code=exc.code) from exc
    if _workspace_from(session) != ctx.workspace_id:
        raise ValidationFailed("Sessão de pagamento inválida.", code="BILLING_INVALID_SESSION")
    if session.get("status") != "complete":
        return {"sync": "pendente", **subscription_out(ctx)}
    event = {"id": f"sync_{session_id}", "type": "checkout.session.completed", "data": {"object": session}}
    handle_event(ctx.db, event)
    if session.get("mode") == "subscription" and session.get("subscription"):
        try:
            sub_obj = client.retrieve_subscription(str(session["subscription"]))
        except StripeError:
            sub_obj = None  # o plano já foi ativado acima; o fim do período chega pelo webhook
        if sub_obj:
            sub_event = {"id": f"sync_{session_id}_sub", "type": "customer.subscription.updated", "data": {"object": sub_obj}}
            handle_event(ctx.db, sub_event)
    return {"sync": "confirmado", **subscription_out(ctx)}


# ------------------------------------------------------------------ webhook


def _ts(v: Any) -> datetime | None:
    return datetime.fromtimestamp(int(v), tz=utcnow().tzinfo) if v else None


def _plan_from_price(price_id: str | None) -> tuple[str, str] | None:
    for key, pid in price_ids().items():
        if pid == price_id:
            return key
    return None


def _upsert(db: Session, workspace_id: uuid.UUID) -> Subscription:
    sub = current_subscription(db, workspace_id)
    if sub is None:
        sub = Subscription(workspace_id=workspace_id, plan_id=FREE, cycle="mensal", status="incomplete", method="card", cancel_at_period_end=False)
        db.add(sub)
    return sub


def _workspace_from(obj: dict[str, Any]) -> uuid.UUID | None:
    raw = (obj.get("metadata") or {}).get("workspace_id") or obj.get("client_reference_id")
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _apply_subscription_object(db: Session, obj: dict[str, Any], event_id: str) -> None:
    sub = db.scalar(select(Subscription).where(Subscription.stripe_subscription_id == obj.get("id")))
    if sub is None:
        ws = _workspace_from(obj)
        if ws is None:
            return
        sub = _upsert(db, ws)
        sub.stripe_subscription_id = obj.get("id")
    items = ((obj.get("items") or {}).get("data")) or [{}]
    price = (items[0].get("price") or {}).get("id")
    plan = _plan_from_price(price) or ((obj.get("metadata") or {}).get("plan"), (obj.get("metadata") or {}).get("cycle"))
    if plan[0] in plans():
        sub.plan_id, sub.cycle = plan[0], plan[1] or sub.cycle
    sub.method = "card"
    sub.status = STRIPE_STATUS.get(obj.get("status", ""), "incomplete")
    sub.current_period_end = _ts(obj.get("current_period_end") or items[0].get("current_period_end"))
    sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
    sub.stripe_customer_id = obj.get("customer") or sub.stripe_customer_id
    sub.last_event_id = event_id


def _activate_pix(db: Session, obj: dict[str, Any], event_id: str) -> None:
    ws = _workspace_from(obj)
    meta = obj.get("metadata") or {}
    if ws is None or meta.get("plan") not in plans() or meta.get("cycle") not in PERIOD:
        log.warning("billing_pix_sem_metadados")
        return
    sub = _upsert(db, ws)
    now = utcnow()
    start = sub.current_period_end if (sub.method == "pix" and sub.status == "active" and sub.current_period_end and sub.current_period_end > now) else now
    sub.plan_id, sub.cycle, sub.method, sub.status = meta["plan"], meta["cycle"], "pix", "active"
    sub.current_period_end = start + PERIOD[meta["cycle"]]
    sub.cancel_at_period_end = True  # Pix não renova sozinho
    sub.stripe_customer_id = obj.get("customer") or sub.stripe_customer_id
    sub.last_event_id = event_id


def handle_event(db: Session, event: dict[str, Any]) -> str:
    """Aplica um evento verificado. Idempotente pelo id do evento. Devolve o que foi feito (para log/teste)."""
    event_id, kind = str(event.get("id") or ""), str(event.get("type") or "")
    if not event_id:
        return "ignorado"
    if db.scalar(select(BillingEvent).where(BillingEvent.stripe_event_id == event_id)):
        return "repetido"
    obj = (event.get("data") or {}).get("object") or {}
    action = "ignorado"
    if kind == "checkout.session.completed" and obj.get("mode") == "subscription":
        ws = _workspace_from(obj)
        if ws:
            sub = _upsert(db, ws)
            meta = obj.get("metadata") or {}
            if meta.get("plan") in plans():
                sub.plan_id, sub.cycle = meta["plan"], meta.get("cycle", "mensal")
            sub.method, sub.status = "card", "active"
            sub.stripe_customer_id = obj.get("customer")
            sub.stripe_subscription_id = obj.get("subscription")
            sub.last_event_id = event_id
            action = "assinatura_cartao"
    elif kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded") and obj.get("mode") == "payment":
        if obj.get("payment_status") == "paid":
            _activate_pix(db, obj, event_id)
            action = "pix_pago"
    elif kind in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        if kind.endswith("deleted"):
            obj = {**obj, "status": "canceled"}
        _apply_subscription_object(db, obj, event_id)
        action = "assinatura_atualizada"
    elif kind == "invoice.payment_failed":
        sub = db.scalar(select(Subscription).where(Subscription.stripe_subscription_id == obj.get("subscription")))
        if sub:
            sub.status = "past_due"
            action = "pagamento_falhou"
    db.add(BillingEvent(stripe_event_id=event_id, type=kind[:80], received_at=utcnow()))
    db.commit()
    log.info("billing_evento", extra={"type": kind, "action": action})
    return action
