import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event, current_thread
from collections.abc import Callable, Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, create_db_engine, get_db
from app.main import app
from app.models import (
    Child,
    GenerationRun,
    GenerationRunStatus,
    GenerationStage,
    Parent,
    PendingAssetDeletion,
    Story,
    StoryIdempotencyKey,
    StoryStatus,
)
from app.schemas import StoryGenerationResult
from app.services import storage, story_jobs, story_workflow
from app.services.illustration import IllustrationGenerationError
from app.services.story_workflow import (
    StoryNotPendingReviewError,
    review_story,
)
from app.tests.conftest import wait_event
from app.tests.testing import StoryForgeTestClient


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _create_child(
    client: StoryForgeTestClient,
    *,
    language: str = "en",
    interests: str = "origami",
    email: str = "parent@example.com",
) -> dict[str, Any]:
    parent = client.create_parent(email=email)

    child_response = client.post(
        f"/parents/{parent['id']}/children",
        json={
            "name": "Camille",
            "age": 7,
            "interests": interests,
            "language": language,
        },
    )
    assert child_response.status_code == 201
    return child_response.json()


def _create_story(
    client: TestClient,
    child_id: str,
    event_text: str,
) -> dict[str, Any]:
    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": event_text},
    )
    assert response.status_code == 201
    return response.json()


def test_create_story_persists_generated_story_and_pages(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "  Camille helped make dinner.  ",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] is not None
    assert body["child_id"] == child["id"]
    assert body["title"] == "Camille and the Gentle Star"
    assert body["language"] == "en"
    assert body["status"] == "pending_review"
    assert body["failure_reason"] is None
    assert body["approved_at"] is None
    assert len(body["pages"]) == 10
    assert [page["page_number"] for page in body["pages"]] == list(
        range(1, 11)
    )
    assert all(page["id"] is not None for page in body["pages"])
    assert all(page["text"] for page in body["pages"])
    assert any("origami" in page["text"] for page in body["pages"])
    assert [page["image_url"] for page in body["pages"]] == [
        (
            "https://picsum.photos/seed/"
            f"{child['id']}-{page_number}/640/480"
        )
        for page_number in range(1, 11)
    ]
    assert all(page["audio_url"] for page in body["pages"])

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille helped make dinner."
        assert [page.page_number for page in stored_story.pages] == list(
            range(1, 11)
        )
        assert [page.image_url for page in stored_story.pages] == [
            page["image_url"] for page in body["pages"]
        ]
        assert [page.audio_url for page in stored_story.pages] == [
            page["audio_url"] for page in body["pages"]
        ]


@pytest.mark.parametrize(
    ("setting_name", "provider_name"),
    [
        ("story_provider", "claude"),
        ("safety_provider", "openai"),
        ("image_gen_provider", "flux"),
        ("tts_provider", "elevenlabs"),
    ],
)
def test_create_story_returns_generating_story_before_production_work(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    setting_name: str,
    provider_name: str,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, setting_name, provider_name)
    if provider_name == "claude":
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    if provider_name == "openai":
        monkeypatch.setattr(settings, "openai_api_key", "test-key")
    if provider_name == "flux":
        with db_session_factory() as db:
            stored_child = db.get(Child, UUID(child["id"]))
            assert stored_child is not None
            stored_child.reference_photo_ref = (
                "local://references/child.webp"
            )
            db.commit()
        monkeypatch.setattr(settings, "image_gen_api_key", "test-key")
    if provider_name == "elevenlabs":
        monkeypatch.setattr(settings, "paid_tts_enabled", True)
        monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key")
        monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice-test")
    notifications: list[UUID] = []
    monkeypatch.setattr(
        client.app.state,
        "notify_story_generation",
        notifications.append,
    )

    def forbid_inline_generation(**_: object) -> None:
        raise AssertionError("provider work ran inside the request")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        forbid_inline_generation,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == StoryStatus.GENERATING.value
    assert body["title"] == ""
    assert body["pages"] == []
    assert notifications == [UUID(body["id"])]
    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.status is StoryStatus.GENERATING


def test_create_story_schedules_production_work_with_a_fresh_session(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        client.app.state,
        "story_generation_session_factory",
        db_session_factory,
    )

    def generate_test_story(**_: object) -> StoryGenerationResult:
        return StoryGenerationResult(
            title="Camille's Bright Evening",
            pages=[f"Gentle page {number}." for number in range(1, 11)],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_test_story,
    )
    with db_session_factory() as db:
        older_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="An older queued event.",
        )
        older_story_id = older_story.id

    worker_finished = Event()
    original_process = story_workflow.process_queued_story

    def process_notified_story(
        session_factory: sessionmaker[Session],
        story_id: UUID | None = None,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        try:
            return original_process(
                session_factory,
                story_id,
                should_stop=should_stop,
            )
        finally:
            worker_finished.set()

    monkeypatch.setattr(
        story_workflow,
        "process_queued_story",
        process_notified_story,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == StoryStatus.GENERATING.value
    assert worker_finished.wait(timeout=5.0)
    with db_session_factory() as db:
        completed_story = db.get(Story, UUID(body["id"]))
        untouched_story = db.get(Story, older_story_id)
        assert completed_story is not None
        assert untouched_story is not None
        assert completed_story.status is StoryStatus.PENDING_REVIEW
        assert completed_story.title == "Camille's Bright Evening"
        assert untouched_story.status is StoryStatus.GENERATING
        assert untouched_story.generation_attempts == 0


def test_notified_claim_failure_does_not_stop_later_generation(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    first_attempted = Event()
    second_finished = Event()
    original_process = story_workflow.process_queued_story
    notification_count = 0

    def fail_first_notification(
        session_factory: sessionmaker[Session],
        story_id: UUID | None = None,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        nonlocal notification_count
        notification_count += 1
        if notification_count == 1:
            first_attempted.set()
            raise RuntimeError("claim failed")
        try:
            return original_process(
                session_factory,
                story_id,
                should_stop=should_stop,
            )
        finally:
            second_finished.set()

    monkeypatch.setattr(
        story_workflow,
        "process_queued_story",
        fail_first_notification,
    )
    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        lambda **_: StoryGenerationResult(
            title="Second notification",
            pages=[f"Page {number}." for number in range(1, 11)],
        ),
    )

    first_response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "First notification.",
        },
    )
    assert first_response.status_code == 201
    assert first_attempted.wait(timeout=5.0)

    second_response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Second notification.",
        },
    )
    assert second_response.status_code == 201
    assert second_finished.wait(timeout=5.0)

    with db_session_factory() as db:
        first_story = db.get(Story, UUID(first_response.json()["id"]))
        second_story = db.get(Story, UUID(second_response.json()["id"]))
        assert first_story is not None
        assert second_story is not None
        assert first_story.status is StoryStatus.GENERATING
        assert first_story.generation_attempts == 0
        assert second_story.status is StoryStatus.PENDING_REVIEW


def test_create_story_rejects_unconfigured_claude_before_queueing(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "story_provider_not_configured"}
    with db_session_factory() as db:
        assert db.scalar(select(Story)) is None
        assert db.scalar(select(GenerationRun)) is None


@pytest.mark.parametrize(
    ("paid_calls_enabled", "api_key", "voice_id"),
    [
        (False, "test-key", "voice-test"),
        (True, None, "voice-test"),
        (True, "test-key", None),
    ],
)
def test_create_story_rejects_unconfigured_elevenlabs_before_queueing(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    paid_calls_enabled: bool,
    api_key: str | None,
    voice_id: str | None,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "tts_provider", "elevenlabs")
    monkeypatch.setattr(settings, "paid_tts_enabled", paid_calls_enabled)
    monkeypatch.setattr(settings, "elevenlabs_api_key", api_key)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", voice_id)

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "narration_provider_not_configured"
    }
    with db_session_factory() as db:
        assert db.scalar(select(Story)) is None
        assert db.scalar(select(GenerationRun)) is None


def test_queued_story_revalidates_configuration_before_provider_work(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    monkeypatch.setattr(settings, "anthropic_api_key", None)

    def forbid_provider_work(**_: object) -> None:
        raise AssertionError("provider work must not start")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        forbid_provider_work,
    )

    story_workflow.process_queued_story(db_session_factory, story_id)

    with db_session_factory() as db:
        queued_story = db.get(Story, story_id)
        assert queued_story is not None
        assert queued_story.status is StoryStatus.GENERATING
        assert queued_story.failure_reason is None
        assert queued_story.generation_claim_token is not None
        assert queued_story.generation_claimed_at is not None
        assert queued_story.generation_attempts == 1
        assert db.scalar(select(GenerationRun)) is None


def test_queued_story_worker_completes_the_existing_story(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    story_workflow.process_queued_story(db_session_factory, story_id)

    with db_session_factory() as db:
        stories = list(db.scalars(select(Story)))
        assert len(stories) == 1
        completed_story = stories[0]
        assert completed_story.id == story_id
        assert completed_story.status is StoryStatus.PENDING_REVIEW
        assert completed_story.title == "Camille and the Gentle Star"
        assert len(completed_story.pages) == 10
        assert completed_story.generation_attempts == 1
        assert completed_story.generation_claim_token is None
        assert completed_story.generation_claimed_at is None
        assert completed_story.generation_stage is GenerationStage.COMPLETE


def test_queued_story_worker_retains_unhandled_failure_for_retry(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    def fail_safety_check(_text: str) -> None:
        raise RuntimeError("private provider details")

    monkeypatch.setattr(story_workflow, "check_text", fail_safety_check)

    with caplog.at_level(logging.ERROR):
        story_workflow.process_queued_story(db_session_factory, story_id)

    with db_session_factory() as db:
        queued_story = db.get(Story, story_id)
        assert queued_story is not None
        assert queued_story.status is StoryStatus.GENERATING
        assert queued_story.failure_reason is None
        assert queued_story.generation_claim_token is not None
        assert queued_story.generation_claimed_at is not None
        assert queued_story.generation_attempts == 1
    assert "private provider details" not in caplog.text


def test_immediate_background_worker_observes_lifespan_shutdown(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as db:
            yield db

    original_session_factory = app.state.story_generation_session_factory
    original_override = app.dependency_overrides.get(get_db)
    app.state.story_generation_session_factory = db_session_factory
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    provider_started = Event()
    stop_observed = Event()

    def generate_until_shutdown(**_: object) -> StoryGenerationResult:
        provider_started.set()
        assert app.state.generation_worker_stop.wait(timeout=5.0)
        stop_observed.set()
        return StoryGenerationResult(
            title="Stopped story",
            pages=[f"Page {number}." for number in range(1, 11)],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_until_shutdown,
    )

    local_client = StoryForgeTestClient(app)
    local_client.db_session_factory = db_session_factory
    try:
        with local_client:
            child = _create_child(local_client)
            response = local_client.post(
                "/stories",
                json={
                    "child_id": child["id"],
                    "event_text": "Camille helped make dinner.",
                },
            )
            assert response.status_code == 201
            story_id = UUID(response.json()["id"])
            assert provider_started.wait(timeout=5.0)

        assert stop_observed.is_set()
        with db_session_factory() as db:
            story = db.get(Story, story_id)
            run = db.scalar(select(GenerationRun))
            assert story is not None
            assert story.status is StoryStatus.GENERATING
            assert story.generation_claim_token is not None
            assert run is not None
            assert run.status is GenerationRunStatus.FAILED
    finally:
        app.state.story_generation_session_factory = (
            original_session_factory
        )
        if original_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_override


def test_pending_story_worker_recovers_a_stale_claim(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id
        queued_story.generation_claim_token = uuid4()
        queued_story.generation_claimed_at = (
            datetime.now(timezone.utc) - timedelta(minutes=16)
        )
        queued_story.generation_attempts = 1
        db.commit()

    handled = story_workflow.process_pending_stories(
        db_session_factory,
        limit=1,
    )

    assert handled == 1
    with db_session_factory() as db:
        recovered_story = db.get(Story, story_id)
        assert recovered_story is not None
        assert recovered_story.status is StoryStatus.PENDING_REVIEW
        assert recovered_story.generation_attempts == 2
        assert recovered_story.generation_claim_token is None
        assert recovered_story.generation_claimed_at is None
        assert recovered_story.generation_stage is GenerationStage.COMPLETE


def test_reclaimed_story_rejects_the_stale_workers_output(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    replacement_token: UUID | None = None

    def generate_after_reclaim(**_: object) -> StoryGenerationResult:
        nonlocal replacement_token
        now = datetime.now(timezone.utc)
        with db_session_factory() as other_db:
            active_story = other_db.get(Story, story_id)
            assert active_story is not None
            active_story.generation_claimed_at = now - timedelta(minutes=16)
            other_db.commit()
            reclaimed = story_jobs.claim_story(
                other_db,
                story_id=story_id,
                now=now,
            )
            assert reclaimed is not None
            replacement_token = reclaimed.generation_claim_token
        return StoryGenerationResult(
            title="Stale worker title",
            pages=[f"Stale page {number}." for number in range(1, 11)],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_after_reclaim,
    )

    story_workflow.process_queued_story(db_session_factory, story_id)

    assert replacement_token is not None
    with db_session_factory() as db:
        story = db.get(Story, story_id)
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert story.status is StoryStatus.GENERATING
        assert story.title == ""
        assert story.pages == []
        assert story.generation_claim_token == replacement_token
        assert story.generation_attempts == 2
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED


def test_terminal_story_commit_clears_its_claim(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    story_workflow.process_queued_story(db_session_factory, story_id)

    with db_session_factory() as db:
        story = db.get(Story, story_id)
        assert story is not None
        assert story.status is StoryStatus.PENDING_REVIEW
        assert story.generation_claim_token is None
        assert story.generation_claimed_at is None
        assert story.generation_stage is GenerationStage.COMPLETE


def test_stopping_worker_retains_claim_after_the_current_provider_call(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    stopping = False

    def generate_then_stop(**_: object) -> StoryGenerationResult:
        nonlocal stopping
        stopping = True
        return StoryGenerationResult(
            title="Worker stopping",
            pages=[f"Page {number}." for number in range(1, 11)],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_then_stop,
    )
    monkeypatch.setattr(
        story_workflow.safety,
        "check_story",
        lambda *_args, **_kwargs: pytest.fail(
            "moderation must not start after shutdown"
        ),
    )

    story_workflow.process_queued_story(
        db_session_factory,
        story_id,
        should_stop=lambda: stopping,
    )

    with db_session_factory() as db:
        story = db.get(Story, story_id)
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert story.status is StoryStatus.GENERATING
        assert story.generation_claim_token is not None
        assert story.generation_claimed_at is not None
        assert story.generation_attempts == 1
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED


def test_claim_heartbeat_renews_during_a_provider_call(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    heartbeat_seen = Event()
    original_renew = story_jobs.renew_claim

    def observe_renewal(
        db: Session,
        *,
        story_id: UUID,
        claim_token: UUID,
        now: datetime | None = None,
    ) -> None:
        original_renew(
            db,
            story_id=story_id,
            claim_token=claim_token,
            now=now,
        )
        if current_thread().name == "story-claim-heartbeat":
            heartbeat_seen.set()

    def generate_after_heartbeat(**_: object) -> StoryGenerationResult:
        assert heartbeat_seen.wait(timeout=5.0)
        return StoryGenerationResult(
            title="Heartbeat story",
            pages=[f"Page {number}." for number in range(1, 11)],
        )

    monkeypatch.setattr(
        story_jobs,
        "STORY_CLAIM_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    monkeypatch.setattr(story_jobs, "renew_claim", observe_renewal)
    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_after_heartbeat,
    )

    story_workflow.process_queued_story(db_session_factory, story_id)

    assert heartbeat_seen.is_set()
    with db_session_factory() as db:
        story = db.get(Story, story_id)
        assert story is not None
        assert story.status is StoryStatus.PENDING_REVIEW


def test_terminal_failure_does_not_wait_forever_for_a_blocked_heartbeat(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    heartbeat_blocked = Event()
    release_heartbeat = Event()
    heartbeat_finished = Event()
    original_renew = story_jobs.renew_claim
    original_finalize = story_workflow.RunCostRecorder.finalize

    def block_heartbeat_renewal(
        db: Session,
        *,
        story_id: UUID,
        claim_token: UUID,
        now: datetime | None = None,
    ) -> None:
        if current_thread().name == "story-claim-heartbeat":
            heartbeat_blocked.set()
            assert release_heartbeat.wait(timeout=5.0)
        original_renew(
            db,
            story_id=story_id,
            claim_token=claim_token,
            now=now,
        )
        if current_thread().name == "story-claim-heartbeat":
            heartbeat_finished.set()

    def generate_while_heartbeat_is_blocked(
        **_: object,
    ) -> StoryGenerationResult:
        assert heartbeat_blocked.wait(timeout=5.0)
        return StoryGenerationResult(
            title="Terminal failure",
            pages=[f"Page {number}." for number in range(1, 11)],
        )

    def fail_successful_finalization(
        recorder: story_workflow.RunCostRecorder,
        *,
        status: GenerationRunStatus,
        **kwargs: object,
    ) -> None:
        if status is GenerationRunStatus.SUCCEEDED:
            raise RuntimeError("terminal write failed")
        original_finalize(recorder, status=status, **kwargs)

    monkeypatch.setattr(
        story_jobs,
        "STORY_CLAIM_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        story_jobs,
        "STORY_CLAIM_HEARTBEAT_JOIN_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(story_jobs, "renew_claim", block_heartbeat_renewal)
    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_while_heartbeat_is_blocked,
    )
    monkeypatch.setattr(
        story_workflow.RunCostRecorder,
        "finalize",
        fail_successful_finalization,
    )

    try:
        story_workflow.process_queued_story(db_session_factory, story_id)
    finally:
        release_heartbeat.set()

    assert heartbeat_finished.wait(timeout=5.0)
    with db_session_factory() as db:
        story = db.get(Story, story_id)
        assert story is not None
        assert story.status is StoryStatus.GENERATING
        assert story.generation_claim_token is not None
        assert story.title == "Terminal failure"
        assert len(story.pages) == 10
        assert all(page.image_url is not None for page in story.pages)
        assert all(page.audio_url is not None for page in story.pages)
        assert story.generation_stage is GenerationStage.NARRATION


def test_queued_story_resumes_illustrations_after_worker_stop(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    illustration_calls = 0
    original_illustration = story_workflow.generate_illustration
    original_story = story_workflow.generate_story

    def count_illustration(**kwargs: object) -> str:
        nonlocal illustration_calls
        illustration_calls += 1
        return original_illustration(**kwargs)

    def stop_after_three_illustrations() -> bool:
        return illustration_calls >= 3

    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        count_illustration,
    )

    story_workflow.process_queued_story(
        db_session_factory,
        story_id,
        should_stop=stop_after_three_illustrations,
    )

    with db_session_factory() as db:
        stopped_story = db.get(Story, story_id)
        assert stopped_story is not None
        assert stopped_story.status is StoryStatus.GENERATING
        assert stopped_story.generation_claim_token is not None
        assert stopped_story.generation_attempts == 1
        assert (
            stopped_story.generation_stage is GenerationStage.ILLUSTRATIONS
        )
        assert stopped_story.title == "Camille and the Gentle Star"
        assert len(stopped_story.pages) == 10
        assert (
            sum(page.image_url is not None for page in stopped_story.pages)
            == 3
        )
        assert all(
            page.audio_url is None for page in stopped_story.pages
        )
        stopped_story.generation_claimed_at = (
            datetime.now(timezone.utc) - timedelta(minutes=16)
        )
        db.commit()

    illustration_calls = 0
    story_calls = 0

    def count_story(**kwargs: object) -> StoryGenerationResult:
        nonlocal story_calls
        story_calls += 1
        return original_story(**kwargs)

    monkeypatch.setattr(story_workflow, "generate_story", count_story)

    story_workflow.process_queued_story(db_session_factory, story_id)

    assert story_calls == 0
    assert illustration_calls == 7
    with db_session_factory() as db:
        recovered_story = db.get(Story, story_id)
        assert recovered_story is not None
        assert recovered_story.status is StoryStatus.PENDING_REVIEW
        assert recovered_story.generation_attempts == 2
        assert (
            recovered_story.generation_stage is GenerationStage.COMPLETE
        )
        assert recovered_story.title == "Camille and the Gentle Star"
        assert len(recovered_story.pages) == 10
        assert all(
            page.image_url is not None for page in recovered_story.pages
        )
        assert all(
            page.audio_url is not None for page in recovered_story.pages
        )


def test_queued_story_resumes_narration_after_worker_stop(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    narration_calls = 0
    original_narration = story_workflow.generate_narration

    def count_narration(**kwargs: object) -> str:
        nonlocal narration_calls
        narration_calls += 1
        return original_narration(**kwargs)

    def stop_after_two_narrations() -> bool:
        return narration_calls >= 2

    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        count_narration,
    )

    story_workflow.process_queued_story(
        db_session_factory,
        story_id,
        should_stop=stop_after_two_narrations,
    )

    with db_session_factory() as db:
        stopped_story = db.get(Story, story_id)
        assert stopped_story is not None
        assert stopped_story.status is StoryStatus.GENERATING
        assert stopped_story.generation_claim_token is not None
        assert stopped_story.generation_attempts == 1
        assert stopped_story.generation_stage is GenerationStage.NARRATION
        assert stopped_story.title == "Camille and the Gentle Star"
        assert len(stopped_story.pages) == 10
        assert all(
            page.image_url is not None for page in stopped_story.pages
        )
        assert (
            sum(page.audio_url is not None for page in stopped_story.pages)
            == 2
        )
        stopped_story.generation_claimed_at = (
            datetime.now(timezone.utc) - timedelta(minutes=16)
        )
        db.commit()

    narration_calls = 0
    story_calls = 0
    illustration_calls = 0
    original_story = story_workflow.generate_story
    original_illustration = story_workflow.generate_illustration

    def count_story(**kwargs: object) -> StoryGenerationResult:
        nonlocal story_calls
        story_calls += 1
        return original_story(**kwargs)

    def count_illustration(**kwargs: object) -> str:
        nonlocal illustration_calls
        illustration_calls += 1
        return original_illustration(**kwargs)

    monkeypatch.setattr(story_workflow, "generate_story", count_story)
    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        count_illustration,
    )

    story_workflow.process_queued_story(db_session_factory, story_id)

    assert story_calls == 0
    assert illustration_calls == 0
    assert narration_calls == 8
    with db_session_factory() as db:
        recovered_story = db.get(Story, story_id)
        assert recovered_story is not None
        assert recovered_story.status is StoryStatus.PENDING_REVIEW
        assert (
            recovered_story.generation_stage is GenerationStage.COMPLETE
        )
        assert len(recovered_story.pages) == 10
        assert all(
            page.image_url is not None for page in recovered_story.pages
        )
        assert all(
            page.audio_url is not None for page in recovered_story.pages
        )


def test_queued_story_retains_partial_pages_after_narration_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    def fail_narration(**_: object) -> str:
        raise RuntimeError("narration provider failed")

    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        fail_narration,
    )

    story_workflow.process_queued_story(db_session_factory, story_id)

    with db_session_factory() as db:
        failed_story = db.get(Story, story_id)
        assert failed_story is not None
        assert failed_story.status is StoryStatus.GENERATION_FAILED
        assert failed_story.failure_reason == "narration_generation_failed"
        assert failed_story.generation_claim_token is None
        assert failed_story.generation_claimed_at is None
        assert failed_story.title == "Camille and the Gentle Star"
        assert len(failed_story.pages) == 10
        assert all(
            page.image_url is not None for page in failed_story.pages
        )
        assert all(
            page.audio_url is None for page in failed_story.pages
        )


def test_story_api_exposes_generation_stage(client: TestClient) -> None:
    child = _create_child(client)

    create_response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["generation_stage"] == "complete"
    detail = client.get(f"/stories/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["generation_stage"] == "complete"


def test_api_worker_recovers_stale_story_on_startup(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_session_factory() as db:
        parent = Parent(email="recovery@example.com")
        child = Child(name="Camille", age=7)
        story = Story(
            event_text="Camille helped make dinner.",
            language="en",
            generation_claim_token=uuid4(),
            generation_claimed_at=(
                datetime.now(timezone.utc) - timedelta(minutes=16)
            ),
            generation_attempts=1,
        )
        child.stories.append(story)
        parent.children.append(child)
        db.add(parent)
        db.commit()
        story_id = story.id

    monkeypatch.setattr(
        app.state,
        "story_generation_session_factory",
        db_session_factory,
    )
    monkeypatch.setattr(
        settings,
        "story_generation_worker_enabled",
        True,
    )
    monkeypatch.setattr(
        settings,
        "story_generation_worker_interval_seconds",
        60,
    )
    worker_finished = Event()
    original_process = story_workflow.try_process_pending_stories

    def process_pending(
        session_factory: sessionmaker[Session],
        *,
        limit: int = 1,
        should_stop: Callable[[], bool] | None = None,
    ) -> int:
        try:
            return original_process(
                session_factory,
                limit=limit,
                should_stop=should_stop,
            )
        finally:
            worker_finished.set()

    monkeypatch.setattr(
        story_workflow,
        "try_process_pending_stories",
        process_pending,
    )

    with TestClient(app):
        assert worker_finished.wait(timeout=5.0)

    with db_session_factory() as db:
        recovered_story = db.get(Story, story_id)
        assert recovered_story is not None
        assert recovered_story.status is StoryStatus.PENDING_REVIEW
        assert recovered_story.generation_attempts == 2


def test_notified_story_takes_priority_between_recovery_jobs(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as db:
            yield db

    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        settings,
        "story_generation_worker_enabled",
        True,
    )
    monkeypatch.setattr(
        settings,
        "story_generation_worker_interval_seconds",
        60,
    )
    with db_session_factory() as db:
        parent = Parent(email="priority@example.com")
        child = Child(name="Camille", age=7)
        parent.children.append(child)
        db.add(parent)
        db.commit()
        child_id = child.id
        older_story = story_workflow.queue_story(
            db=db,
            child_id=child_id,
            event_text="Oldest recovery story.",
        )
        waiting_story = story_workflow.queue_story(
            db=db,
            child_id=child_id,
            event_text="Second recovery story.",
        )
        older_story_id = older_story.id
        waiting_story_id = waiting_story.id

    provider_started = Event()
    release_provider = Event()
    exact_finished = Event()
    generated_events: list[str] = []
    notified_story_id: UUID | None = None
    original_process = story_workflow.process_queued_story

    def generate_in_order(
        *,
        event_text: str,
        **_: object,
    ) -> StoryGenerationResult:
        generated_events.append(event_text)
        if len(generated_events) == 1:
            provider_started.set()
            assert release_provider.wait(timeout=2)
        return StoryGenerationResult(
            title=event_text,
            pages=[f"Page {number}." for number in range(1, 11)],
        )

    def observe_processing(
        session_factory: sessionmaker[Session],
        story_id: UUID | None = None,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        try:
            return original_process(
                session_factory,
                story_id,
                should_stop=should_stop,
            )
        finally:
            if story_id is not None and story_id == notified_story_id:
                exact_finished.set()

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_in_order,
    )
    monkeypatch.setattr(
        story_workflow,
        "process_queued_story",
        observe_processing,
    )
    original_session_factory = app.state.story_generation_session_factory
    original_override = app.dependency_overrides.get(get_db)
    app.state.story_generation_session_factory = db_session_factory
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as local_client:
            assert provider_started.wait(timeout=5.0)
            response = local_client.post(
                "/stories",
                json={
                    "child_id": str(child_id),
                    "event_text": "Newly notified story.",
                },
            )
            assert response.status_code == 201
            notified_story_id = UUID(response.json()["id"])
            release_provider.set()
            assert exact_finished.wait(timeout=2)

            with db_session_factory() as db:
                recovered_story = db.get(Story, older_story_id)
                untouched_story = db.get(Story, waiting_story_id)
                notified_story = db.get(Story, notified_story_id)
                assert recovered_story is not None
                assert untouched_story is not None
                assert notified_story is not None
                assert recovered_story.status is StoryStatus.PENDING_REVIEW
                assert notified_story.status is StoryStatus.PENDING_REVIEW
                assert untouched_story.status is StoryStatus.GENERATING
                assert untouched_story.generation_attempts == 0
            assert generated_events[:2] == [
                "Oldest recovery story.",
                "Newly notified story.",
            ]
    finally:
        release_provider.set()
        app.state.story_generation_session_factory = (
            original_session_factory
        )
        if original_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_override


def test_periodic_recovery_runs_during_sustained_notifications(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "story_generation_worker_enabled",
        True,
    )
    monkeypatch.setattr(
        settings,
        "story_generation_worker_interval_seconds",
        0.2,
    )
    with db_session_factory() as db:
        parent = Parent(email="deadline@example.com")
        child = Child(name="Camille", age=7)
        parent.children.append(child)
        db.add(parent)
        db.commit()
        child_id = child.id

    startup_finished = Event()
    first_exact_started = Event()
    release_first_exact = Event()
    recovery_finished = Event()
    processing_order: list[str] = []
    first_exact_id: UUID | None = None
    original_process = story_workflow.process_queued_story

    def observe_processing(
        session_factory: sessionmaker[Session],
        story_id: UUID | None = None,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        is_startup = story_id is None and not startup_finished.is_set()
        if not is_startup:
            processing_order.append(
                "recovery" if story_id is None else f"exact:{story_id}"
            )
        if story_id is not None and story_id == first_exact_id:
            first_exact_started.set()
            assert release_first_exact.wait(timeout=2)
        try:
            return original_process(
                session_factory,
                story_id,
                should_stop=should_stop,
            )
        finally:
            if is_startup:
                startup_finished.set()
            elif story_id is None:
                recovery_finished.set()

    monkeypatch.setattr(
        story_workflow,
        "process_queued_story",
        observe_processing,
    )
    original_session_factory = app.state.story_generation_session_factory
    app.state.story_generation_session_factory = db_session_factory

    try:
        with TestClient(app):
            assert startup_finished.wait(timeout=5.0)
            with db_session_factory() as db:
                first_exact = story_workflow.queue_story(
                    db=db,
                    child_id=child_id,
                    event_text="First exact story.",
                )
                first_exact_id = first_exact.id
            app.state.notify_story_generation(first_exact_id)
            assert first_exact_started.wait(timeout=5.0)

            with db_session_factory() as db:
                story_workflow.queue_story(
                    db=db,
                    child_id=child_id,
                    event_text="Recovery story.",
                )
                second_exact = story_workflow.queue_story(
                    db=db,
                    child_id=child_id,
                    event_text="Second exact story.",
                )
            app.state.notify_story_generation(second_exact.id)

            assert not release_first_exact.wait(timeout=2.5)
            release_first_exact.set()
            assert recovery_finished.wait(timeout=2)
            assert processing_order[:2] == [
                f"exact:{first_exact_id}",
                "recovery",
            ]
    finally:
        release_first_exact.set()
        app.state.story_generation_session_factory = (
            original_session_factory
        )


@pytest.mark.parametrize(
    ("failed_stage", "failure_reason"),
    [
        ("generate_story", "story_generation_failed"),
        ("generate_illustration", "illustration_generation_failed"),
        ("generate_narration", "narration_generation_failed"),
    ],
)
def test_queued_story_preserves_failure_when_cost_finalization_fails(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failed_stage: str,
    failure_reason: str,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    def fail_provider_stage(**_: object) -> None:
        raise RuntimeError("provider failed")

    def fail_cost_finalization(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cost finalization failed")

    monkeypatch.setattr(
        story_workflow,
        failed_stage,
        fail_provider_stage,
    )
    monkeypatch.setattr(
        story_workflow.RunCostRecorder,
        "finalize",
        fail_cost_finalization,
    )

    story_workflow.process_queued_story(db_session_factory, story_id)

    with db_session_factory() as db:
        failed_story = db.get(Story, story_id)
        assert failed_story is not None
        assert failed_story.status is StoryStatus.GENERATION_FAILED
        assert failed_story.failure_reason == failure_reason
        assert failed_story.generation_claim_token is None
        assert failed_story.generation_claimed_at is None


def test_queued_story_keeps_terminal_status_after_refresh_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        queued_story = story_workflow.queue_story(
            db=db,
            child_id=UUID(child["id"]),
            event_text="Camille helped make dinner.",
        )
        story_id = queued_story.id

    original_refresh = db_session_factory.class_.refresh

    def fail_terminal_story_refresh(
        db: Session,
        row: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        if isinstance(row, Story) and row.status is StoryStatus.PENDING_REVIEW:
            raise RuntimeError("private post-commit details")
        original_refresh(db, row, *args, **kwargs)

    monkeypatch.setattr(
        db_session_factory.class_,
        "refresh",
        fail_terminal_story_refresh,
    )

    with caplog.at_level(logging.ERROR):
        story_workflow.process_queued_story(db_session_factory, story_id)

    with db_session_factory() as db:
        completed_story = db.get(Story, story_id)
        assert completed_story is not None
        assert completed_story.status is StoryStatus.PENDING_REVIEW
    assert "Background story generation failed" not in caplog.text
    assert "private post-commit details" not in caplog.text


def test_create_story_passes_child_reference_photo_to_illustrations(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    reference = "local://references/child.webp"
    with db_session_factory() as db:
        stored_child = db.get(Child, UUID(child["id"]))
        assert stored_child is not None
        stored_child.reference_photo_ref = reference
        db.commit()

    received_references: list[str | None] = []

    def generate_test_illustration(
        *,
        reference_photo_ref: str | None,
        page_number: int,
        **_: object,
    ) -> str:
        received_references.append(reference_photo_ref)
        return f"local://illustrations/page-{page_number}.webp"

    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        generate_test_illustration,
    )

    story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )

    assert story["status"] == StoryStatus.PENDING_REVIEW.value
    assert received_references == [reference] * 10


def test_create_story_requires_reference_photo_before_generation(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "image_gen_provider", "flux")
    monkeypatch.setattr(settings, "image_gen_api_key", "test-key")

    def fail_story_generation(**_: object) -> None:
        raise AssertionError("story generation must not start")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_story_generation,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "add a reference photo before generating illustrations"
    }
    with db_session_factory() as db:
        assert list(db.scalars(select(GenerationRun))) == []


@pytest.mark.parametrize("api_key", [None, "  "])
def test_create_story_requires_flux_configuration_before_generation(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        stored_child = db.get(Child, UUID(child["id"]))
        assert stored_child is not None
        stored_child.reference_photo_ref = (
            "local://references/child.webp"
        )
        db.commit()
    monkeypatch.setattr(settings, "image_gen_provider", "flux")
    monkeypatch.setattr(settings, "image_gen_api_key", api_key)

    def fail_story_generation(**_: object) -> None:
        raise AssertionError("story generation must not start")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_story_generation,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "illustration_provider_not_configured"
    }
    with db_session_factory() as db:
        assert list(db.scalars(select(GenerationRun))) == []


def test_background_queue_rejects_unknown_illustration_provider(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "image_gen_provider", "unknown")

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "illustration_provider_not_configured"
    }
    with db_session_factory() as db:
        assert db.scalar(select(Story)) is None
        assert db.scalar(select(GenerationRun)) is None


def test_create_story_cleans_up_partial_generated_illustrations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    created_reference = (
        "local://illustrations/"
        "11111111111111111111111111111111.webp"
    )
    deleted_references: list[str] = []

    def generate_test_illustration(*, page_number: int, **_: object) -> str:
        if page_number == 2:
            raise RuntimeError("provider unavailable")
        return created_reference

    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        generate_test_illustration,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        deleted_references.append,
    )

    story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )

    assert story["status"] == StoryStatus.GENERATION_FAILED.value
    assert deleted_references == [created_reference]


def test_create_story_retains_failed_illustration_cleanup_for_retry(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    created_reference = (
        "local://illustrations/"
        "11111111111111111111111111111111.webp"
    )

    def generate_test_illustration(*, page_number: int, **_: object) -> str:
        if page_number == 2:
            raise RuntimeError("provider unavailable")
        return created_reference

    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        generate_test_illustration,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda _reference: (_ for _ in ()).throw(
            OSError("cleanup unavailable")
        ),
    )

    story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )

    assert story["status"] == StoryStatus.GENERATION_FAILED.value
    with db_session_factory() as db:
        pending = db.scalar(select(PendingAssetDeletion))
        assert pending is not None
        assert pending.reference == created_reference
        assert pending.attempts == 1


def test_create_story_cleans_up_image_when_cost_update_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    created_reference = (
        "local://illustrations/"
        "11111111111111111111111111111111.webp"
    )
    deleted_references: list[str] = []

    def fail_after_storage(**_kwargs: object) -> str:
        raise IllustrationGenerationError(
            "illustration_cost_tracking_failed",
            "The generated illustration could not be finalized.",
            created_reference=created_reference,
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        fail_after_storage,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        deleted_references.append,
    )

    story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )

    assert story["status"] == StoryStatus.GENERATION_FAILED.value
    assert deleted_references == [created_reference]


def test_create_story_cleans_up_illustrations_when_finalization_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    created_reference = (
        "local://illustrations/"
        "11111111111111111111111111111111.webp"
    )
    deleted_references: list[str] = []
    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        lambda **_kwargs: created_reference,
    )

    def fail_finalization(
        _recorder: object,
        **_: object,
    ) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        story_workflow.RunCostRecorder,
        "finalize",
        fail_finalization,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        deleted_references.append,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/stories",
            json={
                "child_id": child["id"],
                "event_text": "Camille helped make dinner.",
            },
        )

    assert deleted_references == [created_reference]


def test_create_story_retains_created_audio_when_later_narration_fails(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    created_reference = (
        "r2://narration/"
        "11111111111111111111111111111111.mp3"
    )
    narration_calls = 0

    def generate_test_narration(**_: object) -> str:
        nonlocal narration_calls
        narration_calls += 1
        if narration_calls == 2:
            raise RuntimeError("provider unavailable")
        return created_reference

    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        generate_test_narration,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda _reference: (_ for _ in ()).throw(
            OSError("cleanup unavailable")
        ),
    )

    story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )

    assert story["status"] == StoryStatus.GENERATION_FAILED.value
    with db_session_factory() as db:
        pending = db.scalar(select(PendingAssetDeletion))
        assert pending is not None
        assert pending.reference == created_reference
        assert pending.attempts == 1


def test_create_story_cleans_up_audio_when_finalization_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    created_reference = (
        "r2://narration/"
        "11111111111111111111111111111111.mp3"
    )
    deleted_references: list[str] = []
    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        lambda **_kwargs: created_reference,
    )

    def fail_finalization(
        _recorder: object,
        **_: object,
    ) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        story_workflow.RunCostRecorder,
        "finalize",
        fail_finalization,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        deleted_references.append,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/stories",
            json={
                "child_id": child["id"],
                "event_text": "Camille helped make dinner.",
            },
        )

    assert deleted_references == [created_reference]


def test_create_story_retains_audio_when_finalization_cleanup_fails(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    created_reference = (
        "r2://narration/"
        "11111111111111111111111111111111.mp3"
    )
    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        lambda **_kwargs: created_reference,
    )

    def fail_finalization(
        _recorder: object,
        **_: object,
    ) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        story_workflow.RunCostRecorder,
        "finalize",
        fail_finalization,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda _reference: (_ for _ in ()).throw(
            OSError("cleanup unavailable")
        ),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/stories",
            json={
                "child_id": child["id"],
                "event_text": "Camille helped make dinner.",
            },
        )

    with db_session_factory() as db:
        pending = db.scalar(select(PendingAssetDeletion))
        assert pending is not None
        assert pending.reference == created_reference
        assert pending.attempts == 0


@pytest.mark.parametrize("language", ["en", "fr"])
def test_create_story_persists_deterministic_narration_urls(
    client: TestClient,
    language: str,
) -> None:
    child = _create_child(client, language=language)
    event_text = "Camille helped prepare dinner."

    first_story = _create_story(client, child["id"], event_text)
    second_story = _create_story(client, child["id"], event_text)

    assert first_story["status"] == "pending_review"
    assert second_story["status"] == "pending_review"
    assert first_story["pages"]
    assert second_story["pages"]
    first_urls = [page["audio_url"] for page in first_story["pages"]]
    second_urls = [page["audio_url"] for page in second_story["pages"]]
    assert all(isinstance(url, str) for url in first_urls)
    assert all(
        f"/media/placeholders/narration/{language}/" in url
        for url in first_urls
    )
    assert len(set(first_urls)) == len(first_urls)
    assert second_urls == first_urls
    assert [
        page["audio_url"]
        for page in client.get(f"/stories/{first_story['id']}").json()[
            "pages"
        ]
    ] == first_urls


def test_stub_narration_url_serves_wav_audio(client: TestClient) -> None:
    child = _create_child(client)
    story = _create_story(client, child["id"], "A good day.")

    response = client.get(story["pages"][0]["audio_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert response.content[8:12] == b"WAVE"
    assert len(response.content) > 44


def test_create_story_persists_rejected_event_without_generation(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client, language="fr")

    def fail_generation(**_: object) -> None:
        raise AssertionError("Unsafe event reached story generation.")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_generation,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille a trouvé une arme.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["language"] == "fr"
    assert body["status"] == "rejected"
    assert body["failure_reason"] == "safety_content_blocked"
    assert body["pages"] == []

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille a trouvé une arme."
        assert stored_story.status is StoryStatus.REJECTED
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


def test_create_story_discards_unsafe_generated_content(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)

    def generate_unsafe_story(**_: object) -> StoryGenerationResult:
        return StoryGenerationResult(
            title="Camille and the Gentle Star",
            pages=[
                "Camille followed a friendly guide.",
                "The guide discovered blood on the path.",
            ],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_unsafe_story,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped prepare dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == "Camille and the Gentle Star"
    assert body["language"] == "en"
    assert body["status"] == "rejected"
    assert body["failure_reason"] == "safety_generated_page_2_blocked"
    assert body["pages"] == []

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille helped prepare dinner."
        assert stored_story.title == "Camille and the Gentle Star"
        assert stored_story.status is StoryStatus.REJECTED
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


def test_create_story_records_generation_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client, language="fr")

    def fail_generation(**_: object) -> None:
        raise RuntimeError("provider unavailable: secret details")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_generation,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "  Camille a aidé à préparer le dîner.  ",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["language"] == "fr"
    assert body["status"] == "generation_failed"
    assert body["failure_reason"] == "story_generation_failed"
    assert body["pages"] == []
    assert "secret details" not in response.text

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == (
            "Camille a aidé à préparer le dîner."
        )
        assert stored_story.status is StoryStatus.GENERATION_FAILED
        assert stored_story.failure_reason == "story_generation_failed"
        assert stored_story.pages == []


def test_create_story_records_illustration_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "image_gen_provider", "unknown")

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped prepare dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["status"] == "generation_failed"
    assert body["failure_reason"] == "illustration_generation_failed"
    assert body["pages"] == []
    assert "Unsupported illustration provider" not in response.text

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


def test_create_story_records_narration_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "tts_provider", "unknown")

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped prepare dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["status"] == "generation_failed"
    assert body["failure_reason"] == "narration_generation_failed"
    assert body["pages"] == []
    assert "Unsupported narration provider" not in response.text

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


def test_create_story_uses_child_story_language(client: TestClient) -> None:
    child = _create_child(client, language="fr")

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille a aidé à préparer le dîner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["language"] == "fr"
    assert body["title"] == "Camille et la douce étoile"
    assert len(body["pages"]) == 10
    assert any("dîner" in page["text"] for page in body["pages"])


def test_create_story_requires_existing_child(client: TestClient) -> None:
    _create_child(client)
    response = client.post(
        "/stories",
        json={
            "child_id": str(uuid4()),
            "event_text": "A good day.",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}


@pytest.mark.parametrize(
    "payload",
    [
        {"child_id": "not-a-uuid", "event_text": "A good day."},
        {"child_id": str(uuid4()), "event_text": ""},
        {"child_id": str(uuid4()), "event_text": " " * 3},
        {"child_id": str(uuid4()), "event_text": "a" * 2001},
    ],
)
def test_create_story_rejects_invalid_input(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    _create_child(client)
    response = client.post("/stories", json=payload)

    assert response.status_code == 422


def test_list_stories_scopes_to_child_and_orders_newest_first(
    client: TestClient,
) -> None:
    child = _create_child(client, email="first@example.com")
    other_child = _create_child(client, email="other@example.com")
    first_story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )
    second_story = _create_story(
        client,
        child["id"],
        "Camille built a paper crane.",
    )
    _create_story(client, other_child["id"], "Another child's story.")

    response = client.get(f"/stories/by-child/{child['id']}")

    assert response.status_code == 200
    stories = response.json()
    assert [story["id"] for story in stories] == [
        second_story["id"],
        first_story["id"],
    ]
    assert all(story["child_id"] == child["id"] for story in stories)
    assert all(len(story["pages"]) == 10 for story in stories)
    assert all(
        [page["page_number"] for page in story["pages"]]
        == list(range(1, 11))
        for story in stories
    )


def test_list_stories_returns_empty_list_for_existing_child(
    client: TestClient,
) -> None:
    child = _create_child(client)

    response = client.get(f"/stories/by-child/{child['id']}")

    assert response.status_code == 200
    assert response.json() == []


def test_list_stories_uses_id_to_break_created_at_ties(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    first_story = _create_story(client, child["id"], "First event.")
    second_story = _create_story(client, child["id"], "Second event.")
    matching_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with db_session_factory() as db:
        for story_id in (first_story["id"], second_story["id"]):
            story = db.get(Story, UUID(story_id))
            assert story is not None
            story.created_at = matching_created_at
        db.commit()

    response = client.get(f"/stories/by-child/{child['id']}")

    assert response.status_code == 200
    expected_ids = sorted(
        [first_story["id"], second_story["id"]],
        reverse=True,
    )
    assert [story["id"] for story in response.json()] == expected_ids


def test_list_stories_requires_existing_child(client: TestClient) -> None:
    _create_child(client)
    response = client.get(f"/stories/by-child/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}


def test_list_stories_rejects_invalid_child_id(client: TestClient) -> None:
    _create_child(client)
    response = client.get("/stories/by-child/not-a-uuid")

    assert response.status_code == 422


def test_get_story_returns_complete_story_with_ordered_pages(
    client: TestClient,
) -> None:
    child = _create_child(client)
    created_story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )

    response = client.get(f"/stories/{created_story['id']}")

    assert response.status_code == 200
    story = response.json()
    assert story == {
        **created_story,
        "event_text": "Camille helped make dinner.",
        "safety_reason": None,
    }
    assert [page["page_number"] for page in story["pages"]] == list(
        range(1, 11)
    )


def test_rejection_details_only_appear_on_parent_story_detail(
    client: TestClient,
) -> None:
    child = _create_child(client)
    event_text = "Camille found a weapon."

    create_response = client.post(
        "/stories",
        json={"child_id": child["id"], "event_text": event_text},
    )
    list_response = client.get(f"/stories/by-child/{child['id']}")
    detail_response = client.get(
        f"/stories/{create_response.json()['id']}"
    )

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    protected_fields = {
        "event_text",
        "safety_reason",
        "moderation_record",
        "flagged_text",
        "categories",
        "category_scores",
    }
    assert protected_fields.isdisjoint(create_response.json())
    assert protected_fields.isdisjoint(list_response.json()[0])
    detail = detail_response.json()
    assert detail["event_text"] == event_text
    assert detail["safety_reason"] == "unsafe_content"
    assert {
        "moderation_record",
        "flagged_text",
        "categories",
        "category_scores",
    }.isdisjoint(detail)


def test_get_story_returns_not_found_for_missing_story(
    client: TestClient,
) -> None:
    _create_child(client)
    response = client.get(f"/stories/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_get_story_rejects_invalid_story_id(client: TestClient) -> None:
    _create_child(client)
    response = client.get("/stories/not-a-uuid")

    assert response.status_code == 422


def test_get_story_route_coexists_with_list_by_child_route(
    client: TestClient,
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")

    list_response = client.get(f"/stories/by-child/{child['id']}")
    get_response = client.get(f"/stories/{created_story['id']}")

    assert list_response.status_code == 200
    assert [story["id"] for story in list_response.json()] == [
        created_story["id"]
    ]
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created_story["id"]


def test_approve_story_persists_review_decision(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")
    review_started_at = datetime.now(timezone.utc)

    response = client.patch(
        f"/stories/{created_story['id']}/approve",
        json={"approve": True},
    )
    review_finished_at = datetime.now(timezone.utc)

    assert response.status_code == 200
    story = response.json()
    assert story["status"] == "approved"
    assert story["approved_at"] is not None
    approved_at = _as_utc(datetime.fromisoformat(story["approved_at"]))
    assert review_started_at <= approved_at <= review_finished_at
    assert story["pages"] == created_story["pages"]

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        assert stored_story.status is StoryStatus.APPROVED
        assert stored_story.approved_at is not None
        stored_approved_at = _as_utc(stored_story.approved_at)
        assert review_started_at <= stored_approved_at <= review_finished_at


def test_reject_story_persists_review_decision(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A difficult day.")

    response = client.patch(
        f"/stories/{created_story['id']}/approve",
        json={"approve": False},
    )

    assert response.status_code == 200
    story = response.json()
    assert story["status"] == "rejected"
    assert story["approved_at"] is None
    assert story["pages"] == created_story["pages"]

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        assert stored_story.status is StoryStatus.REJECTED
        assert stored_story.approved_at is None


@pytest.mark.parametrize(
    ("first_decision", "second_decision", "expected_status"),
    [
        (True, False, "approved"),
        (False, True, "rejected"),
    ],
)
def test_review_story_rejects_a_second_decision(
    client: TestClient,
    first_decision: bool,
    second_decision: bool,
    expected_status: str,
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")
    story_url = f"/stories/{created_story['id']}"

    first_response = client.patch(
        f"{story_url}/approve",
        json={"approve": first_decision},
    )
    second_response = client.patch(
        f"{story_url}/approve",
        json={"approve": second_decision},
    )
    first_review = first_response.json()
    stored_review = client.get(story_url).json()

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": "Story is not pending review."
    }
    assert stored_review["status"] == expected_status
    assert stored_review["approved_at"] == first_review["approved_at"]


def test_review_story_does_not_overwrite_a_concurrent_decision(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")
    story_id = UUID(created_story["id"])

    with db_session_factory() as stale_db:
        stale_story = stale_db.get(Story, story_id)
        assert stale_story is not None
        assert stale_story.status is StoryStatus.PENDING_REVIEW

        with db_session_factory() as current_db:
            review_story(
                db=current_db,
                story_id=story_id,
                approve=True,
            )

        with pytest.raises(StoryNotPendingReviewError):
            review_story(
                db=stale_db,
                story_id=story_id,
                approve=False,
            )

        stale_db.expire_all()
        stored_story = stale_db.get(Story, story_id)
        assert stored_story is not None
        assert stored_story.status is StoryStatus.APPROVED
        assert stored_story.approved_at is not None


def test_review_story_returns_not_found_for_missing_story(
    client: TestClient,
) -> None:
    _create_child(client)
    response = client.patch(
        f"/stories/{uuid4()}/approve",
        json={"approve": True},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_review_story_rejects_invalid_story_id(client: TestClient) -> None:
    _create_child(client)
    response = client.patch(
        "/stories/not-a-uuid/approve",
        json={"approve": True},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"approve": None},
        {"approve": 1},
        {"approve": "true"},
        {"approve": True, "unexpected": "value"},
    ],
)
def test_review_story_rejects_invalid_payload(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")

    response = client.patch(
        f"/stories/{created_story['id']}/approve",
        json=payload,
    )

    assert response.status_code == 422


def test_create_story_replays_existing_story_for_repeated_idempotency_key(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)

    first_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "create-story-1"},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )
    second_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "create-story-1"},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    first_body = first_response.json()
    assert second_response.json()["id"] == first_body["id"]
    assert second_response.json()["title"] == first_body["title"]
    with db_session_factory() as db:
        stories = db.scalars(
            select(Story).where(Story.child_id == UUID(child["id"]))
        ).all()
        assert len(stories) == 1
        key_rows = db.scalars(select(StoryIdempotencyKey)).all()
        assert len(key_rows) == 1
        assert key_rows[0].key == "create-story-1"
        assert key_rows[0].story_id == stories[0].id


def test_create_story_creates_distinct_stories_for_distinct_keys(
    client: TestClient,
) -> None:
    child = _create_child(client)

    first_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "create-story-1"},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )
    second_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "create-story-2"},
        json={
            "child_id": child["id"],
            "event_text": "Camille planted a seed.",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert second_response.json()["id"] != first_response.json()["id"]


def test_create_story_scopes_idempotency_key_to_same_parent(
    client: StoryForgeTestClient,
) -> None:
    parent = client.create_parent()
    parent_id = parent["id"]
    first_child = client.post(
        f"/parents/{parent_id}/children",
        json={
            "name": "Camille",
            "age": 7,
            "interests": "origami",
            "language": "en",
        },
    ).json()
    second_child = client.post(
        f"/parents/{parent_id}/children",
        json={
            "name": "Leo",
            "age": 5,
            "interests": "trains",
            "language": "en",
        },
    ).json()

    first_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "shared-key"},
        json={
            "child_id": first_child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )
    replay_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "shared-key"},
        json={
            "child_id": second_child["id"],
            "event_text": "Leo played with his trains.",
        },
    )

    assert first_response.status_code == 201
    assert replay_response.status_code == 200
    assert replay_response.json()["id"] == first_response.json()["id"]


def test_create_story_scopes_idempotency_key_across_parents(
    client: TestClient,
) -> None:
    child = _create_child(client)
    other_child = _create_child(
        client,
        email="other-parent@example.com",
    )

    first_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "shared-key"},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )
    other_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "shared-key"},
        json={
            "child_id": other_child["id"],
            "event_text": "Another child did something else.",
        },
    )

    assert other_response.status_code == 201
    assert other_response.json()["id"] != first_response.json()["id"]
    assert other_response.json()["child_id"] == other_child["id"]


@pytest.mark.parametrize(
    "key",
    ["", "   ", "x" * 201],
)
def test_create_story_rejects_blank_or_oversized_idempotency_keys(
    client: TestClient,
    key: str,
) -> None:
    child = _create_child(client)

    response = client.post(
        "/stories",
        headers={"Idempotency-Key": key},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 422


def test_create_story_purges_expired_idempotency_keys_when_recording_new(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    with db_session_factory() as db:
        stored_child = db.get(Child, UUID(child["id"]))
        assert stored_child is not None
        stale_story = Story(
            child_id=stored_child.id,
            event_text="A stale story.",
            language="en",
        )
        db.add(stale_story)
        db.flush()
        db.add(
            StoryIdempotencyKey(
                parent_id=stored_child.parent_id,
                key="stale-key",
                story_id=stale_story.id,
                created_at=datetime.now(timezone.utc)
                - timedelta(hours=settings.idempotency_key_ttl_hours + 1),
            )
        )
        db.commit()

    response = client.post(
        "/stories",
        headers={"Idempotency-Key": "fresh-key"},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 201
    with db_session_factory() as db:
        keys = db.scalars(select(StoryIdempotencyKey)).all()
        assert {key.key for key in keys} == {"fresh-key"}
        assert {key.story_id for key in keys} == {UUID(response.json()["id"])}


def test_create_story_queues_once_for_repeated_idempotency_key(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    notifications: list[UUID] = []
    monkeypatch.setattr(
        client.app.state,
        "notify_story_generation",
        notifications.append,
    )

    first_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "create-story-1"},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )
    second_response = client.post(
        "/stories",
        headers={"Idempotency-Key": "create-story-1"},
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    first_body = first_response.json()
    assert first_body["status"] == StoryStatus.GENERATING.value
    assert second_response.json()["id"] == first_body["id"]
    assert notifications == [UUID(first_body["id"])]
    with db_session_factory() as db:
        stories = db.scalars(
            select(Story).where(Story.child_id == UUID(child["id"]))
        ).all()
        assert len(stories) == 1
        assert stories[0].status is StoryStatus.GENERATING


def test_concurrent_requests_with_same_key_create_one_story(
    tmp_path: Path,
) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'idempotency.db'}")
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)
    try:
        with session_factory() as db:
            parent = Parent(email="parent@example.com")
            child = Child(
                name="Camille",
                age=7,
                interests="origami",
                language="en",
            )
            parent.children.append(child)
            db.add(parent)
            db.commit()
            child_id = child.id

        ready = Barrier(2)

        def create_story() -> tuple[UUID, bool]:
            with session_factory() as db:
                ready.wait()
                story, created = story_workflow.create_story_with_idempotency(
                    db=db,
                    child_id=child_id,
                    event_text="Camille helped make dinner.",
                    idempotency_key="concurrent-key",
                )
                return story.id, created

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda _: create_story(), range(2))
            )

        assert len({story_id for story_id, _ in results}) == 1
        assert sum(created for _, created in results) == 1
        with session_factory() as db:
            stories = db.scalars(select(Story)).all()
            assert len(stories) == 1
            key_rows = db.scalars(select(StoryIdempotencyKey)).all()
            assert len(key_rows) == 1
            assert key_rows[0].story_id == stories[0].id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
