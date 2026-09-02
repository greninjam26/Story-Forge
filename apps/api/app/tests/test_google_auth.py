import pytest
from google.auth import exceptions as google_exceptions

from app.config import settings
from app.services import google_auth


def test_valid_google_credential_returns_verified_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "google_client_id", "web-client-id")
    monkeypatch.setattr(
        google_auth.id_token,
        "verify_oauth2_token",
        lambda credential, _request, audience: {
            "sub": "google-subject",
            "email": "parent@gmail.com",
            "email_verified": True,
            "received": credential,
            "audience": audience,
        },
    )

    claims = google_auth.verify_google_credential("signed-token")

    assert claims["received"] == "signed-token"
    assert claims["audience"] == "web-client-id"


@pytest.mark.parametrize(
    "provider_error",
    [ValueError("bad token"), google_exceptions.GoogleAuthError("bad issuer")],
)
def test_rejected_google_token_is_invalid_identity(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: Exception,
) -> None:
    monkeypatch.setattr(settings, "google_client_id", "web-client-id")

    def reject(*_args: object, **_kwargs: object) -> None:
        raise provider_error

    monkeypatch.setattr(google_auth.id_token, "verify_oauth2_token", reject)

    with pytest.raises(google_auth.GoogleIdentityInvalid):
        google_auth.verify_google_credential("bad-token")


def test_google_transport_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "google_client_id", "web-client-id")

    def fail_transport(*_args: object, **_kwargs: object) -> None:
        raise google_exceptions.TransportError("offline")

    monkeypatch.setattr(
        google_auth.id_token,
        "verify_oauth2_token",
        fail_transport,
    )

    with pytest.raises(google_auth.GoogleIdentityUnavailable):
        google_auth.verify_google_credential("signed-token")


def test_unverified_email_claim_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "google_client_id", "web-client-id")
    monkeypatch.setattr(
        google_auth.id_token,
        "verify_oauth2_token",
        lambda *_args, **_kwargs: {
            "sub": "google-subject",
            "email": "parent@gmail.com",
            "email_verified": False,
        },
    )

    with pytest.raises(google_auth.GoogleIdentityInvalid):
        google_auth.verify_google_credential("signed-token")
