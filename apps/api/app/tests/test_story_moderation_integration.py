from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from threading import Event
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import (
    GenerationRun,
    GenerationRunStatus,
    ModerationRecord,
    Story,
    StoryStatus,
)
from app.schemas import StoryGenerationResult
from app.services import moderation_audit, openai_moderation, story_workflow
from app.services.cost_tracking import Usage


@pytest.fixture
def story_worker_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> Event:
    finished = Event()
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
            finished.set()

    monkeypatch.setattr(
        story_workflow,
        "process_queued_story",
        process_notified_story,
    )
    return finished


def _create_child(client: TestClient) -> str:
    parent = client.post(
        "/parents",
        json={"email": "moderation-parent@example.com"},
    )
    assert parent.status_code == 201
    child = client.post(
        f"/parents/{parent.json()['id']}/children",
        json={
            "name": "Camille",
            "age": 7,
            "interests": "stars",
            "language": "en",
        },
    )
    assert child.status_code == 201
    return child.json()["id"]


def _install_generated_story(
    monkeypatch: pytest.MonkeyPatch,
    *,
    title: str = "A Safe Title",
    pages: tuple[str, ...] = ("First page", "Second page"),
) -> None:
    def generate_story(*, recorder, **_: object) -> StoryGenerationResult:
        recorder.record_call(
            stage="story_text",
            provider="stub",
            model=None,
            attempt=1,
            outcome="succeeded",
            usage=(Usage("request", 1),),
        )
        return StoryGenerationResult(
            title=title,
            pages=list(pages),
        )

    monkeypatch.setattr(story_workflow, "generate_story", generate_story)


def _create_pending_story(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    child_id = _create_child(client)
    _install_generated_story(monkeypatch)
    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )
    assert response.status_code == 201
    return response.json()


def _moderation_response(
    *,
    flagged_index: int | None,
) -> openai_moderation.ModerationResponse:
    results = []
    for index in range(3):
        flagged = index == flagged_index
        results.append(
            openai_moderation.ModerationResult(
                flagged=flagged,
                categories={"violence": flagged},
                category_scores={"violence": 0.9 if flagged else 0.01},
            )
        )
    return openai_moderation.ModerationResponse(
        request_id="modr_test",
        model="omni-moderation-latest",
        results=tuple(results),
    )


def _select_openai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    flagged_index: int | None,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        openai_moderation,
        "moderate",
        lambda _inputs: _moderation_response(
            flagged_index=flagged_index
        ),
    )


@pytest.mark.parametrize(
    ("provider", "api_key"),
    [("misspelled", None), ("openai", "  ")],
)
def test_invalid_safety_configuration_is_rejected_before_cost_run(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    api_key: str | None,
) -> None:
    child_id = _create_child(client)
    monkeypatch.setattr(settings, "safety_provider", provider)
    monkeypatch.setattr(settings, "openai_api_key", api_key)
    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        lambda **_: pytest.fail("story generation must not run"),
    )

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "safety_provider_not_configured"
    }
    with db_session_factory() as db:
        assert db.scalar(select(GenerationRun)) is None
        assert db.scalar(select(Story)) is None


def test_openai_pass_continues_creation_with_known_zero_cost(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    story_worker_finished: Event,
) -> None:
    child_id = _create_child(client)
    _install_generated_story(monkeypatch)
    _select_openai(monkeypatch, flagged_index=None)

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "generating"
    assert response.json()["pages"] == []
    assert story_worker_finished.wait(timeout=0.5)
    with db_session_factory() as db:
        story = db.get(Story, UUID(response.json()["id"]))
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert story.status is StoryStatus.PENDING_REVIEW
        assert len(story.pages) == 2
        assert run is not None
        assert run.status is GenerationRunStatus.SUCCEEDED
        assert Counter(event.stage for event in run.cost_events) == Counter(
            {"story_text": 1, "moderation": 1, "illustration": 2, "tts": 2}
        )
        moderation_event = next(
            event for event in run.cost_events
            if event.stage == "moderation"
        )
        assert moderation_event.quantity == 1
        assert moderation_event.cost_known is True
        assert moderation_event.cost_usd == Decimal("0")
        assert db.scalar(select(ModerationRecord)) is None


@pytest.mark.parametrize(
    (
        "flagged_index",
        "item_kind",
        "page_number",
        "public_title",
        "failure_reason",
    ),
    [
        (0, "title", None, "", "safety_generated_title_blocked"),
        (2, "page", 2, "A Safe Title", "safety_generated_page_2_blocked"),
    ],
)
def test_openai_rejection_atomically_persists_private_audit(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    flagged_index: int,
    item_kind: str,
    page_number: int | None,
    public_title: str,
    failure_reason: str,
    story_worker_finished: Event,
) -> None:
    child_id = _create_child(client)
    _install_generated_story(monkeypatch)
    _select_openai(monkeypatch, flagged_index=flagged_index)
    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        lambda **_: pytest.fail("illustration must not run"),
    )
    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        lambda **_: pytest.fail("narration must not run"),
    )

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "generating"
    assert response.json()["title"] == ""
    assert response.json()["pages"] == []
    assert story_worker_finished.wait(timeout=0.5)
    with db_session_factory() as db:
        story = db.scalar(select(Story))
        record = db.scalar(select(ModerationRecord))
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert record is not None
        assert run is not None
        assert story.status is StoryStatus.REJECTED
        assert story.title == public_title
        assert story.safety_reason == "violence"
        assert story.failure_reason == failure_reason
        assert story.pages == []
        assert story.generation_claim_token is None
        assert story.generation_claimed_at is None
        assert record.story_id == story.id
        assert record.flagged_item_kind == item_kind
        assert record.flagged_page_number == page_number
        assert record.flagged_text == (
            "A Safe Title" if item_kind == "title" else "Second page"
        )
        assert run.status is GenerationRunStatus.REJECTED
        assert run.story_id == story.id
        assert Counter(event.stage for event in run.cost_events) == Counter(
            {"story_text": 1, "moderation": 1}
        )


def test_moderation_provider_failure_retains_background_story_for_retry(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    story_worker_finished: Event,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    child_id = _create_child(client)
    _install_generated_story(monkeypatch)
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        openai_moderation,
        "moderate",
        lambda _inputs: (_ for _ in ()).throw(
            openai_moderation.ModerationProviderError("private failure")
        ),
    )
    monkeypatch.setattr(
        story_workflow,
        "generate_illustration",
        lambda **_: pytest.fail("illustration must not run"),
    )

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "generating"
    assert story_worker_finished.wait(timeout=0.5)
    with db_session_factory() as db:
        story = db.get(Story, UUID(response.json()["id"]))
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert story.status is StoryStatus.GENERATING
        assert story.failure_reason is None
        assert story.generation_claim_token is not None
        assert story.generation_claimed_at is not None
        assert story.generation_attempts == 1
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED
        assert run.story_id is None
        assert [event.stage for event in run.cost_events] == [
            "story_text",
            "moderation",
            "moderation",
            "moderation",
        ]
        assert run.cost_events[-1].cost_known is True
        assert run.cost_events[-1].cost_usd == Decimal("0")
        assert db.scalar(select(ModerationRecord)) is None


def test_audit_failure_rolls_back_rejection_and_retains_story_for_retry(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    story_worker_finished: Event,
) -> None:
    child_id = _create_child(client)
    _install_generated_story(monkeypatch)
    _select_openai(monkeypatch, flagged_index=0)
    monkeypatch.setattr(
        moderation_audit,
        "add_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("private audit failure")
        ),
    )

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "generating"
    assert story_worker_finished.wait(timeout=0.5)
    with db_session_factory() as db:
        story = db.get(Story, UUID(response.json()["id"]))
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert story.status is StoryStatus.GENERATING
        assert story.failure_reason is None
        assert story.generation_claim_token is not None
        assert story.generation_claimed_at is not None
        assert story.generation_attempts == 1
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED
        assert run.story_id is None
        assert db.scalar(select(ModerationRecord)) is None


def test_rejection_commit_failure_never_leaves_story_without_audit(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    story_worker_finished: Event,
) -> None:
    child_id = _create_child(client)
    _install_generated_story(monkeypatch)
    _select_openai(monkeypatch, flagged_index=0)
    original_commit = db_session_factory.class_.commit
    rejection_commit_attempted = False

    def fail_rejection_commit(db: Session) -> None:
        nonlocal rejection_commit_attempted
        has_audit = any(
            isinstance(row, ModerationRecord)
            for row in (*db.new, *db.identity_map.values())
        )
        if not rejection_commit_attempted and has_audit:
            rejection_commit_attempted = True
            raise RuntimeError("transaction commit failure")
        original_commit(db)

    monkeypatch.setattr(
        db_session_factory.class_, "commit", fail_rejection_commit
    )

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )

    assert story_worker_finished.wait(timeout=0.5)
    assert rejection_commit_attempted is True
    assert response.status_code == 201
    assert response.json()["status"] == "generating"
    with db_session_factory() as db:
        story = db.get(Story, UUID(response.json()["id"]))
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert story.status is StoryStatus.GENERATING
        assert story.failure_reason is None
        assert story.generation_claim_token is not None
        assert story.generation_claimed_at is not None
        assert story.generation_attempts == 1
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED
        assert run.story_id is None
        assert db.scalar(select(ModerationRecord)) is None


def test_rejection_does_not_depend_on_post_commit_story_refresh(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    story_worker_finished: Event,
) -> None:
    child_id = _create_child(client)
    _install_generated_story(monkeypatch)
    _select_openai(monkeypatch, flagged_index=0)
    original_refresh = db_session_factory.class_.refresh

    def fail_rejected_story_refresh(
        db: Session,
        row: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        if isinstance(row, Story) and row.status is StoryStatus.REJECTED:
            raise RuntimeError("post-commit read failure")
        original_refresh(db, row, *args, **kwargs)

    monkeypatch.setattr(
        db_session_factory.class_, "refresh", fail_rejected_story_refresh
    )

    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": "A calm day."},
    )

    assert response.status_code == 201
    assert story_worker_finished.wait(timeout=0.5)
    story_id = UUID(response.json()["id"])
    with db_session_factory() as db:
        story = db.get(Story, story_id)
        run = db.scalar(select(GenerationRun))
        assert story is not None
        assert story.status is StoryStatus.REJECTED
        assert story.moderation_record is not None
        assert run is not None
        assert run.status is GenerationRunStatus.REJECTED
        assert run.story_id == story.id


@pytest.mark.parametrize(
    ("provider", "api_key"),
    [("misspelled", None), ("openai", "  ")],
)
def test_regeneration_rejects_invalid_safety_configuration_before_cost_run(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    api_key: str | None,
) -> None:
    original = _create_pending_story(client, monkeypatch)
    monkeypatch.setattr(settings, "safety_provider", provider)
    monkeypatch.setattr(settings, "openai_api_key", api_key)

    response = client.post(f"/stories/{original['id']}/regenerate")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "safety_provider_not_configured"
    }
    assert client.get(f"/stories/{original['id']}").json() == {
        **original,
        "event_text": "A calm day.",
        "safety_reason": None,
    }
    with db_session_factory() as db:
        assert len(list(db.scalars(select(GenerationRun)))) == 1


def test_openai_pass_continues_regeneration_with_known_zero_cost(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _create_pending_story(client, monkeypatch)
    _install_generated_story(
        monkeypatch,
        title="A New Safe Title",
        pages=("A new first page", "A new second page"),
    )
    _select_openai(monkeypatch, flagged_index=None)

    response = client.post(f"/stories/{original['id']}/regenerate")

    assert response.status_code == 200
    assert response.json()["title"] == "A New Safe Title"
    assert [page["text"] for page in response.json()["pages"]] == [
        "A new first page",
        "A new second page",
    ]
    with db_session_factory() as db:
        runs = list(
            db.scalars(
                select(GenerationRun).order_by(
                    GenerationRun.started_at,
                    GenerationRun.id,
                )
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.SUCCEEDED
        assert Counter(event.stage for event in runs[1].cost_events) == Counter(
            {"story_text": 1, "moderation": 1, "illustration": 2, "tts": 2}
        )
        moderation_event = next(
            event for event in runs[1].cost_events
            if event.stage == "moderation"
        )
        assert moderation_event.cost_known is True
        assert moderation_event.cost_usd == Decimal("0")
        assert db.scalar(select(ModerationRecord)) is None


@pytest.mark.parametrize(
    (
        "flagged_index",
        "item_kind",
        "page_number",
        "public_title",
        "failure_reason",
    ),
    [
        (0, "title", None, "", "safety_generated_title_blocked"),
        (2, "page", 2, "A New Safe Title", "safety_generated_page_2_blocked"),
    ],
)
def test_openai_regeneration_rejection_atomically_replaces_draft_with_audit(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    flagged_index: int,
    item_kind: str,
    page_number: int | None,
    public_title: str,
    failure_reason: str,
) -> None:
    original = _create_pending_story(client, monkeypatch)
    _install_generated_story(
        monkeypatch,
        title="A New Safe Title",
        pages=("A new first page", "A new second page"),
    )
    _select_openai(monkeypatch, flagged_index=flagged_index)

    response = client.post(f"/stories/{original['id']}/regenerate")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["title"] == public_title
    assert response.json()["failure_reason"] == failure_reason
    assert response.json()["pages"] == []
    with db_session_factory() as db:
        story = db.get(Story, UUID(str(original["id"])))
        record = db.scalar(select(ModerationRecord))
        runs = list(
            db.scalars(
                select(GenerationRun).order_by(
                    GenerationRun.started_at,
                    GenerationRun.id,
                )
            )
        )
        assert story is not None
        assert record is not None
        assert story.status is StoryStatus.REJECTED
        assert story.safety_reason == "violence"
        assert story.pages == []
        assert record.story_id == story.id
        assert record.flagged_item_kind == item_kind
        assert record.flagged_page_number == page_number
        assert record.flagged_text == (
            "A New Safe Title"
            if item_kind == "title"
            else "A new second page"
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.REJECTED
        assert runs[1].story_id == story.id
        assert Counter(event.stage for event in runs[1].cost_events) == Counter(
            {"story_text": 1, "moderation": 1}
        )


def test_regeneration_moderation_failure_preserves_existing_draft(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    original = _create_pending_story(client, monkeypatch)
    _install_generated_story(
        monkeypatch,
        title="A New Safe Title",
        pages=("A new first page", "A new second page"),
    )
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        openai_moderation,
        "moderate",
        lambda _inputs: (_ for _ in ()).throw(
            openai_moderation.ModerationProviderError("private failure")
        ),
    )

    response = client.post(f"/stories/{original['id']}/regenerate")

    assert response.status_code == 503
    assert response.json() == {"detail": "safety_review_unavailable"}
    assert client.get(f"/stories/{original['id']}").json() == {
        **original,
        "event_text": "A calm day.",
        "safety_reason": None,
    }
    with db_session_factory() as db:
        runs = list(
            db.scalars(
                select(GenerationRun).order_by(
                    GenerationRun.started_at,
                    GenerationRun.id,
                )
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.FAILED
        assert runs[1].story_id is None
        assert [event.stage for event in runs[1].cost_events] == [
            "story_text",
            "moderation",
            "moderation",
            "moderation",
        ]
        assert db.scalar(select(ModerationRecord)) is None


def test_regeneration_audit_failure_preserves_existing_draft(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _create_pending_story(client, monkeypatch)
    _install_generated_story(
        monkeypatch,
        title="A New Safe Title",
        pages=("A new first page", "A new second page"),
    )
    _select_openai(monkeypatch, flagged_index=0)
    monkeypatch.setattr(
        moderation_audit,
        "add_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("private audit failure")
        ),
    )

    response = client.post(f"/stories/{original['id']}/regenerate")

    assert response.status_code == 503
    assert response.json() == {"detail": "safety_review_unavailable"}
    assert client.get(f"/stories/{original['id']}").json() == {
        **original,
        "event_text": "A calm day.",
        "safety_reason": None,
    }
    with db_session_factory() as db:
        runs = list(
            db.scalars(
                select(GenerationRun).order_by(
                    GenerationRun.started_at,
                    GenerationRun.id,
                )
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.FAILED
        assert runs[1].story_id is None
        assert db.scalar(select(ModerationRecord)) is None


def test_regeneration_rejection_commit_failure_preserves_existing_draft(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _create_pending_story(client, monkeypatch)
    _install_generated_story(
        monkeypatch,
        title="A New Safe Title",
        pages=("A new first page", "A new second page"),
    )
    _select_openai(monkeypatch, flagged_index=0)
    original_commit = db_session_factory.class_.commit
    rejection_commit_attempted = False

    def fail_rejection_commit(db: Session) -> None:
        nonlocal rejection_commit_attempted
        has_audit = any(
            isinstance(row, ModerationRecord)
            for row in (*db.new, *db.identity_map.values())
        )
        if not rejection_commit_attempted and has_audit:
            rejection_commit_attempted = True
            raise RuntimeError("transaction commit failure")
        original_commit(db)

    monkeypatch.setattr(
        db_session_factory.class_, "commit", fail_rejection_commit
    )

    response = client.post(f"/stories/{original['id']}/regenerate")

    assert rejection_commit_attempted is True
    assert response.status_code == 503
    assert response.json() == {"detail": "safety_review_unavailable"}
    assert client.get(f"/stories/{original['id']}").json() == {
        **original,
        "event_text": "A calm day.",
        "safety_reason": None,
    }
    with db_session_factory() as db:
        runs = list(
            db.scalars(
                select(GenerationRun).order_by(
                    GenerationRun.started_at,
                    GenerationRun.id,
                )
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.FAILED
        assert runs[1].story_id is None
        assert db.scalar(select(ModerationRecord)) is None
