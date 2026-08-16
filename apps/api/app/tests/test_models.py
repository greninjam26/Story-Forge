from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.db import Base, create_db_engine
from app.models import (
    Child,
    GenerationCostEvent,
    GenerationRun,
    GenerationRunStatus,
    GenerationStage,
    Parent,
    Story,
    StoryPage,
    StoryStatus,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_parent_uses_defaults_and_persists(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_parent = db_session.scalar(
        select(Parent).where(Parent.email == "parent@example.com")
    )

    assert saved_parent is not None
    assert isinstance(saved_parent.id, UUID)
    assert saved_parent.locale == "en"
    assert saved_parent.created_at is not None


def test_pending_asset_deletion_persists_retry_state(
    db_session: Session,
) -> None:
    pending = models.PendingAssetDeletion(
        reference=(
            "r2://illustrations/"
            "0123456789abcdef0123456789abcdef.webp"
        )
    )
    db_session.add(pending)
    db_session.commit()
    db_session.expire_all()

    saved = db_session.scalar(select(models.PendingAssetDeletion))

    assert saved is not None
    assert isinstance(saved.id, UUID)
    assert saved.reference == pending.reference
    assert saved.attempts == 0
    assert saved.last_error is None
    assert saved.created_at is not None
    assert saved.last_attempt_at is None
    assert saved.next_attempt_at is None
    assert saved.terminal_at is None


def test_pending_asset_deletion_rejects_negative_attempts(
    db_session: Session,
) -> None:
    db_session.add(
        models.PendingAssetDeletion(
            reference=(
                "r2://illustrations/"
                "0123456789abcdef0123456789abcdef.webp"
            ),
            attempts=-1,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_parent_rejects_unsupported_locale(db_session: Session) -> None:
    db_session.add(Parent(email="parent@example.com", locale="es"))

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_parent_email_must_be_unique(db_session: Session) -> None:
    db_session.add(Parent(email="parent@example.com"))
    db_session.commit()
    db_session.add(Parent(email="parent@example.com"))

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_child_uses_defaults_and_belongs_to_parent(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_child = db_session.scalar(select(Child).where(Child.name == "Camille"))

    assert saved_child is not None
    assert isinstance(saved_child.id, UUID)
    assert saved_child.parent.email == "parent@example.com"
    assert saved_child.language == "en"
    assert saved_child.interests == ""
    assert saved_child.reference_photo_ref is None
    assert saved_child.created_at is not None


def test_child_accepts_french_story_language(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    parent.children.append(Child(name="Camille", age=7, language="fr"))
    db_session.add(parent)
    db_session.commit()

    assert parent.children[0].language == "fr"


@pytest.mark.parametrize(
    ("age", "language"),
    [(0, "en"), (13, "en"), (7, "es")],
)
def test_child_rejects_invalid_values(
    db_session: Session, age: int, language: str
) -> None:
    parent = Parent(email="parent@example.com")
    parent.children.append(Child(name="Camille", age=age, language=language))
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_deleting_parent_deletes_children(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    parent.children.append(Child(name="Camille", age=7))
    db_session.add(parent)
    db_session.commit()

    db_session.delete(parent)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Child)) == 0


def test_story_uses_defaults_and_belongs_to_child(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7, language="fr")
    story = Story(
        event_text="Camille helped make dinner.",
        language=child.language,
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_story = db_session.scalar(
        select(Story).where(Story.event_text == "Camille helped make dinner.")
    )

    assert saved_story is not None
    assert isinstance(saved_story.id, UUID)
    assert saved_story.child.name == "Camille"
    assert saved_story.language == "fr"
    assert saved_story.status is StoryStatus.GENERATING
    assert saved_story.title == ""
    assert saved_story.failure_reason is None
    assert saved_story.safety_reason is None
    assert saved_story.cost_usd == Decimal("0.0000")
    assert saved_story.generation_claim_token is None
    assert saved_story.generation_claimed_at is None
    assert saved_story.generation_attempts == 0
    assert saved_story.generation_stage.value == "story_text"
    assert saved_story.created_at is not None
    assert saved_story.approved_at is None


def test_story_persists_generation_claim_state(db_session: Session) -> None:
    claim_token = uuid4()
    claimed_at = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
    parent = Parent(email="claim@example.com")
    child = Child(name="Camille", age=7)
    child.stories.append(
        Story(
            event_text="Camille found a smooth stone.",
            language="en",
            generation_claim_token=claim_token,
            generation_claimed_at=claimed_at,
            generation_attempts=2,
            generation_stage=GenerationStage.ILLUSTRATIONS,
        )
    )
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_story = db_session.scalar(select(Story))

    assert saved_story is not None
    assert saved_story.generation_claim_token == claim_token
    assert saved_story.generation_claimed_at is not None
    assert saved_story.generation_claimed_at.replace(
        tzinfo=timezone.utc
    ) == claimed_at
    assert saved_story.generation_attempts == 2
    assert saved_story.generation_stage is GenerationStage.ILLUSTRATIONS


def test_story_rejects_negative_generation_attempts(
    db_session: Session,
) -> None:
    parent = Parent(email="claim@example.com")
    child = Child(name="Camille", age=7)
    child.stories.append(
        Story(
            event_text="Camille found a smooth stone.",
            language="en",
            generation_attempts=-1,
        )
    )
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


@pytest.mark.parametrize(
    ("claim_token", "claimed_at"),
    [
        (uuid4(), None),
        (None, datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)),
    ],
)
def test_story_rejects_partial_generation_claims(
    db_session: Session,
    claim_token: UUID | None,
    claimed_at: datetime | None,
) -> None:
    parent = Parent(email="claim@example.com")
    child = Child(name="Camille", age=7)
    child.stories.append(
        Story(
            event_text="Camille found a smooth stone.",
            language="en",
            generation_claim_token=claim_token,
            generation_claimed_at=claimed_at,
        )
    )
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_story_owns_one_private_moderation_record(
    db_session: Session,
) -> None:
    parent = Parent(email="moderation@example.com")
    child = Child(name="Camille", age=7)
    story = Story(
        event_text="Camille helped make dinner.",
        language="en",
        status=StoryStatus.REJECTED,
        failure_reason="safety_generated_page_1_blocked",
        safety_reason="violence",
    )
    story.moderation_record = models.ModerationRecord(
        provider="openai",
        model="omni-moderation-test",
        provider_request_id="req_test",
        flagged_item_kind="page",
        flagged_page_number=1,
        flagged_text="Only this generated page is retained.",
        categories=["violence"],
        category_scores={"violence": 0.93},
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    record_id = story.moderation_record.id
    db_session.expire_all()

    saved_story = db_session.get(Story, story.id)

    assert saved_story is not None
    assert saved_story.moderation_record is not None
    assert saved_story.moderation_record.review_status == "pending"
    assert saved_story.moderation_record.categories == ["violence"]
    assert saved_story.moderation_record.reviewed_at is None
    assert saved_story.moderation_record.created_at is not None

    db_session.delete(saved_story)
    db_session.commit()

    assert db_session.get(models.ModerationRecord, record_id) is None


def test_story_status_can_move_to_pending_review(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille shared a toy.", language="en")
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    story.title = "The Shared Star"
    story.status = StoryStatus.PENDING_REVIEW
    db_session.commit()
    db_session.refresh(story)

    assert story.title == "The Shared Star"
    assert story.status is StoryStatus.PENDING_REVIEW


@pytest.mark.parametrize(
    ("language", "cost_usd"),
    [("es", Decimal("0")), ("en", Decimal("-0.01"))],
)
def test_story_rejects_invalid_values(
    db_session: Session, language: str, cost_usd: Decimal
) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    child.stories.append(
        Story(
            event_text="Camille went to the park.",
            language=language,
            cost_usd=cost_usd,
        )
    )
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_deleting_child_deletes_stories(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    child.stories.append(
        Story(event_text="Camille learned to whistle.", language="en")
    )
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    db_session.delete(child)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Story)) == 0


def test_story_pages_are_ordered_and_allow_pending_assets(
    db_session: Session,
) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille planted a seed.", language="en")
    story.pages.extend(
        [
            StoryPage(page_number=2, text="A green shoot appeared."),
            StoryPage(page_number=1, text="Camille planted a tiny seed."),
        ]
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_story = db_session.scalar(
        select(Story).where(Story.event_text == "Camille planted a seed.")
    )

    assert saved_story is not None
    assert [page.page_number for page in saved_story.pages] == [1, 2]
    assert saved_story.pages[0].story is saved_story
    assert saved_story.pages[0].image_url is None
    assert saved_story.pages[0].audio_url is None


def test_story_page_number_must_be_positive(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille drew a picture.", language="en")
    story.pages.append(StoryPage(page_number=0, text="A bright picture."))
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_story_page_numbers_are_unique_within_story(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille built a tower.", language="en")
    story.pages.extend(
        [
            StoryPage(page_number=1, text="The first block."),
            StoryPage(page_number=1, text="Another first page."),
        ]
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_generation_run_records_cost_before_story_exists(
    db_session: Session,
) -> None:
    run = GenerationRun()
    run.cost_events.append(
        GenerationCostEvent(
            call_id=uuid4(),
            stage="story",
            provider="stub",
            model=None,
            attempt=1,
            page_number=None,
            outcome="succeeded",
            usage_unit="request",
            quantity=1,
            unit_rate_usd=Decimal("0"),
            cost_usd=Decimal("0"),
            cost_known=True,
        )
    )
    db_session.add(run)
    db_session.commit()
    db_session.expire_all()

    saved_run = db_session.scalar(select(GenerationRun))

    assert saved_run is not None
    assert isinstance(saved_run.id, UUID)
    assert saved_run.story_id is None
    assert saved_run.status is GenerationRunStatus.IN_PROGRESS
    assert saved_run.known_cost_usd == Decimal("0")
    assert saved_run.cost_complete is True
    assert saved_run.ceiling_exceeded is False
    assert saved_run.started_at is not None
    assert saved_run.completed_at is None
    assert len(saved_run.cost_events) == 1
    saved_event = saved_run.cost_events[0]
    assert saved_event.generation_run is saved_run
    assert saved_event.stage == "story"
    assert saved_event.provider == "stub"
    assert saved_event.quantity == 1
    assert saved_event.cost_usd == Decimal("0")
    assert saved_event.cost_known is True
    assert saved_event.created_at is not None


def test_story_retains_multiple_generation_runs(
    db_session: Session,
) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille tried again.", language="en")
    story.generation_runs.extend(
        [
            GenerationRun(
                status=GenerationRunStatus.FAILED,
            ),
            GenerationRun(
                status=GenerationRunStatus.SUCCEEDED,
            ),
        ]
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_story = db_session.scalar(
        select(Story).where(Story.event_text == "Camille tried again.")
    )

    assert saved_story is not None
    assert {run.status for run in saved_story.generation_runs} == {
        GenerationRunStatus.FAILED,
        GenerationRunStatus.SUCCEEDED,
    }
    assert all(run.story is saved_story for run in saved_story.generation_runs)


def test_cost_event_requires_known_cost_details(
    db_session: Session,
) -> None:
    run = GenerationRun()
    run.cost_events.append(
        GenerationCostEvent(
            call_id=uuid4(),
            stage="story",
            provider="provider",
            model="model",
            attempt=1,
            page_number=None,
            outcome="succeeded",
            usage_unit="input_token",
            quantity=10,
            unit_rate_usd=None,
            cost_usd=None,
            cost_known=True,
        )
    )
    db_session.add(run)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_deleting_story_deletes_pages(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille found a shell.", language="en")
    story.pages.append(StoryPage(page_number=1, text="A shell by the water."))
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    db_session.delete(story)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(StoryPage)) == 0


def test_story_idempotency_key_is_unique_per_parent(
    db_session: Session,
) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille found a shell.", language="en")
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    first = models.StoryIdempotencyKey(
        parent_id=parent.id,
        key="create-story-1",
        story_id=story.id,
    )
    db_session.add(first)
    db_session.commit()

    duplicate = models.StoryIdempotencyKey(
        parent_id=parent.id,
        key="create-story-1",
        story_id=story.id,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    other_parent = Parent(email="other@example.com")
    other_child = Child(name="Liam", age=5)
    other_story = Story(event_text="Liam found a pebble.", language="en")
    other_child.stories.append(other_story)
    other_parent.children.append(other_child)
    db_session.add(other_parent)
    db_session.commit()

    other_key = models.StoryIdempotencyKey(
        parent_id=other_parent.id,
        key="create-story-1",
        story_id=other_story.id,
    )
    db_session.add(other_key)
    db_session.commit()

    assert (
        db_session.scalar(
            select(func.count()).select_from(models.StoryIdempotencyKey)
        )
        == 2
    )


def test_deleting_story_deletes_its_idempotency_key(
    db_session: Session,
) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille found a shell.", language="en")
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    db_session.add(
        models.StoryIdempotencyKey(
            parent_id=parent.id,
            key="create-story-1",
            story_id=story.id,
        )
    )
    db_session.commit()

    db_session.delete(story)
    db_session.commit()

    assert (
        db_session.scalar(
            select(func.count()).select_from(models.StoryIdempotencyKey)
        )
        == 0
    )
