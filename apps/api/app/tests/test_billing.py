"""Stripe billing. Stripe itself is never called: checkout/portal mock
the SDK surface, and webhook tests sign real payloads with Stripe's own HMAC
scheme so the actual verification path runs."""

import json
import time
from uuid import UUID
from unittest.mock import MagicMock

import pytest
import stripe as stripe_lib

from app.config import settings
from app.models import Parent
from app.services.auth import create_access_token, hash_password

WEBHOOK_SECRET = "whsec_test_secret"


def _uuid(value: str) -> UUID:
    """Convert a string ID to UUID for db.get lookups."""
    return UUID(value)


def _signed(payload: dict) -> tuple[bytes, str]:
    """Produce (body, Stripe-Signature) exactly as Stripe would."""
    body = json.dumps(payload).encode()
    timestamp = int(time.time())
    signature = stripe_lib.WebhookSignature._compute_signature(
        f"{timestamp}.{body.decode()}", WEBHOOK_SECRET
    )
    return body, f"t={timestamp},v1={signature}"


def _post_event(client, payload: dict, *, signature: str | None = None):
    body, sig = _signed(payload)
    return client.post(
        "/billing/webhook",
        content=body,
        headers={
            "stripe-signature": signature if signature is not None else sig
        },
    )


def _event(event_type: str, obj: dict) -> dict:
    return {"id": "evt_1", "type": event_type, "data": {"object": obj}}


def _login(client, db_session_factory, email="billing-test@example.com"):
    """Register a parent via the API and return the auth dict."""
    client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
        },
    )
    response = client.post(
        "/auth/login",
        json={"email": email, "password": "password123"},
    )
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    with db_session_factory() as db:
        parent = db.query(Parent).filter(Parent.email == email).first()
        return {"id": str(parent.id), "email": parent.email}


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


# --- the stub hole is closed ---


def test_stub_checkout_subscribes_in_dev(client, db_session_factory):
    _login(client, db_session_factory)
    response = client.post("/billing/checkout")
    assert response.status_code == 200
    assert response.json()["stub"] is True


def test_unconfigured_checkout_in_prod_is_503(
    client, db_session_factory, monkeypatch
):
    parent = _login(client, db_session_factory)
    monkeypatch.setattr(settings, "app_environment", "production")

    response = client.post("/billing/checkout")

    assert response.status_code == 503
    me = client.get("/auth/me").json()
    assert me["is_subscribed"] is False, "unconfigured billing granted a sub"


# --- checkout and portal (SDK mocked) ---


def test_checkout_creates_a_stripe_session(
    client, db_session_factory, stripe_configured, monkeypatch
):
    _login(client, db_session_factory)
    created = {}

    def fake_create(**kwargs):
        created.update(kwargs)
        return MagicMock(url="https://checkout.stripe.test/s1")

    monkeypatch.setattr(
        stripe_lib.checkout.Session, "create", staticmethod(fake_create)
    )

    response = client.post("/billing/checkout")

    assert response.json() == {
        "checkout_url": "https://checkout.stripe.test/s1",
        "stub": False,
    }
    assert created["mode"] == "subscription"
    assert created["line_items"] == [{"price": "price_x", "quantity": 1}]
    assert created["client_reference_id"]


def test_checkout_reuses_existing_stripe_customer(
    client, db_session_factory, stripe_configured, monkeypatch
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        db.get(Parent, _uuid(parent["id"])).stripe_customer_id = "cus_existing"
        db.commit()
    created = {}
    monkeypatch.setattr(
        stripe_lib.checkout.Session,
        "create",
        staticmethod(
            lambda **kw: (created.update(kw), MagicMock(url="https://x"))[1]
        ),
    )

    client.post("/billing/checkout")

    assert created["customer"] == "cus_existing"
    assert created["customer_email"] is None


def test_portal_requires_a_subscription(client, db_session_factory, stripe_configured):
    _login(client, db_session_factory)
    assert client.post("/billing/portal").status_code == 409


def test_portal_returns_stripe_portal_url(
    client, db_session_factory, stripe_configured, monkeypatch
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        db.get(Parent, _uuid(parent["id"])).stripe_customer_id = "cus_1"
        db.commit()
    monkeypatch.setattr(
        stripe_lib.billing_portal.Session,
        "create",
        staticmethod(
            lambda **kw: MagicMock(url="https://portal.stripe.test/p1")
        ),
    )

    response = client.post("/billing/portal")

    assert response.json() == {"portal_url": "https://portal.stripe.test/p1"}


# --- webhook: the signature IS the authentication ---


def test_webhook_rejects_bad_signature(client, stripe_configured):
    response = _post_event(
        client,
        _event("checkout.session.completed", {"client_reference_id": "p1"}),
        signature="t=1,v1=deadbeef",
    )
    assert response.status_code == 400


def test_webhook_rejects_wrong_secret(
    client, stripe_configured, monkeypatch
):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_other")
    response = _post_event(
        client,
        _event("checkout.session.completed", {"client_reference_id": "p1"}),
    )
    assert response.status_code == 400


def test_webhook_unconfigured_is_503(client):
    response = client.post(
        "/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "x"},
    )
    assert response.status_code == 503


def test_checkout_completed_subscribes_parent(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)

    response = _post_event(
        client,
        _event(
            "checkout.session.completed",
            {
                "client_reference_id": parent["id"],
                "customer": "cus_9",
                "payment_status": "paid",
                "subscription": "sub_9",
            },
        ),
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        assert row.is_subscribed is True
        assert row.stripe_customer_id == "cus_9"


def test_checkout_completed_is_idempotent(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)
    event = _event(
        "checkout.session.completed",
        {
            "client_reference_id": parent["id"],
            "customer": "cus_9",
            "payment_status": "paid",
        },
    )

    assert _post_event(client, event).status_code == 200
    assert _post_event(client, event).status_code == 200

    with db_session_factory() as db:
        assert db.get(Parent, _uuid(parent["id"])).is_subscribed is True


def test_checkout_completed_for_deleted_parent_acked(
    client, stripe_configured
):
    response = _post_event(
        client,
        _event(
            "checkout.session.completed",
            {"client_reference_id": "gone", "customer": "cus_9"},
        ),
    )
    assert response.status_code == 200


def test_subscription_deleted_unsubscribes_parent(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        row.is_subscribed = True
        row.stripe_customer_id = "cus_9"
        db.commit()

    response = _post_event(
        client,
        _event("customer.subscription.deleted", {"customer": "cus_9"}),
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        assert db.get(Parent, _uuid(parent["id"])).is_subscribed is False


def test_payment_failed_reports_but_no_unsubscribe(
    client, db_session_factory, stripe_configured, monkeypatch
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        row.is_subscribed = True
        row.stripe_customer_id = "cus_9"
        db.commit()
    reported = []
    monkeypatch.setattr(
        "app.routers.billing.observability.report_message",
        lambda message, **tags: reported.append((message, tags)),
    )

    response = _post_event(
        client,
        _event("invoice.payment_failed", {"customer": "cus_9"}),
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        assert db.get(Parent, _uuid(parent["id"])).is_subscribed is True
    assert reported and "payment failed" in reported[0][0]
    assert reported[0][1]["parent_id"] == parent["id"]


def test_portal_unconfigured_is_503(client, db_session_factory):
    _login(client, db_session_factory)
    assert client.post("/billing/portal").status_code == 503


# --- ordering, replay, and states between paid and cancelled ---


def test_late_checkout_doesnt_resurrect_cancelled(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        row.stripe_customer_id = "cus_9"
        db.commit()

    deleted = _event("customer.subscription.deleted", {"customer": "cus_9"})
    deleted["id"] = "evt_deleted"
    deleted["created"] = 2000
    completed = _event(
        "checkout.session.completed",
        {
            "client_reference_id": parent["id"],
            "customer": "cus_9",
            "payment_status": "paid",
            "mode": "subscription",
        },
    )
    completed["id"] = "evt_completed"
    completed["created"] = 1000

    assert _post_event(client, deleted).status_code == 200
    assert _post_event(client, completed).status_code == 200

    with db_session_factory() as db:
        assert (
            db.get(Parent, _uuid(parent["id"])).is_subscribed is False
        ), "out-of-order delivery granted free access"


def test_replayed_event_acked_without_side_effects(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)
    event = _event(
        "checkout.session.completed",
        {
            "client_reference_id": parent["id"],
            "customer": "cus_9",
            "payment_status": "paid",
        },
    )

    assert _post_event(client, event).status_code == 200
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        row.is_subscribed = False
        db.commit()

    replay = _post_event(client, event)

    assert replay.status_code == 200
    assert replay.json().get("duplicate") is True
    with db_session_factory() as db:
        assert (
            db.get(Parent, _uuid(parent["id"])).is_subscribed is False
        ), "replay re-subscribed a cancelled parent"


def test_unsettled_checkout_doesnt_subscribe(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)

    response = _post_event(
        client,
        _event(
            "checkout.session.completed",
            {
                "client_reference_id": parent["id"],
                "customer": "cus_9",
                "payment_status": "unpaid",
                "status": "open",
            },
        ),
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        assert db.get(Parent, _uuid(parent["id"])).is_subscribed is False


def test_async_payment_succeeds_subscribes(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)

    response = _post_event(
        client,
        _event(
            "checkout.session.async_payment_succeeded",
            {
                "client_reference_id": parent["id"],
                "customer": "cus_9",
                "subscription": "sub_1",
            },
        ),
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        assert row.is_subscribed is True
        assert row.stripe_subscription_id == "sub_1"


def test_subscription_marked_unpaid_revokes(
    client, db_session_factory, stripe_configured
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        row.is_subscribed = True
        row.stripe_customer_id = "cus_9"
        db.commit()

    response = _post_event(
        client,
        _event(
            "customer.subscription.updated",
            {"customer": "cus_9", "status": "unpaid"},
        ),
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        assert db.get(Parent, _uuid(parent["id"])).is_subscribed is False


def test_poison_event_acked_not_retried(client, stripe_configured):
    body_missing_data = {
        "id": "evt_poison",
        "type": "checkout.session.completed",
    }
    assert _post_event(client, body_missing_data).status_code == 200

    no_reference = _event(
        "checkout.session.completed", {"payment_status": "paid"}
    )
    no_reference["id"] = "evt_no_ref"
    assert _post_event(client, no_reference).status_code == 200


def test_events_leave_audit_trail(
    client, db_session_factory, stripe_configured
):
    from app.models import StripeEvent

    parent = _login(client, db_session_factory)
    event = _event(
        "checkout.session.completed",
        {
            "client_reference_id": parent["id"],
            "customer": "cus_9",
            "payment_status": "paid",
        },
    )
    event["id"] = "evt_audit"
    event["created"] = 1234

    _post_event(client, event)

    with db_session_factory() as db:
        row = db.get(StripeEvent, "evt_audit")
        assert row is not None
        assert row.parent_id == parent["id"]
        assert row.stripe_created == 1234


# --- account deletion cancels the money ---


def test_account_deletion_cancels_stripe(
    client, db_session_factory, stripe_configured, monkeypatch
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        row.stripe_customer_id = "cus_9"
        row.stripe_subscription_id = "sub_9"
        db.commit()
    cancelled = []
    monkeypatch.setattr(
        stripe_lib.Subscription,
        "cancel",
        staticmethod(lambda sub_id, **_kw: cancelled.append(sub_id)),
    )

    response = client.delete("/auth/me")

    assert response.status_code == 204
    assert cancelled == ["sub_9"]


def test_account_deletion_proceeds_when_stripe_fails(
    client, db_session_factory, stripe_configured, monkeypatch
):
    parent = _login(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(Parent, _uuid(parent["id"]))
        row.stripe_subscription_id = "sub_9"
        db.commit()
    reported = []
    monkeypatch.setattr(
        stripe_lib.Subscription,
        "cancel",
        staticmethod(
            lambda *_a, **_kw: (_ for _ in ()).throw(
                RuntimeError("stripe down")
            )
        ),
    )
    monkeypatch.setattr(
        "app.routers.auth.observability.report",
        lambda exc, **tags: reported.append(tags),
    )

    response = client.delete("/auth/me")

    assert response.status_code == 204, "vendor outage blocked deletion"
    with db_session_factory() as db:
        assert db.get(Parent, _uuid(parent["id"])) is None
    assert reported and reported[0]["stripe_subscription"] == "sub_9"


# --- free story limit enforcement ---


def test_free_story_limit_enforced(client, db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "free_stories_limit", 2)
    parent = _login(client, db_session_factory)

    from app.models import Child

    with db_session_factory() as db:
        p = db.get(Parent, _uuid(parent["id"]))
        child = Child(
            name="Test",
            age=5,
            interests="stars",
            language="en",
            parent_id=p.id,
        )
        db.add(child)
        db.commit()
        child_id = str(child.id)

    for _ in range(2):
        response = client.post(
            "/stories",
            json={"child_id": child_id, "event_text": "test event"},
        )
        assert response.status_code in (200, 201)

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "test event"},
    )
    assert response.status_code == 402


def test_subscribed_bypasses_free_limit(
    client, db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "free_stories_limit", 1)
    parent = _login(client, db_session_factory)

    with db_session_factory() as db:
        db.get(Parent, _uuid(parent["id"])).is_subscribed = True
        db.commit()

    from app.models import Child

    with db_session_factory() as db:
        p = db.get(Parent, _uuid(parent["id"]))
        child = Child(
            name="Test",
            age=5,
            interests="stars",
            language="en",
            parent_id=p.id,
        )
        db.add(child)
        db.commit()
        child_id = str(child.id)

    for _ in range(3):
        response = client.post(
            "/stories",
            json={"child_id": child_id, "event_text": "test event"},
        )
        assert response.status_code in (200, 201)
