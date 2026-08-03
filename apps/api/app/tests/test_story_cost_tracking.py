from collections import Counter
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import (
    Child,
    GenerationRun,
    GenerationRunStatus,
    Parent,
    Story,
    StoryStatus,
)
from app.schemas import StoryGenerationResult
from app.services import story_workflow
from app.services.cost_tracking import CostRecorder, RunCostRecorder, Usage
from app.services.story_workflow import (
    StoryNotPendingReviewError,
    StoryRegenerationError,
    create_story,
    regenerate_story,
    review_story,
)


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


def test_create_story_does_not_commit_story_or_events_before_finalization(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_finalization(
        _recorder: RunCostRecorder,
        **_: object,
    ) -> None:
        raise RuntimeError("finalization unavailable")

    monkeypatch.setattr(
        RunCostRecorder,
        "finalize",
        fail_finalization,
    )

    with db_session_factory() as db:
        child = _create_child(db)

        with pytest.raises(RuntimeError, match="finalization unavailable"):
            create_story(
                db=db,
                child_id=child.id,
                event_text="Camille helped make dinner.",
            )

        db.rollback()
        db.expire_all()
        assert list(
            db.scalars(select(Story).where(Story.child_id == child.id))
        ) == []
        run = db.scalar(select(GenerationRun))
        assert run is not None
        assert run.status is GenerationRunStatus.IN_PROGRESS
        assert run.cost_events == []


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
        run = db.scalar(select(GenerationRun))
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED
        assert run.story_id is None
        assert run.completed_at is not None
        assert run.cost_complete is False
        assert len(run.cost_events) == 1
        assert run.cost_events[0].outcome == "provider_failure"


def test_create_story_preserves_failure_when_cost_finalization_fails(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_messages: list[str] = []

    def fail_story_generation(**_: object) -> StoryGenerationResult:
        raise RuntimeError("provider unavailable")

    def fail_finalization(
        _recorder: RunCostRecorder,
        **_: object,
    ) -> None:
        raise RuntimeError("accounting unavailable")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_story_generation,
    )
    monkeypatch.setattr(
        RunCostRecorder,
        "finalize",
        fail_finalization,
    )
    monkeypatch.setattr(
        story_workflow.logger,
        "exception",
        lambda message, *_: log_messages.append(message),
    )

    with db_session_factory() as db:
        child = _create_child(db)

        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )

        db.expire_all()
        saved_story = db.get(Story, story.id)
        assert saved_story is not None
        assert saved_story.status is StoryStatus.GENERATION_FAILED
        run = db.scalar(select(GenerationRun))
        assert run is not None
        assert run.status is GenerationRunStatus.IN_PROGRESS
        assert run.cost_events == []

    assert log_messages == ["failed to finalize generation cost run %s"]


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
        run = db.scalar(select(GenerationRun))
        assert run is not None
        assert run.status is GenerationRunStatus.FAILED
        assert run.story_id is None
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


def test_regenerate_story_adds_succeeded_run_without_replacing_original(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        child = _create_child(db)
        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )
        original_run_id = story.generation_runs[0].id

        regenerated_story = regenerate_story(db=db, story_id=story.id)

        db.expire_all()
        runs = list(
            db.scalars(
                select(GenerationRun)
                .where(GenerationRun.story_id == regenerated_story.id)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[0].id == original_run_id
        assert runs[0].status is GenerationRunStatus.SUCCEEDED
        assert runs[1].status is GenerationRunStatus.SUCCEEDED
        assert runs[1].completed_at is not None
        assert len(runs[1].cost_events) == 21
        assert Counter(event.stage for event in runs[1].cost_events) == Counter(
            {"story_text": 1, "illustration": 10, "tts": 10}
        )


def test_regenerate_story_finalizes_failed_run_and_preserves_draft(
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

    with db_session_factory() as db:
        child = _create_child(db)
        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )
        story.cost_usd = Decimal("0.42")
        db.commit()
        original_title = story.title
        original_pages = [page.text for page in story.pages]
        monkeypatch.setattr(
            story_workflow,
            "generate_story",
            fail_story_generation,
        )

        with pytest.raises(StoryRegenerationError):
            regenerate_story(db=db, story_id=story.id)

        db.expire_all()
        saved_story = db.get(type(story), story.id)
        assert saved_story is not None
        assert saved_story.title == original_title
        assert [page.text for page in saved_story.pages] == original_pages
        assert saved_story.failure_reason == "story_regeneration_failed"
        assert saved_story.cost_usd == Decimal("0.42")
        runs = list(
            db.scalars(
                select(GenerationRun)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.FAILED
        assert runs[1].story_id is None
        assert runs[1].cost_complete is False
        assert len(runs[1].cost_events) == 1
        assert runs[1].cost_events[0].outcome == "provider_failure"


def test_regeneration_preserves_domain_error_when_finalization_fails(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_story_generation(**_: object) -> StoryGenerationResult:
        raise RuntimeError("provider unavailable")

    def fail_finalization(
        _recorder: RunCostRecorder,
        **_: object,
    ) -> None:
        raise RuntimeError("accounting unavailable")

    with db_session_factory() as db:
        child = _create_child(db)
        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )
        monkeypatch.setattr(
            story_workflow,
            "generate_story",
            fail_story_generation,
        )
        monkeypatch.setattr(
            RunCostRecorder,
            "finalize",
            fail_finalization,
        )

        with pytest.raises(StoryRegenerationError):
            regenerate_story(db=db, story_id=story.id)

        db.expire_all()
        saved_story = db.get(Story, story.id)
        assert saved_story is not None
        assert saved_story.failure_reason == "story_regeneration_failed"
        runs = list(
            db.scalars(
                select(GenerationRun)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.IN_PROGRESS
        assert runs[1].cost_events == []


def test_regenerate_story_finalizes_rejected_run_with_story_cost(
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
            title="Camille and the Hidden Weapon",
            pages=["Camille followed a friendly guide home."],
        )

    with db_session_factory() as db:
        child = _create_child(db)
        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )
        monkeypatch.setattr(
            story_workflow,
            "generate_story",
            generate_unsafe_story,
        )

        rejected_story = regenerate_story(db=db, story_id=story.id)

        db.expire_all()
        assert rejected_story.status is StoryStatus.REJECTED
        assert rejected_story.pages == []
        runs = list(
            db.scalars(
                select(GenerationRun)
                .where(GenerationRun.story_id == story.id)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.REJECTED
        assert runs[1].completed_at is not None
        assert len(runs[1].cost_events) == 1
        assert runs[1].cost_events[0].stage == "story_text"


def test_regenerate_story_finalizes_run_when_safety_check_crashes(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_session_factory() as db:
        child = _create_child(db)
        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )
        monkeypatch.setattr(
            story_workflow,
            "check_generated_story",
            lambda **_: (_ for _ in ()).throw(
                RuntimeError("safety unavailable")
            ),
        )

        with pytest.raises(RuntimeError, match="safety unavailable"):
            regenerate_story(db=db, story_id=story.id)

        db.expire_all()
        runs = list(
            db.scalars(
                select(GenerationRun)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.FAILED
        assert runs[1].story_id is None
        assert runs[1].completed_at is not None
        assert len(runs[1].cost_events) == 1
        assert runs[1].cost_events[0].stage == "story_text"


def test_regenerate_story_finalizes_run_discarded_by_concurrent_review(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_session_factory() as db:
        child = _create_child(db)
        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )
        original_generate_story = story_workflow.generate_story

        def generate_then_review(**values: object) -> StoryGenerationResult:
            generated = original_generate_story(**values)
            with db_session_factory() as review_db:
                review_story(
                    db=review_db,
                    story_id=story.id,
                    approve=True,
                )
            return generated

        monkeypatch.setattr(
            story_workflow,
            "generate_story",
            generate_then_review,
        )

        with pytest.raises(StoryNotPendingReviewError):
            regenerate_story(db=db, story_id=story.id)

        db.expire_all()
        runs = list(
            db.scalars(
                select(GenerationRun)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.FAILED
        assert runs[1].story_id is None
        assert runs[1].completed_at is not None
        assert len(runs[1].cost_events) == 21
        assert Counter(event.stage for event in runs[1].cost_events) == Counter(
            {"story_text": 1, "illustration": 10, "tts": 10}
        )
