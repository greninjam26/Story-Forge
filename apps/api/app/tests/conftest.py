import os
from collections.abc import Generator
from decimal import Decimal
from threading import Event
from time import monotonic
from uuid import UUID

import httpx
import pytest
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

# The application creates its global engine during import. Force that engine to
# stay offline even when a developer's ignored .env points at a hosted database.
os.environ["DATABASE_URL"] = "sqlite://"

from app.config import settings
from app.db import Base, create_db_engine, get_db
from app.dependencies import get_current_parent
from app.main import app
from app.models import Parent
from app.services import (
    cloudflare_ai,
    cloudflare_tts,
    deepinfra_tts,
    flux,
    narration_providers,
    openai_moderation,
)
from app.tests.testing import StoryForgeTestClient


def wait_event(
    event: Event,
    timeout: float = 5.0,
    interval: float = 0.1,
) -> bool:
    """Poll *event* until set or *timeout* elapses.

    Unlike a single ``event.wait(timeout)`` this survives slow CI runners
    where the full startup → thread → provider chain can exceed 0.5 s.
    """
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if event.wait(interval):
            return True
    return False


@pytest.fixture(autouse=True)
def _safe_paid_provider_test_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep developer paid-provider settings and HTTP out of tests."""
    monkeypatch.setattr(settings, "app_environment", "development")
    monkeypatch.setattr(settings, "api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "story_provider", "stub")
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "image_gen_provider", "stub")
    monkeypatch.setattr(settings, "image_gen_api_key", None)
    monkeypatch.setattr(settings, "cloudflare_ai_account_id", None)
    monkeypatch.setattr(settings, "cloudflare_ai_api_token", None)
    monkeypatch.setattr(
        settings,
        "cloudflare_tts_model",
        "@cf/myshell-ai/melotts",
    )
    monkeypatch.setattr(settings, "cloudflare_tts_timeout_seconds", 60)
    monkeypatch.setattr(
        settings,
        "cloudflare_tts_cost_per_thousand_neurons_usd",
        0,
    )
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
    monkeypatch.setattr(
        settings,
        "story_generation_recovery_enabled",
        False,
    )
    monkeypatch.setattr(settings, "elevenlabs_api_key", None)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", None)
    monkeypatch.setattr(settings, "deepinfra_api_token", None)
    monkeypatch.setattr(
        settings,
        "deepinfra_tts_base_url",
        "https://paid-provider.invalid/v1",
    )
    monkeypatch.setattr(
        settings,
        "deepinfra_tts_model",
        "hexgrad/Kokoro-82M",
    )
    monkeypatch.setattr(settings, "deepinfra_tts_en_voice", "af_heart")
    monkeypatch.setattr(settings, "deepinfra_tts_fr_voice", "ff_siwis")
    monkeypatch.setattr(settings, "deepinfra_tts_speed", 1.0)
    monkeypatch.setattr(settings, "deepinfra_tts_timeout_seconds", 60)
    monkeypatch.setattr(
        settings,
        "deepinfra_tts_cost_per_character_usd",
        Decimal("0.00000062"),
    )
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
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_price_id", None)
    monkeypatch.setattr(settings, "stripe_webhook_secret", None)

    def forbid_paid_tts_provider(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "paid TTS provider access is forbidden in tests"
        )

    monkeypatch.setattr(
        narration_providers,
        "_post",
        forbid_paid_tts_provider,
    )
    monkeypatch.setattr(
        cloudflare_tts,
        "_post",
        forbid_paid_tts_provider,
    )
    monkeypatch.setattr(
        deepinfra_tts,
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
    monkeypatch.setattr(
        cloudflare_ai,
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
def db_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[sessionmaker[Session], None, None]:
    database_dir = tmp_path_factory.mktemp("database")
    engine = create_db_engine(f"sqlite:///{database_dir / 'test.db'}")
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
) -> Generator[StoryForgeTestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    original_story_generation_session_factory = (
        app.state.story_generation_session_factory
    )
    app.state.story_generation_session_factory = db_session_factory

    test_client = StoryForgeTestClient(app)
    test_client.db_session_factory = db_session_factory
    try:
        with test_client:
            yield test_client
    finally:
        app.state.story_generation_session_factory = (
            original_story_generation_session_factory
        )
        app.dependency_overrides.clear()


@pytest.fixture
def test_parent(
    db_session_factory: sessionmaker[Session],
) -> Parent:
    with db_session_factory() as session:
        parent = Parent(
            email="test-parent@example.com",
            locale="en",
            hashed_password="unused-in-tests",
        )
        session.add(parent)
        session.commit()
        session.refresh(parent)
        return parent


@pytest.fixture(autouse=True)
def _bypass_auth(
    db_session_factory: sessionmaker[Session],
) -> Generator[None, None, None]:
    import json
    import re

    from sqlalchemy import select

    from app.models import Child, Parent as ParentModel, Story

    _UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    def override_get_current_parent(request: Request, db: Session = Depends(get_db)):
        path = request.url.path

        match = re.search(rf"/parents/({_UUID_RE})(?:/|$)", path)
        if match:
            parent = db.get(ParentModel, UUID(match.group(1)))
            if parent is not None:
                return parent

        match = re.search(rf"/children/({_UUID_RE})(?:/|$)", path)
        if match:
            child = db.get(Child, UUID(match.group(1)))
            if child is not None:
                parent = db.get(ParentModel, child.parent_id)
                if parent is not None:
                    return parent

        match = re.search(rf"/stories/by-child/({_UUID_RE})", path)
        if match:
            child = db.get(Child, UUID(match.group(1)))
            if child is not None:
                parent = db.get(ParentModel, child.parent_id)
                if parent is not None:
                    return parent

        match = re.search(rf"/stories/({_UUID_RE})(?:/|$)", path)
        if match:
            story = db.get(Story, UUID(match.group(1)))
            if story is not None:
                child = db.get(Child, story.child_id)
                if child is not None:
                    parent = db.get(ParentModel, child.parent_id)
                    if parent is not None:
                        return parent

        if request.method == "POST" and path.rstrip("/") == "/stories":
            try:
                body = json.loads(request._body)
                child_id_str = body.get("child_id")
                if child_id_str:
                    child = db.get(Child, UUID(child_id_str))
                    if child is not None:
                        parent = db.get(ParentModel, child.parent_id)
                        if parent is not None:
                            return parent
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        parent = db.execute(
            select(ParentModel)
            .order_by(ParentModel.created_at.desc(), ParentModel.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if parent is not None:
            return parent

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No test parent found.",
        )

    app.dependency_overrides[get_current_parent] = override_get_current_parent
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_parent, None)
