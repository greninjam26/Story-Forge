"""Validate production security settings before the application starts."""

from app.config import settings


class SafetyConfigurationError(RuntimeError):
    """The selected production configuration is unsafe."""


_DEV_JWT_SECRET = "dev-secret-change-in-production"


def validate_production_configuration() -> None:
    """Reject unsafe settings before production starts."""
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
    if settings.jwt_secret_key == _DEV_JWT_SECRET:
        raise SafetyConfigurationError(
            "JWT_SECRET_KEY must be changed from the dev default in production"
        )
    if not settings.web_origin.startswith("https://"):
        raise SafetyConfigurationError(
            "WEB_ORIGIN must use HTTPS in production"
        )
    if not settings.trusted_hosts or "*" in settings.trusted_hosts:
        raise SafetyConfigurationError(
            "TRUSTED_HOSTS must restrict requests to known hosts in production"
        )
