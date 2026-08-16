import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.models import Story, StoryStatus


logger = logging.getLogger(__name__)
STORY_CLAIM_STALE_AFTER = timedelta(minutes=15)
MAX_GENERATION_ATTEMPTS = 5
STORY_CLAIM_HEARTBEAT_INTERVAL_SECONDS = 60.0
STORY_CLAIM_HEARTBEAT_JOIN_TIMEOUT_SECONDS = 1.0


class GenerationClaimLostError(Exception):
    pass


@contextmanager
def maintain_claim(
    session_factory: Callable[[], Session],
    *,
    story_id: uuid.UUID,
    claim_token: uuid.UUID,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[None]:
    """Renew a claim from an independent session during provider calls."""
    heartbeat_stop = Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(
            STORY_CLAIM_HEARTBEAT_INTERVAL_SECONDS
        ):
            if should_stop is not None and should_stop():
                return
            try:
                with session_factory() as heartbeat_db:
                    renew_claim(
                        heartbeat_db,
                        story_id=story_id,
                        claim_token=claim_token,
                    )
            except GenerationClaimLostError:
                return
            except Exception:
                logger.exception("Story claim heartbeat failed.")

    heartbeat_thread = Thread(
        target=heartbeat,
        name="story-claim-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        yield
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(
            timeout=STORY_CLAIM_HEARTBEAT_JOIN_TIMEOUT_SECONDS
        )
        if heartbeat_thread.is_alive():
            logger.warning(
                "Story claim heartbeat is still finishing after stop."
            )


def _claimable_story_conditions(
    stale_before: datetime,
) -> tuple[ColumnElement[bool], ...]:
    return (
        Story.status == StoryStatus.GENERATING,
        Story.generation_attempts < MAX_GENERATION_ATTEMPTS,
        or_(
            Story.generation_claim_token.is_(None),
            Story.generation_claimed_at <= stale_before,
        ),
    )


def _mark_exhausted_stories(
    db: Session,
    *,
    story_id: uuid.UUID | None,
    stale_before: datetime,
) -> None:
    conditions = [
        Story.status == StoryStatus.GENERATING,
        Story.generation_attempts >= MAX_GENERATION_ATTEMPTS,
        or_(
            Story.generation_claim_token.is_(None),
            Story.generation_claimed_at <= stale_before,
        ),
    ]
    if story_id is not None:
        conditions.append(Story.id == story_id)
    db.execute(
        update(Story)
        .where(*conditions)
        .values(
            status=StoryStatus.GENERATION_FAILED,
            failure_reason="background_generation_attempts_exhausted",
            generation_claim_token=None,
            generation_claimed_at=None,
        )
        .execution_options(synchronize_session=False)
    )


def _oldest_claimable_story_id(
    db: Session,
    *,
    stale_before: datetime,
) -> ScalarSelect[uuid.UUID]:
    candidate = aliased(Story)
    candidate_query = (
        select(candidate.id)
        .where(
            candidate.status == StoryStatus.GENERATING,
            candidate.generation_attempts < MAX_GENERATION_ATTEMPTS,
            or_(
                candidate.generation_claim_token.is_(None),
                candidate.generation_claimed_at <= stale_before,
            ),
        )
        .order_by(candidate.created_at, candidate.id)
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        candidate_query = candidate_query.with_for_update(skip_locked=True)
    return candidate_query.scalar_subquery()


def _claim_available_story(
    db: Session,
    *,
    selector: ColumnElement[bool],
    claim_time: datetime,
    stale_before: datetime,
) -> uuid.UUID | None:
    return db.scalar(
        update(Story)
        .where(selector, *_claimable_story_conditions(stale_before))
        .values(
            generation_claim_token=uuid.uuid4(),
            generation_claimed_at=claim_time,
            generation_attempts=Story.generation_attempts + 1,
        )
        .returning(Story.id)
        .execution_options(synchronize_session=False)
    )


def claim_story(
    db: Session,
    *,
    story_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Story | None:
    """Atomically claim one queued story by ID."""
    claim_time = now or datetime.now(timezone.utc)
    stale_before = claim_time - STORY_CLAIM_STALE_AFTER
    _mark_exhausted_stories(
        db,
        story_id=story_id,
        stale_before=stale_before,
    )

    if story_id is None:
        selector = Story.id == _oldest_claimable_story_id(
            db,
            stale_before=stale_before,
        )
    else:
        selector = Story.id == story_id

    claimed_id = _claim_available_story(
        db,
        selector=selector,
        claim_time=claim_time,
        stale_before=stale_before,
    )
    db.commit()
    db.expire_all()
    if claimed_id is None:
        return None
    return db.get(Story, claimed_id)


def renew_claim(
    db: Session,
    *,
    story_id: uuid.UUID,
    claim_token: uuid.UUID,
    now: datetime | None = None,
) -> None:
    """Renew a matching live claim or raise when ownership was lost."""
    result = db.execute(
        update(Story)
        .where(
            Story.id == story_id,
            Story.status == StoryStatus.GENERATING,
            Story.generation_claim_token == claim_token,
        )
        .values(generation_claimed_at=now or datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.expire_all()
    if result.rowcount != 1:
        raise GenerationClaimLostError


def lock_claim(
    db: Session,
    *,
    story_id: uuid.UUID,
    claim_token: uuid.UUID,
) -> Story:
    """Lock a matching live claim until the caller commits or rolls back."""
    locked_id = db.scalar(
        update(Story)
        .where(
            Story.id == story_id,
            Story.status == StoryStatus.GENERATING,
            Story.generation_claim_token == claim_token,
        )
        .values(generation_claimed_at=Story.generation_claimed_at)
        .returning(Story.id)
        .execution_options(synchronize_session=False)
    )
    if locked_id is None:
        raise GenerationClaimLostError
    db.expire_all()
    story = db.get(Story, locked_id)
    if story is None:
        raise GenerationClaimLostError
    return story
