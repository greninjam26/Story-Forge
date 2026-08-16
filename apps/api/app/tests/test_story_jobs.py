from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, create_db_engine
from app.models import (
    Child,
    GenerationStage,
    Parent,
    Story,
    StoryStatus,
)


def _queue_story(
    session_factory: sessionmaker[Session],
    *,
    created_at: datetime | None = None,
) -> UUID:
    with session_factory() as db:
        parent = Parent(email=f"jobs-{uuid4()}@example.com")
        child = Child(name="Camille", age=7)
        story = Story(
            event_text="Camille helped make dinner.",
            language="en",
            status=StoryStatus.GENERATING,
            created_at=created_at,
        )
        child.stories.append(story)
        parent.children.append(child)
        db.add(parent)
        db.commit()
        return story.id


def test_claim_story_persists_claim_and_increments_attempts(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import claim_story

    story_id = _queue_story(db_session_factory)
    now = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)

    with db_session_factory() as db:
        claimed = claim_story(db, story_id=story_id, now=now)

    assert claimed is not None
    assert claimed.id == story_id
    assert claimed.generation_claim_token is not None
    assert claimed.generation_claimed_at is not None
    assert claimed.generation_claimed_at.replace(tzinfo=timezone.utc) == now
    assert claimed.generation_attempts == 1

    with db_session_factory() as db:
        saved = db.get(Story, story_id)
        assert saved is not None
        assert saved.generation_claim_token == claimed.generation_claim_token
        assert saved.generation_claimed_at is not None
        assert saved.generation_claimed_at.replace(tzinfo=timezone.utc) == now
        assert saved.generation_attempts == 1


def test_concurrent_workers_only_claim_a_story_once(
    tmp_path: Path,
) -> None:
    from app.services.story_jobs import claim_story

    engine = create_db_engine(f"sqlite:///{tmp_path / 'claims.db'}")
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)
    story_id = _queue_story(session_factory)
    ready = Barrier(2)

    def claim_from_worker() -> UUID | None:
        with session_factory() as db:
            ready.wait()
            claimed = claim_story(db, story_id=story_id)
            if claimed is None:
                return None
            return claimed.generation_claim_token

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            tokens = list(executor.map(lambda _: claim_from_worker(), range(2)))

        assert sum(token is not None for token in tokens) == 1
        with session_factory() as db:
            story = db.get(Story, story_id)
            assert story is not None
            assert story.generation_attempts == 1
            assert story.generation_claim_token in tokens
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_claim_story_recovers_a_stale_claim(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import claim_story

    story_id = _queue_story(db_session_factory)
    previous_token = uuid4()
    now = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
    with db_session_factory() as db:
        story = db.get(Story, story_id)
        assert story is not None
        story.generation_claim_token = previous_token
        story.generation_claimed_at = now - timedelta(minutes=16)
        story.generation_attempts = 1
        db.commit()

        claimed = claim_story(db, story_id=story_id, now=now)

    assert claimed is not None
    assert claimed.generation_claim_token not in {None, previous_token}
    assert claimed.generation_attempts == 2


def test_claim_story_does_not_reissue_a_fresh_claim(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import claim_story

    story_id = _queue_story(db_session_factory)
    now = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
    with db_session_factory() as db:
        first = claim_story(db, story_id=story_id, now=now)
        assert first is not None
        first_token = first.generation_claim_token

        second = claim_story(
            db,
            story_id=story_id,
            now=now + timedelta(minutes=14, seconds=59),
        )

        saved = db.get(Story, story_id)
        assert saved is not None
        assert second is None
        assert saved.generation_claim_token == first_token
        assert saved.generation_attempts == 1


def test_renew_claim_extends_only_the_matching_lease(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import (
        GenerationClaimLostError,
        claim_story,
        renew_claim,
    )

    story_id = _queue_story(db_session_factory)
    claimed_at = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
    renewed_at = claimed_at + timedelta(minutes=10)
    with db_session_factory() as db:
        claimed = claim_story(db, story_id=story_id, now=claimed_at)
        assert claimed is not None
        assert claimed.generation_claim_token is not None

        renew_claim(
            db,
            story_id=story_id,
            claim_token=claimed.generation_claim_token,
            now=renewed_at,
        )

        with pytest.raises(GenerationClaimLostError):
            renew_claim(
                db,
                story_id=story_id,
                claim_token=uuid4(),
                now=renewed_at + timedelta(minutes=1),
            )

        saved = db.get(Story, story_id)
        assert saved is not None
        assert saved.generation_claimed_at is not None
        assert saved.generation_claimed_at.replace(
            tzinfo=timezone.utc
        ) == renewed_at


def test_claim_story_does_not_exceed_the_attempt_limit(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import claim_story

    story_id = _queue_story(db_session_factory)
    with db_session_factory() as db:
        story = db.get(Story, story_id)
        assert story is not None
        story.generation_attempts = 5
        db.commit()

        claimed = claim_story(
            db,
            story_id=story_id,
            now=datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc),
        )

        assert claimed is None
        saved = db.get(Story, story_id)
        assert saved is not None
        assert saved.generation_attempts == 5


def test_claim_story_without_an_id_claims_the_oldest_story(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import claim_story

    older_id = _queue_story(
        db_session_factory,
        created_at=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
    )
    _queue_story(
        db_session_factory,
        created_at=datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc),
    )

    with db_session_factory() as db:
        claimed = claim_story(
            db,
            now=datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc),
        )

    assert claimed is not None
    assert claimed.id == older_id


def test_claim_story_marks_an_exhausted_stale_story_failed(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import claim_story

    story_id = _queue_story(db_session_factory)
    now = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
    with db_session_factory() as db:
        story = db.get(Story, story_id)
        assert story is not None
        story.generation_claim_token = uuid4()
        story.generation_claimed_at = now - timedelta(minutes=16)
        story.generation_attempts = 5
        db.commit()

        claimed = claim_story(db, story_id=story_id, now=now)

        assert claimed is None
        saved = db.get(Story, story_id)
        assert saved is not None
        assert saved.status is StoryStatus.GENERATION_FAILED
        assert saved.failure_reason == "background_generation_attempts_exhausted"
        assert saved.generation_claim_token is None
        assert saved.generation_claimed_at is None


def test_lock_claim_rejects_a_stale_worker_token(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.story_jobs import (
        GenerationClaimLostError,
        claim_story,
        lock_claim,
    )

    story_id = _queue_story(db_session_factory)
    now = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
    with db_session_factory() as db:
        claimed = claim_story(db, story_id=story_id, now=now)
        assert claimed is not None
        assert claimed.generation_claim_token is not None

        with pytest.raises(GenerationClaimLostError):
            lock_claim(
                db,
                story_id=story_id,
                claim_token=uuid4(),
            )

        saved = db.get(Story, story_id)
        assert saved is not None
        assert saved.generation_claim_token == claimed.generation_claim_token
        assert saved.generation_claimed_at is not None
        assert saved.generation_stage is GenerationStage.STORY_TEXT
