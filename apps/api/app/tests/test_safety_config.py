import asyncio

import pytest

from app import main as main_module
from app.config import settings
from app.services import safety_config


@pytest.mark.parametrize(
    ("provider", "api_key", "error_setting"),
    [
        ("stub", None, "SAFETY_PROVIDER"),
        ("unknown", "test-key", "SAFETY_PROVIDER"),
        ("openai", None, "OPENAI_API_KEY"),
        ("openai", "", "OPENAI_API_KEY"),
        ("openai", "   ", "OPENAI_API_KEY"),
    ],
)
def test_production_rejects_unsafe_moderation_configuration(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    api_key: str | None,
    error_setting: str,
) -> None:
    monkeypatch.setattr(settings, "app_environment", "production")
    monkeypatch.setattr(settings, "safety_provider", provider)
    monkeypatch.setattr(settings, "openai_api_key", api_key)

    with pytest.raises(
        safety_config.SafetyConfigurationError,
        match=error_setting,
    ):
        safety_config.validate_production_configuration()


def test_production_rejects_default_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_environment", "production")
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "jwt_secret_key", "dev-secret-change-in-production")

    with pytest.raises(
        safety_config.SafetyConfigurationError,
        match="JWT_SECRET_KEY",
    ):
        safety_config.validate_production_configuration()


def test_production_rejects_http_web_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_environment", "production")
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "jwt_secret_key", "secure-random-secret")
    monkeypatch.setattr(settings, "web_origin", "http://example.com")

    with pytest.raises(
        safety_config.SafetyConfigurationError,
        match="WEB_ORIGIN",
    ):
        safety_config.validate_production_configuration()


@pytest.mark.parametrize(
    ("environment", "provider", "api_key"),
    [
        ("production", "openai", "test-key"),
        ("development", "stub", None),
    ],
)
def test_safe_production_or_development_configuration_passes(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    provider: str,
    api_key: str | None,
) -> None:
    monkeypatch.setattr(settings, "app_environment", environment)
    monkeypatch.setattr(settings, "safety_provider", provider)
    monkeypatch.setattr(settings, "openai_api_key", api_key)
    monkeypatch.setattr(settings, "jwt_secret_key", "secure-random-secret")
    monkeypatch.setattr(settings, "web_origin", "https://example.com")

    safety_config.validate_production_configuration()


def test_lifespan_validates_before_starting_background_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_environment", "production")
    monkeypatch.setattr(settings, "safety_provider", "stub")
    monkeypatch.setattr(settings, "asset_cleanup_worker_enabled", True)
    monkeypatch.setattr(
        main_module.asyncio,
        "create_task",
        lambda _coroutine: pytest.fail(
            "worker started before safety configuration validation"
        ),
    )

    async def enter_lifespan() -> None:
        async with main_module.lifespan(main_module.app):
            pytest.fail("unsafe production configuration started")

    with pytest.raises(
        safety_config.SafetyConfigurationError,
        match="SAFETY_PROVIDER",
    ):
        asyncio.run(enter_lifespan())
