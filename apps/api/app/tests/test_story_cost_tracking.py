from collections import Counter

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import (
    Child,
    GenerationRun,
    GenerationRunStatus,
    Parent,
)
from app.schemas import StoryGenerationResult
from app.services import story_workflow
from app.services.cost_tracking import CostRecorder, Usage
from app.services.story_workflow import create_story


def _create_child(db: Session) -> Child:
    parent = Parent(email="parent@example.com")
    child = Child(
        name="Camille",
        age=7,
        interests="stars",
        language="en",
    )
    parent.children.append(child)
    db.add(parent)
    db.commit()
    return child


def test_create_story_finalizes_succeeded_zero_cost_run(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        child = _create_child(db)

        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille helped make dinner.",
        )

        db.expire_all()
        run = db.scalar(
            select(GenerationRun).where(
                GenerationRun.story_id == story.id
            )
        )
        assert run is not None
        assert run.status is GenerationRunStatus.SUCCEEDED
        assert run.completed_at is not None
        assert run.known_cost_usd == 0
        assert run.cost_complete is True
        assert run.ceiling_exceeded is False
        assert len(run.cost_events) == 21
        assert Counter(event.stage for event in run.cost_events) == Counter(
            {"story_text": 1, "illustration": 10, "tts": 10}
        )
        assert all(event.cost_known for event in run.cost_events)
        assert all(event.cost_usd == 0 for event in run.cost_events)


def test_create_story_finalizes_rejected_run_without_provider_costs(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        child = _create_child(db)

        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille found a weapon.",
        )

        db.expire_all()
        run = db.scalar(
            select(GenerationRun).where(
                GenerationRun.story_id == story.id
            )
        )
        assert run is not None
        assert run.status is GenerationRunStatus.REJECTED
        assert run.completed_at is not None
        assert run.known_cost_usd == 0
        assert run.cost_complete is True
        assert run.cost_events == []


def test_create_story_preserves_cost_when_generated_story_is_rejected(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def generate_unsafe_story(
        *,
        recorder: CostRecorder,
        **_: object,
    ) -> StoryGenerationResult:
        recorder.record_call(
            stage="story_text",
            provider="stub",
            model=None,
            attempt=1,
            outcome="succeeded",
            usage=(Usage("request", 1),),
        )
        return StoryGenerationResult(
            title="An unsafe story",
            pages=["Camille found blood on the path."],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_unsafe_story,
    )

    with db_session_factory() as db:
        child = _create_child(db)

        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )

        db.expire_all()
        run = db.scalar(
            select(GenerationRun).where(
                GenerationRun.story_id == story.id
            )
        )
        assert run is not None
        assert run.status is GenerationRunStatus.REJECTED
        assert len(run.cost_events) == 1
        assert run.cost_events[0].stage == "story_text"
        assert run.cost_events[0].cost_known is True


def test_create_story_finalizes_failed_provider_run(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_story_generation(
        *,
        recorder: CostRecorder,
        **_: object,
    ) -> StoryGenerationResult:
        recorder.record_call(
            stage="story_text",
            provider="provider",
            model="model-v1",
            attempt=1,
            outcome="provider_failure",
            usage=None,
        )
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_story_generation,
    )

    with db_session_factory() as db:
        child = _create_child(db)

        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )

        db.expire_all()
        run = db.scalar(
            select(GenerationRun).where(
                GenerationRun.story_id == story.id
            )
        )
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED
        assert run.completed_at is not None
        assert run.cost_complete is False
        assert len(run.cost_events) == 1
        assert run.cost_events[0].outcome == "provider_failure"


@pytest.mark.parametrize(
    ("setting_name", "expected_stages"),
    [
        ("image_gen_provider", {"story_text": 1}),
        ("tts_provider", {"story_text": 1, "illustration": 10}),
    ],
)
def test_create_story_finalizes_failed_media_run_with_prior_costs(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    setting_name: str,
    expected_stages: dict[str, int],
) -> None:
    monkeypatch.setattr(settings, setting_name, "unknown")

    with db_session_factory() as db:
        child = _create_child(db)

        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )

        db.expire_all()
        run = db.scalar(
            select(GenerationRun).where(
                GenerationRun.story_id == story.id
            )
        )
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED
        assert run.completed_at is not None
        assert run.cost_complete is True
        assert Counter(event.stage for event in run.cost_events) == Counter(
            expected_stages
        )


def test_create_story_finalizes_run_when_generated_safety_check_crashes(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        story_workflow,
        "check_generated_story",
        lambda **_: (_ for _ in ()).throw(RuntimeError("safety unavailable")),
    )

    with db_session_factory() as db:
        child = _create_child(db)

        with pytest.raises(RuntimeError, match="safety unavailable"):
            create_story(
                db=db,
                child_id=child.id,
                event_text="Camille explored a garden.",
            )

        db.expire_all()
        run = db.scalar(select(GenerationRun))
        assert run is not None
        assert run.story_id is None
        assert run.status is GenerationRunStatus.FAILED
        assert run.completed_at is not None
        assert len(run.cost_events) == 1
        assert run.cost_events[0].stage == "story_text"


def test_create_story_finalizes_run_when_input_safety_check_crashes(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        story_workflow,
        "check_text",
        lambda *_: (_ for _ in ()).throw(RuntimeError("safety unavailable")),
    )

    with db_session_factory() as db:
        child = _create_child(db)

        with pytest.raises(RuntimeError, match="safety unavailable"):
            create_story(
                db=db,
                child_id=child.id,
                event_text="Camille explored a garden.",
            )

        db.expire_all()
        run = db.scalar(select(GenerationRun))
        assert run is not None
        assert run.story_id is None
        assert run.status is GenerationRunStatus.FAILED
        assert run.completed_at is not None
        assert run.cost_events == []
