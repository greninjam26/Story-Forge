"""Error monitoring: off by default, reports handled failures when on."""

import pytest

from app import observability
from app.config import settings


def test_disabled_by_default_and_never_imports_sentry(monkeypatch):
    """Without a DSN nothing must touch the sentry SDK at all."""
    monkeypatch.setattr(settings, "sentry_dsn", None)
    monkeypatch.setattr(observability, "enabled", lambda: False)

    observability.init()
    observability.report(RuntimeError("x"), story_id="s1")
    observability.report_message("y", run_id="r1")


def test_report_failure_never_breaks_the_caller(monkeypatch):
    """Monitoring going down must not take the app with it."""
    monkeypatch.setattr(settings, "sentry_dsn", "https://k@sentry.invalid/1")

    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("sentry sdk is broken")

    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", Exploding())
    observability.report(RuntimeError("x"))
    observability.report_message("y")


def test_init_survives_a_malformed_dsn(monkeypatch):
    """A copy-paste mangled DSN must mean 'monitoring off', not a crashloop."""
    monkeypatch.setattr(settings, "sentry_dsn", "not-a-dsn")
    monkeypatch.setattr(observability, "_initialized", False)
    observability.init()
    assert observability._initialized is False


def test_init_disables_log_event_promotion(monkeypatch):
    """logger.error must NOT mint Sentry issues."""
    import sentry_sdk

    monkeypatch.setattr(settings, "sentry_dsn", "https://k@sentry.invalid/1")
    monkeypatch.setattr(observability, "_initialized", False)
    seen = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))

    observability.init()

    integrations = seen["integrations"]
    assert len(integrations) == 1
    assert integrations[0]._handler is None
    assert integrations[0]._breadcrumb_handler.level == 20
    assert seen["before_send"] is observability._before_send
    assert seen["before_breadcrumb"] is observability._before_breadcrumb


def test_scrubbing_removes_login_tokens_everywhere():
    """Magic-link tokens must never leak into Sentry events."""
    event = {
        "request": {
            "url": "https://storyforge.app/auth/callback?token=SEKRET&x=1",
            "query_string": "token=SEKRET&x=1",
            "headers": {
                "Referer": "https://storyforge.app/auth/callback?token=SEKRET"
            },
        }
    }
    out = observability._before_send(event, None)
    blob = repr(out)
    assert "SEKRET" not in blob
    assert "token=[redacted]" in out["request"]["url"]

    crumb = {
        "message": (
            "EMAIL STUB: magic link for a@b.com: "
            "https://storyforge.app/auth/callback?token=SEKRET (dev only)"
        )
    }
    out_crumb = observability._before_breadcrumb(crumb, None)
    assert "SEKRET" not in out_crumb["message"]
