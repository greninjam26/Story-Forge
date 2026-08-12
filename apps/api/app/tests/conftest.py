from collections.abc import Generator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, create_db_engine, get_db
from app.main import app
from app.services import flux, narration_providers, openai_moderation


@pytest.fixture(autouse=True)
def _safe_paid_provider_test_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep developer paid-provider settings and HTTP out of tests."""
    monkeypatch.setattr(settings, "image_gen_provider", "stub")
    monkeypatch.setattr(settings, "image_gen_api_key", None)
    monkeypatch.setattr(
        settings,
        "image_gen_base_url",
        "https://paid-provider.invalid/v1",
    )
    monkeypatch.setattr(settings, "tts_provider", "stub")
    monkeypatch.setattr(settings, "paid_tts_enabled", False)
    monkeypatch.setattr(settings, "safety_provider", "stub")
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(
        settings,
        "openai_moderation_model",
        "omni-moderation-latest",
    )
    monkeypatch.setattr(
        settings,
        "openai_moderation_timeout_seconds",
        10,
    )
    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(
        settings,
        "asset_cleanup_worker_enabled",
        False,
    )
    monkeypatch.setattr(settings, "elevenlabs_api_key", None)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", None)
    monkeypatch.setattr(
        settings,
        "elevenlabs_base_url",
        "https://paid-provider.invalid/v1",
    )
    monkeypatch.setattr(
        settings,
        "elevenlabs_cost_per_character_usd",
        None,
    )

    def forbid_paid_tts_provider(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "paid TTS provider access is forbidden in tests"
        )

    monkeypatch.setattr(
        narration_providers,
        "_post",
        forbid_paid_tts_provider,
    )

    def forbid_paid_image_provider(_timeout: float) -> httpx.Client:
        raise AssertionError(
            "paid image provider access is forbidden in tests"
        )

    monkeypatch.setattr(
        flux,
        "_new_http_client",
        forbid_paid_image_provider,
    )

    def forbid_openai_moderation(_timeout: float) -> httpx.Client:
        raise AssertionError(
            "OpenAI moderation access is forbidden in tests"
        )

    monkeypatch.setattr(
        openai_moderation,
        "_new_http_client",
        forbid_openai_moderation,
    )


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_db_engine("sqlite:///:memory:")
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)

    try:
        yield testing_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
