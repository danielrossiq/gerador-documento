"""Rotas de cobrança. O webhook é público (sem sessão/CSRF) e só confia na assinatura HMAC da Stripe."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import Ctx, get_ctx
from app.core.errors import ValidationFailed
from app.core.logging import get_logger
from app.db.session import get_db
from app.modules.billing import service
from app.modules.billing.plans import plans
from app.modules.billing.stripe_client import StripeError, verify_webhook

log = get_logger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans")
def list_plans() -> dict[str, Any]:
    """Público: planos, preços e quais formas de pagamento estão disponíveis neste ambiente."""
    return {"plans": list(plans().values()), "currency": "BRL", "checkout": service.checkout_methods()}


@router.get("")
def my_subscription(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.subscription_out(ctx)


class CheckoutIn(BaseModel):
    plan: Literal["profissional", "escritorio"]
    cycle: Literal["mensal", "anual"]
    method: Literal["card", "pix"] = "card"


@router.post("/checkout")
def checkout(body: CheckoutIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, str]:
    return {"url": service.create_checkout(ctx, body.plan, body.cycle, body.method)}


class SyncIn(BaseModel):
    session_id: str


@router.post("/sync")
def sync(body: SyncIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    return service.sync_checkout(ctx, body.session_id)


@router.post("/portal")
def portal(ctx: Ctx = Depends(get_ctx)) -> dict[str, str]:
    return {"url": service.create_portal(ctx)}


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request, stripe_signature: str | None = Header(default=None), db: Session = Depends(get_db)
) -> dict[str, str]:
    secret = get_settings().stripe_webhook_signing_secret
    if not secret:
        raise ValidationFailed("Webhook de pagamentos não configurado.", code="BILLING_NOT_CONFIGURED")
    payload = await request.body()
    if len(payload) > 1_000_000:
        raise ValidationFailed("Evento grande demais.", code="BILLING_BAD_SIGNATURE")
    try:
        event = verify_webhook(payload, stripe_signature, secret)
    except StripeError as exc:
        log.warning("billing_webhook_recusado", extra={"code": exc.code})
        raise ValidationFailed(str(exc), code=exc.code) from exc
    return {"status": service.handle_event(db, event)}
