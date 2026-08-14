"""Validate that production cannot run without real moderation."""

from app.config import settings


class SafetyConfigurationError(RuntimeError):
    """The selected production safety configuration is unsafe."""


def validate_production_configuration() -> None:
    """Reject unsafe moderation settings before production starts."""
    if settings.app_environment != "production":
        return
    if settings.safety_provider != "openai":
        raise SafetyConfigurationError(
            "SAFETY_PROVIDER must be openai when "
            "APP_ENVIRONMENT=production"
        )
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise SafetyConfigurationError(
            "OPENAI_API_KEY is required when APP_ENVIRONMENT=production"
        )
