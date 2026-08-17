"""Error reporting seam. Off unless SENTRY_DSN is set.

Everything the app reports goes through this module, for two reasons:

- The app must run identically with monitoring off. Every function here
  no-ops when Sentry is not configured, so dev, CI, and tests never need a
  DSN and never make network calls.
- Handled failures are invisible to auto-instrumentation. The FastAPI
  integration only sees *unhandled* exceptions, but our riskiest failures are
  deliberately handled: generation falls back to `generation_failed`, the
  narration worker swallows provider errors by design, and the cost ceiling
  only logs. Those paths call `report()` / `report_message()` explicitly so
  "gracefully degraded" stops meaning "nobody ever finds out".

The content rule: identifiers only (story id, run id, provider name), never
child names, event text, story text, photos, or audio. Sentry is a third
party; what we send it is governed by the same privacy policy as any vendor.
"""

import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)

_initialized = False


def enabled() -> bool:
    return bool(settings.sentry_dsn)


_TOKEN_RE = re.compile(r"token=[^&\s\"']+")


def _scrub(value: str) -> str:
    return _TOKEN_RE.sub("token=[redacted]", value)


def _before_send(event, _hint):
    request = event.get("request")
    if isinstance(request, dict):
        for key in ("url", "query_string"):
            if isinstance(request.get(key), str):
                request[key] = _scrub(request[key])
        headers = request.get("headers")
        if isinstance(headers, dict):
            for header in ("Referer", "referer"):
                if isinstance(headers.get(header), str):
                    headers[header] = _scrub(headers[header])
    return event


def _before_breadcrumb(crumb, _hint):
    message = crumb.get("message")
    if isinstance(message, str) and "token=" in message:
        crumb["message"] = _scrub(message)
    return crumb


def init() -> None:
    """Initialize Sentry once at startup. Safe to call when disabled.

    Never raises: a malformed DSN pasted into a secret must degrade to
    "monitoring off", not take the API down at import.
    """
    global _initialized
    if not enabled() or _initialized:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            release=settings.sentry_release or None,
            traces_sample_rate=0.0,
            include_local_variables=False,
            max_request_body_size="never",
            send_default_pii=False,
            integrations=[
                LoggingIntegration(level=logging.INFO, event_level=None)
            ],
            before_send=_before_send,
            before_breadcrumb=_before_breadcrumb,
        )
        _initialized = True
        logger.info(
            "sentry initialized (environment=%s)", settings.sentry_environment
        )
    except Exception:
        logger.exception("sentry initialization failed; monitoring disabled")


def report(exc: BaseException, **tags: str | int | None) -> None:
    """Report a handled exception with identifier tags.

    When monitoring is off this still logs so failures are not silent.
    """
    if not enabled():
        logger.warning("[unreported] %s: %s %s", type(exc).__name__, exc, tags)
        return
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            for key, value in tags.items():
                if value is not None:
                    scope.set_tag(key, str(value))
            sentry_sdk.capture_exception(exc)
    except Exception:
        logger.exception("failed to report exception to sentry")


def report_message(
    message: str, *, level: str = "warning", **tags: str | int | None
) -> None:
    """Report an event that has no exception object (e.g. cost anomalies)."""
    if not enabled():
        logger.warning("[unreported] %s %s", message, tags)
        return
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            for key, value in tags.items():
                if value is not None:
                    scope.set_tag(key, str(value))
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        logger.exception("failed to report message to sentry")
