from typing import Any

import requests
from cachecontrol import CacheControl
from google.auth import exceptions as google_exceptions
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from app.config import settings


class GoogleIdentityInvalid(ValueError):
    pass


class GoogleIdentityUnavailable(RuntimeError):
    pass


class _TimeoutRequest(Request):
    def __call__(self, url: str, method: str = "GET", **kwargs: Any):
        kwargs.setdefault("timeout", settings.google_auth_timeout_seconds)
        return super().__call__(url=url, method=method, **kwargs)


_cached_session = CacheControl(requests.Session())
_google_request = _TimeoutRequest(session=_cached_session)


def verify_google_credential(credential: str) -> dict[str, Any]:
    if not settings.google_client_id:
        raise GoogleIdentityUnavailable("Google authentication is not configured")

    try:
        claims = id_token.verify_oauth2_token(
            credential,
            _google_request,
            settings.google_client_id,
        )
    except google_exceptions.TransportError as error:
        raise GoogleIdentityUnavailable(
            "Google token verification is unavailable"
        ) from error
    except (ValueError, google_exceptions.GoogleAuthError) as error:
        raise GoogleIdentityInvalid("Google token verification failed") from error

    subject = claims.get("sub")
    email = claims.get("email")
    if (
        not isinstance(subject, str)
        or not subject
        or len(subject) > 255
        or not isinstance(email, str)
        or not email
        or claims.get("email_verified") is not True
    ):
        raise GoogleIdentityInvalid("Google identity claims are incomplete")

    return dict(claims)
