"""Stripe subscription billing.

Provider-switched: unset keys mean stub behavior, but the stub only
auto-subscribes in dev auth mode. In prod, missing keys return 503.

Webhooks are the source of truth for subscription state. The redirect
back from Checkout proves nothing — a parent can close the tab, and Stripe
retries webhooks until acknowledged, so every handler is idempotent.
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import observability
from app.config import settings
from app.db import get_db
from app.dependencies import get_current_parent
from app.models import Parent, StripeEvent
from app.ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _stripe():
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def _configured() -> bool:
    return bool(settings.stripe_secret_key and settings.stripe_price_id)


@router.post("/checkout")
def create_checkout_session(
    parent: Parent = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    if not _configured():
        if settings.app_environment != "development":
            raise HTTPException(503, "billing is not configured")
        logger.warning(
            "stub checkout (%s): parent %s subscribed with no payment",
            settings.app_environment,
            parent.id,
        )
        parent.is_subscribed = True
        db.commit()
        return {
            "checkout_url": None,
            "stub": True,
            "message": "no Stripe keys set — subscribed directly",
        }

    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{settings.web_origin}/billing/success",
        cancel_url=f"{settings.web_origin}/billing/cancel",
        client_reference_id=str(parent.id),
        customer=parent.stripe_customer_id or None,
        customer_email=None if parent.stripe_customer_id else parent.email,
    )
    return {"checkout_url": session.url, "stub": False}


@router.post("/portal")
def create_billing_portal_session(
    parent: Parent = Depends(get_current_parent),
):
    """Stripe-hosted subscription management — cancel lives there, not here."""
    if not _configured():
        raise HTTPException(503, "billing is not configured")
    if not parent.stripe_customer_id:
        raise HTTPException(409, "no subscription to manage")

    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=parent.stripe_customer_id,
        return_url=f"{settings.web_origin}/children",
    )
    return {"portal_url": session.url}


@router.post(
    "/webhook",
    dependencies=[Depends(rate_limit("stripe_webhook", 300, 60))],
)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Subscription state transitions, driven by Stripe's signed events.

    Unauthenticated by design (Stripe calls it), so the signature IS the
    authentication.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, "billing webhook is not configured")

    import stripe

    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except (stripe.error.SignatureVerificationError, ValueError) as exc:
        logger.warning("stripe webhook rejected: %s", type(exc).__name__)
        raise HTTPException(400, "invalid webhook signature") from exc

    return _apply_event(db, event)


_INACTIVE_SUB_STATUSES = {
    "canceled",
    "unpaid",
    "incomplete_expired",
    "paused",
}
_SETTLED_PAYMENT_STATUSES = {"paid", "no_payment_required"}


def _apply_event(db: Session, event: dict) -> dict:
    """Idempotent, order-tolerant application of one verified event."""
    data = (event.get("data") or {}).get("object") or {}
    customer_id = data.get("customer")

    record = StripeEvent(
        id=event.get("id") or f"missing-{uuid4()}",
        type=event.get("type", "unknown"),
        stripe_customer_id=customer_id,
        stripe_created=int(event.get("created") or 0),
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("duplicate stripe event acked: %s", event.get("id"))
        return {"received": True, "duplicate": True}

    if event["type"] == "checkout.session.completed":
        _handle_checkout_completed(db, record, data)
    elif event["type"] == "checkout.session.async_payment_succeeded":
        _subscribe_if_not_cancelled_since(db, record, data)
    elif event["type"] == "checkout.session.async_payment_failed":
        observability.report_message(
            "stripe async payment failed",
            stripe_customer=customer_id,
            event_id=record.id,
        )
    elif event["type"] == "customer.subscription.deleted":
        _set_subscription(db, record, customer_id, subscribed=False)
    elif event["type"] == "customer.subscription.updated":
        status = data.get("status")
        if status in _INACTIVE_SUB_STATUSES:
            _set_subscription(db, record, customer_id, subscribed=False)
        elif status in ("active", "trialing"):
            _set_subscription(db, record, customer_id, subscribed=True)
    elif event["type"] == "invoice.payment_failed":
        parent = _parent_by_customer(db, customer_id)
        observability.report_message(
            "stripe invoice payment failed",
            parent_id=str(parent.id) if parent else None,
            stripe_customer=customer_id,
            event_id=record.id,
        )

    db.commit()
    return {"received": True}


def _handle_checkout_completed(
    db: Session, record: StripeEvent, data: dict
) -> None:
    if data.get("mode") not in (None, "subscription"):
        return
    if data.get("payment_status") not in _SETTLED_PAYMENT_STATUSES:
        logger.info(
            "checkout completed but unsettled (%s); awaiting async payment",
            data.get("payment_status"),
        )
        return
    _subscribe_if_not_cancelled_since(db, record, data)


def _subscribe_if_not_cancelled_since(
    db: Session, record: StripeEvent, data: dict
) -> None:
    reference = data.get("client_reference_id")
    parent = db.get(Parent, reference) if reference else None
    if parent is None and data.get("customer"):
        parent = _parent_by_customer(db, data.get("customer"))
    if parent is None:
        logger.warning(
            "checkout completed for unknown parent (event %s)", record.id
        )
        return

    customer_id = data.get("customer")
    if customer_id:
        cancelled_later = (
            db.query(StripeEvent)
            .filter(
                StripeEvent.stripe_customer_id == customer_id,
                StripeEvent.type == "customer.subscription.deleted",
                StripeEvent.stripe_created >= record.stripe_created,
                StripeEvent.id != record.id,
            )
            .first()
        )
        if cancelled_later is not None:
            logger.warning(
                "checkout %s ignored: subscription already cancelled by %s",
                record.id,
                cancelled_later.id,
            )
            record.parent_id = parent.id
            return

    parent.is_subscribed = True
    parent.stripe_customer_id = customer_id
    parent.stripe_subscription_id = data.get("subscription")
    record.parent_id = parent.id


def _set_subscription(
    db: Session,
    record: StripeEvent,
    customer_id: str | None,
    *,
    subscribed: bool,
) -> None:
    parent = _parent_by_customer(db, customer_id)
    if parent is None:
        return
    parent.is_subscribed = subscribed
    record.parent_id = parent.id


def _parent_by_customer(db: Session, customer_id: str | None) -> Parent | None:
    if not customer_id:
        return None
    return (
        db.query(Parent)
        .filter(Parent.stripe_customer_id == customer_id)
        .first()
    )
