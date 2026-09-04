"""Billing lifecycle safeguards for destructive account operations."""

from app.config import settings


class SubscriptionCancellationUnavailableError(RuntimeError):
    """Raised when Stripe cannot confirm that a subscription is canceled."""


def cancel_subscription_before_account_deletion(
    subscription_id: str | None,
) -> None:
    """Confirm a known subscription cannot bill before account deletion."""
    if subscription_id is None:
        return
    if not settings.stripe_secret_key:
        raise SubscriptionCancellationUnavailableError(
            "Stripe is not configured."
        )

    try:
        import stripe

        stripe.api_key = settings.stripe_secret_key
        subscription = stripe.Subscription.retrieve(subscription_id)
        if subscription.status == "canceled":
            return

        canceled_subscription = stripe.Subscription.cancel(subscription_id)
        if canceled_subscription.status != "canceled":
            raise SubscriptionCancellationUnavailableError(
                "Stripe did not confirm subscription cancellation."
            )
    except SubscriptionCancellationUnavailableError:
        raise
    except Exception as error:
        raise SubscriptionCancellationUnavailableError(
            "Stripe could not confirm subscription cancellation."
        ) from error
