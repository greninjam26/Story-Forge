import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Child,
    GenerationRun,
    GenerationRunStatus,
    Parent,
)
from app.services import story_workflow
from app.services.cost_tracking import CostRecorder, RunCostRecorder
from app.services.story_workflow import (
    StoryNarrationGenerationError,
    StoryNotPendingReviewError,
    create_story,
    review_story,
    update_story,
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


def test_page_edit_adds_succeeded_narration_cost_run(
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

        updated_story = update_story(
            db=db,
            story_id=story.id,
            title=None,
            pages={
                2: "A calmer second page.",
                4: "A brighter fourth page.",
            },
        )

        db.expire_all()
        runs = list(
            db.scalars(
                select(GenerationRun)
                .where(GenerationRun.story_id == updated_story.id)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[0].id == original_run_id
        assert runs[1].status is GenerationRunStatus.SUCCEEDED
        assert runs[1].completed_at is not None
        assert len(runs[1].cost_events) == 2
        assert {event.stage for event in runs[1].cost_events} == {"tts"}
        assert {event.quantity for event in runs[1].cost_events} == {21, 23}
        assert all(event.cost_known for event in runs[1].cost_events)


def test_page_edit_finalizes_failed_narration_run_and_preserves_draft(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_narration(
        *,
        recorder: CostRecorder,
        **_: object,
    ) -> str:
        recorder.record_call(
            stage="tts",
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
        original_text = story.pages[0].text
        original_audio_url = story.pages[0].audio_url
        monkeypatch.setattr(
            story_workflow,
            "generate_narration",
            fail_narration,
        )

        with pytest.raises(StoryNarrationGenerationError):
            update_story(
                db=db,
                story_id=story.id,
                title=None,
                pages={1: "A newly edited first page."},
            )

        db.expire_all()
        saved_story = db.get(type(story), story.id)
        assert saved_story is not None
        assert saved_story.pages[0].text == original_text
        assert saved_story.pages[0].audio_url == original_audio_url
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


def test_page_edit_preserves_domain_error_when_finalization_fails(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_narration(**_: object) -> str:
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
        original_text = story.pages[0].text
        monkeypatch.setattr(
            story_workflow,
            "generate_narration",
            fail_narration,
        )
        monkeypatch.setattr(
            RunCostRecorder,
            "finalize",
            fail_finalization,
        )

        with pytest.raises(StoryNarrationGenerationError):
            update_story(
                db=db,
                story_id=story.id,
                title=None,
                pages={1: "A newly edited first page."},
            )

        db.expire_all()
        saved_story = db.get(type(story), story.id)
        assert saved_story is not None
        assert saved_story.pages[0].text == original_text
        runs = list(
            db.scalars(
                select(GenerationRun)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.IN_PROGRESS
        assert runs[1].cost_events == []


def test_title_only_edit_does_not_create_generation_run(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        child = _create_child(db)
        story = create_story(
            db=db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )

        update_story(
            db=db,
            story_id=story.id,
            title="Camille's Wonderful Evening",
            pages={},
        )

        runs = list(
            db.scalars(
                select(GenerationRun).where(
                    GenerationRun.story_id == story.id
                )
            )
        )
        assert len(runs) == 1


def test_page_edit_finalizes_run_discarded_by_concurrent_review(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as stale_db:
        child = _create_child(stale_db)
        story = create_story(
            db=stale_db,
            child_id=child.id,
            event_text="Camille explored a garden.",
        )

        with db_session_factory() as current_db:
            review_story(
                db=current_db,
                story_id=story.id,
                approve=True,
            )

        with pytest.raises(StoryNotPendingReviewError):
            update_story(
                db=stale_db,
                story_id=story.id,
                title=None,
                pages={1: "A newly edited first page."},
            )

        stale_db.expire_all()
        runs = list(
            stale_db.scalars(
                select(GenerationRun)
                .order_by(GenerationRun.started_at, GenerationRun.id)
            )
        )
        assert len(runs) == 2
        assert runs[1].status is GenerationRunStatus.FAILED
        assert runs[1].story_id is None
        assert runs[1].completed_at is not None
        assert len(runs[1].cost_events) == 1
        assert runs[1].cost_events[0].stage == "tts"
