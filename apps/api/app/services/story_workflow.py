import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NoReturn
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    Child,
    GenerationRunStatus,
    GenerationStage,
    Parent,
    Story,
    StoryIdempotencyKey,
    StoryPage,
    StoryStatus,
)
from app.schemas import StoryGenerationResult
from app.services import (
    asset_cleanup,
    moderation_audit,
    safety,
    storage,
    story_jobs,
)
from app.services.cost_tracking import RunCostRecorder
from app.services.illustration import generate_illustration
from app.services.narration import generate_narration
from app.services.story_generation import generate_story
from app.services.story_safety import check_text


logger = logging.getLogger(__name__)


def production_generation_enabled() -> bool:
    return any(
        (
            settings.story_provider.strip().lower() == "claude",
            settings.safety_provider.strip().lower() == "openai",
            settings.image_gen_provider.strip().lower() == "flux",
            settings.tts_provider.strip().lower() == "elevenlabs",
        )
    )


class ChildNotFoundError(Exception):
    pass


class StoryNotFoundError(Exception):
    pass


class StoryNotPendingReviewError(Exception):
    pass


class StoryPageNotFoundError(Exception):
    pass


class UnsafeStoryEditError(Exception):
    pass


class FreeStoryLimitReachedError(Exception):
    pass


class StoryNarrationGenerationError(Exception):
    pass


class StoryRegenerationError(Exception):
    pass


class ReferencePhotoRequiredError(Exception):
    pass


class IllustrationProviderNotConfiguredError(Exception):
    pass


class SafetyProviderNotConfiguredError(Exception):
    pass


class StoryProviderNotConfiguredError(Exception):
    pass


class NarrationProviderNotConfiguredError(Exception):
    pass


class GenerationWorkerStoppingError(Exception):
    pass


def _worker_is_stopping(
    should_stop: Callable[[], bool] | None,
) -> bool:
    return should_stop is not None and should_stop()


@dataclass(slots=True)
class _GenerationJob:
    db: Session
    story: Story | None
    claim_token: UUID | None
    should_stop: Callable[[], bool] | None
    cost_recorder: RunCostRecorder = field(init=False)
    created_asset_references: list[str | None] = field(
        default_factory=list,
        init=False,
    )
    _asset_cleanup_enabled: bool = field(default=False, init=False)
    _interruption_finalized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.cost_recorder = RunCostRecorder.start(self.db)

    def finalize_interruption(self) -> None:
        if self._interruption_finalized:
            return
        self._interruption_finalized = True
        _finalize_failed_run(
            db=self.db,
            cost_recorder=self.cost_recorder,
        )
        if self._asset_cleanup_enabled and self.story is not None:
            _cleanup_unpersisted_story_assets(
                db=self.db,
                story_id=self.story.id,
                references=self.created_asset_references,
            )

    def begin_asset_generation(self) -> None:
        self._asset_cleanup_enabled = True

    def record_asset(self, reference: str | None) -> None:
        self.created_asset_references.append(reference)

    def renew(self) -> None:
        try:
            if _worker_is_stopping(self.should_stop):
                raise GenerationWorkerStoppingError
            if self.story is not None and self.claim_token is not None:
                story_jobs.renew_claim(
                    self.db,
                    story_id=self.story.id,
                    claim_token=self.claim_token,
                )
        except (
            story_jobs.GenerationClaimLostError,
            GenerationWorkerStoppingError,
        ):
            self.finalize_interruption()
            raise

    def prepare_terminal(self, *, complete: bool = False) -> Story | None:
        try:
            if _worker_is_stopping(self.should_stop):
                raise GenerationWorkerStoppingError
            if self.story is None or self.claim_token is None:
                return self.story
            self.story = story_jobs.lock_claim(
                self.db,
                story_id=self.story.id,
                claim_token=self.claim_token,
            )
            self.story.generation_claim_token = None
            self.story.generation_claimed_at = None
            if complete:
                self.story.generation_stage = GenerationStage.COMPLETE
            return self.story
        except (
            story_jobs.GenerationClaimLostError,
            GenerationWorkerStoppingError,
        ):
            self.finalize_interruption()
            raise


def _validate_story_request() -> None:
    provider = settings.story_provider.strip().lower()
    if provider not in {"stub", "claude", "ollama"}:
        raise StoryProviderNotConfiguredError
    if provider == "claude" and (
        not settings.anthropic_api_key
        or not settings.anthropic_api_key.strip()
    ):
        raise StoryProviderNotConfiguredError


def _validate_illustration_request(
    child: Child,
    *,
    require_supported_provider: bool = False,
) -> None:
    provider = settings.image_gen_provider.strip().lower()
    if require_supported_provider and provider not in {"stub", "flux"}:
        raise IllustrationProviderNotConfiguredError
    if provider != "flux":
        return
    if not child.reference_photo_ref:
        raise ReferencePhotoRequiredError
    if (
        not settings.image_gen_api_key
        or not settings.image_gen_api_key.strip()
    ):
        raise IllustrationProviderNotConfiguredError


def _validate_safety_request() -> None:
    if settings.safety_provider not in {"stub", "openai"}:
        raise SafetyProviderNotConfiguredError
    if settings.safety_provider == "openai" and (
        not settings.openai_api_key
        or not settings.openai_api_key.strip()
    ):
        raise SafetyProviderNotConfiguredError


def _validate_narration_request() -> None:
    provider = settings.tts_provider.strip().lower()
    if provider not in {"stub", "elevenlabs"}:
        raise NarrationProviderNotConfiguredError
    if provider == "elevenlabs" and (
        not settings.paid_tts_enabled
        or not settings.elevenlabs_api_key
        or not settings.elevenlabs_api_key.strip()
        or not settings.elevenlabs_voice_id
        or not settings.elevenlabs_voice_id.strip()
    ):
        raise NarrationProviderNotConfiguredError


def _validate_generation_request(child: Child) -> None:
    _validate_story_request()
    _validate_illustration_request(
        child,
        require_supported_provider=True,
    )
    _validate_safety_request()
    _validate_narration_request()


def _cleanup_generated_assets(
    references: Iterable[str | None],
) -> tuple[str, ...]:
    failed_references: list[str] = []
    for reference in dict.fromkeys(references):
        if reference is None or not storage.is_managed_reference(reference):
            continue
        try:
            storage.delete_object(reference)
        except Exception:
            failed_references.append(reference)
            logger.exception(
                "Generated asset cleanup failed."
            )
    return tuple(failed_references)


def _cleanup_unpersisted_story_assets(
    *,
    db: Session,
    story_id: UUID,
    references: Iterable[str | None],
) -> None:
    candidates = tuple(dict.fromkeys(references))
    db.rollback()
    try:
        persisted_references = {
            reference
            for image_url, audio_url in db.execute(
                select(
                    StoryPage.image_url,
                    StoryPage.audio_url,
                ).where(StoryPage.story_id == story_id)
            )
            for reference in (image_url, audio_url)
        }
    except Exception:
        db.rollback()
        logger.exception(
            "Could not verify generated asset persistence after failure."
        )
        return
    failed_references = _cleanup_generated_assets(
        reference
        for reference in candidates
        if reference not in persisted_references
    )
    if not failed_references:
        return
    try:
        asset_cleanup.queue_references(db, failed_references)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Could not retain failed generated asset cleanup for retry."
        )


def _finalize_failed_run(
    *,
    db: Session,
    cost_recorder: RunCostRecorder,
) -> bool:
    try:
        cost_recorder.finalize(status=GenerationRunStatus.FAILED)
    except Exception:
        db.rollback()
        logger.exception(
            "failed to finalize generation cost run %s",
            cost_recorder.run_id,
        )
        return False
    return True


def _finalize_failed_story(
    *,
    db: Session,
    story: Story,
    cost_recorder: RunCostRecorder,
    cleanup_references: Iterable[str | None],
) -> None:
    references = tuple(dict.fromkeys(cleanup_references))
    asset_cleanup.queue_references(db, references)
    if not _finalize_failed_run(db=db, cost_recorder=cost_recorder):
        db.add(story)
        asset_cleanup.queue_references(db, references)
        db.commit()
        db.refresh(story)
    asset_cleanup.try_process_pending_deletions(db)


def _finalize_failed_generation_story(
    *,
    db: Session,
    story: Story,
    child: Child,
    event_text: str,
    failure_reason: str,
    cost_recorder: RunCostRecorder,
    cleanup_references: Iterable[str | None],
    claim_token: UUID | None = None,
) -> Story:
    references = tuple(dict.fromkeys(cleanup_references))
    asset_cleanup.queue_references(db, references)
    if not _finalize_failed_run(db=db, cost_recorder=cost_recorder):
        story = _restore_failed_story(
            db=db,
            story_id=story.id,
            child=child,
            event_text=event_text,
            failure_reason=failure_reason,
            claim_token=claim_token,
        )
        asset_cleanup.queue_references(db, references)
        db.commit()
        db.refresh(story)
    asset_cleanup.try_process_pending_deletions(db)
    return story


def _raise_for_unmatched_pending_story(
    *,
    db: Session,
    story_id: UUID,
) -> NoReturn:
    story_exists = db.scalar(
        select(Story.id).where(Story.id == story_id)
    )
    db.rollback()
    if story_exists is None:
        raise StoryNotFoundError
    raise StoryNotPendingReviewError


def _raise_for_regeneration_failure(
    *,
    db: Session,
    story_id: UUID,
    error: Exception,
    cost_recorder: RunCostRecorder,
    cleanup_references: Iterable[str | None] = (),
) -> NoReturn:
    references = tuple(dict.fromkeys(cleanup_references))
    failure_result = db.execute(
        update(Story)
        .where(
            Story.id == story_id,
            Story.status == StoryStatus.PENDING_REVIEW,
        )
        .values(failure_reason="story_regeneration_failed")
        .execution_options(synchronize_session=False)
    )
    if failure_result.rowcount == 0:
        asset_cleanup.queue_references(db, references)
        if not _finalize_failed_run(db=db, cost_recorder=cost_recorder):
            asset_cleanup.queue_references(db, references)
            db.commit()
        asset_cleanup.try_process_pending_deletions(db)
        _raise_for_unmatched_pending_story(db=db, story_id=story_id)
    db.flush()
    db.expire_all()
    asset_cleanup.queue_references(db, references)
    if not _finalize_failed_run(db=db, cost_recorder=cost_recorder):
        retry_result = db.execute(
            update(Story)
            .where(
                Story.id == story_id,
                Story.status == StoryStatus.PENDING_REVIEW,
            )
            .values(failure_reason="story_regeneration_failed")
            .execution_options(synchronize_session=False)
        )
        if retry_result.rowcount == 0:
            _raise_for_unmatched_pending_story(db=db, story_id=story_id)
        asset_cleanup.queue_references(db, references)
        db.commit()
    asset_cleanup.try_process_pending_deletions(db)
    raise StoryRegenerationError from error


def _raise_for_stale_generation_action(
    *,
    db: Session,
    story: Story,
    cost_recorder: RunCostRecorder,
) -> NoReturn:
    _finalize_failed_run(db=db, cost_recorder=cost_recorder)
    _raise_for_unmatched_pending_story(db=db, story_id=story.id)


def _persist_rejected_story(
    *,
    db: Session,
    child: Child,
    event_text: str,
    failure_reason: str | None,
    title: str = "",
    safety_reason: str | None = None,
    story: Story | None = None,
) -> Story:
    if story is None:
        story = Story(child_id=child.id, event_text=event_text)
    story.title = title
    story.language = child.language
    story.status = StoryStatus.REJECTED
    story.failure_reason = failure_reason
    story.safety_reason = safety_reason
    db.add(story)
    db.flush()
    return story


def _moderation_failure_reason(
    decision: safety.SafetyDecision,
) -> str:
    if decision.flagged_item_kind == "title":
        return "safety_generated_title_blocked"
    return (
        "safety_generated_page_"
        f"{decision.flagged_page_number}_blocked"
    )


def _finalize_rejected_run(
    *,
    cost_recorder: RunCostRecorder,
    story: Story,
) -> None:
    cost_recorder.finalize(
        status=GenerationRunStatus.REJECTED,
        story=story,
        refresh_story=False,
    )


def _persist_moderated_rejection(
    *,
    db: Session,
    child: Child,
    event_text: str,
    title: str,
    decision: safety.SafetyDecision,
    cost_recorder: RunCostRecorder,
    story: Story | None = None,
) -> Story:
    try:
        story = _persist_rejected_story(
            db=db,
            child=child,
            event_text=event_text,
            title=(
                "" if decision.flagged_item_kind == "title" else title
            ),
            failure_reason=_moderation_failure_reason(decision),
            safety_reason=decision.reason_code,
            story=story,
        )
        moderation_audit.add_record(db, story, decision)
        _finalize_rejected_run(
            cost_recorder=cost_recorder,
            story=story,
        )
    except Exception:
        db.rollback()
        _finalize_failed_run(db=db, cost_recorder=cost_recorder)
        raise safety.SafetyReviewUnavailable(
            "safety review is unavailable"
        ) from None
    return story


def _persist_failed_story(
    *,
    db: Session,
    child: Child,
    event_text: str,
    failure_reason: str,
    story: Story | None = None,
) -> Story:
    if story is None:
        story = Story(child_id=child.id, event_text=event_text, title="")
    story.language = child.language
    story.status = StoryStatus.GENERATION_FAILED
    story.failure_reason = failure_reason
    db.add(story)
    db.flush()
    db.refresh(story)
    return story


def _restore_failed_story(
    *,
    db: Session,
    story_id: UUID,
    child: Child,
    event_text: str,
    failure_reason: str,
    claim_token: UUID | None = None,
) -> Story:
    statement = update(Story).where(Story.id == story_id)
    if claim_token is not None:
        statement = statement.where(
            Story.status == StoryStatus.GENERATING,
            Story.generation_claim_token == claim_token,
        )
    result = db.execute(
        statement
        .values(
            language=child.language,
            status=StoryStatus.GENERATION_FAILED,
            failure_reason=failure_reason,
            generation_claim_token=(
                None if claim_token is not None else Story.generation_claim_token
            ),
            generation_claimed_at=(
                None if claim_token is not None else Story.generation_claimed_at
            ),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        if claim_token is not None:
            raise story_jobs.GenerationClaimLostError
        db.add(
            Story(
                id=story_id,
                child_id=child.id,
                event_text=event_text,
                title="",
                language=child.language,
                status=StoryStatus.GENERATION_FAILED,
                failure_reason=failure_reason,
            )
        )
        db.flush()
    db.expire_all()
    restored_story = db.get(Story, story_id)
    if restored_story is None:
        raise RuntimeError("failed story could not be restored")
    return restored_story


def _purge_expired_idempotency_keys(
    *,
    db: Session,
    parent_id: UUID,
) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.idempotency_key_ttl_hours
    )
    db.execute(
        delete(StoryIdempotencyKey).where(
            StoryIdempotencyKey.parent_id == parent_id,
            StoryIdempotencyKey.created_at < cutoff,
        )
    )


def _record_idempotency_key(
    *,
    db: Session,
    parent_id: UUID,
    key: str,
    story: Story,
) -> None:
    _purge_expired_idempotency_keys(db=db, parent_id=parent_id)
    db.add(
        StoryIdempotencyKey(
            parent_id=parent_id,
            key=key,
            story_id=story.id,
        )
    )


def _find_idempotency_story(
    *,
    db: Session,
    parent_id: UUID,
    key: str,
) -> Story | None:
    key_row = db.scalar(
        select(StoryIdempotencyKey).where(
            StoryIdempotencyKey.parent_id == parent_id,
            StoryIdempotencyKey.key == key,
        )
    )
    if key_row is None:
        return None
    story = db.scalar(
        select(Story)
        .where(Story.id == key_row.story_id)
        .options(selectinload(Story.pages))
    )
    if story is None:
        db.delete(key_row)
        db.commit()
        return None
    return story


def _reserve_free_story_usage(*, db: Session, parent: Parent) -> bool:
    if parent.is_subscribed:
        return False

    result = db.execute(
        update(Parent)
        .where(
            Parent.id == parent.id,
            Parent.is_subscribed.is_(False),
            Parent.free_stories_used < settings.free_stories_limit,
        )
        .values(free_stories_used=Parent.free_stories_used + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        db.rollback()
        db.refresh(parent)
        if parent.is_subscribed:
            return False
        raise FreeStoryLimitReachedError

    db.commit()
    db.refresh(parent)
    return True


def _release_free_story_usage(*, db: Session, parent: Parent) -> None:
    db.rollback()
    db.execute(
        update(Parent)
        .where(
            Parent.id == parent.id,
            Parent.free_stories_used > 0,
        )
        .values(free_stories_used=Parent.free_stories_used - 1)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(parent)


def queue_story(
    *,
    db: Session,
    child_id: UUID,
    event_text: str,
    idempotency_key: str | None = None,
) -> Story:
    child = db.get(Child, child_id)
    if child is None:
        raise ChildNotFoundError
    _validate_generation_request(child)

    story = Story(
        child_id=child.id,
        event_text=event_text,
        title="",
        language=child.language,
        status=StoryStatus.GENERATING,
    )
    db.add(story)
    if idempotency_key is not None:
        db.flush()
        _record_idempotency_key(
            db=db,
            parent_id=child.parent_id,
            key=idempotency_key,
            story=story,
        )
    db.commit()
    db.refresh(story)
    return story


def _create_story_or_replay_race(
    *,
    db: Session,
    child: Child,
    event_text: str,
    idempotency_key: str | None,
) -> tuple[Story, bool]:
    if idempotency_key is None:
        if production_generation_enabled():
            return (
                queue_story(
                    db=db,
                    child_id=child.id,
                    event_text=event_text,
                ),
                True,
            )
        return (
            create_story(
                db=db,
                child_id=child.id,
                event_text=event_text,
            ),
            True,
        )

    story: Story | None = None
    try:
        if production_generation_enabled():
            story = queue_story(
                db=db,
                child_id=child.id,
                event_text=event_text,
                idempotency_key=idempotency_key,
            )
        else:
            story = create_story(
                db=db,
                child_id=child.id,
                event_text=event_text,
            )
            _record_idempotency_key(
                db=db,
                parent_id=child.parent_id,
                key=idempotency_key,
                story=story,
            )
            db.commit()
    except IntegrityError:
        db.rollback()
        if story is not None:
            db.delete(story)
            db.commit()
        existing = _find_idempotency_story(
            db=db,
            parent_id=child.parent_id,
            key=idempotency_key,
        )
        if existing is None:
            raise
        return existing, False
    assert story is not None
    return story, True


def create_story_with_idempotency(
    *,
    db: Session,
    child_id: UUID,
    event_text: str,
    idempotency_key: str | None,
) -> tuple[Story, bool]:
    """Create a story, or replay the existing story for a repeated key.

    Returns the story and whether this call created it. The idempotency key
    is scoped to the parent who owns the child, so a retry returns the
    original story instead of queueing a duplicate.
    """
    child = db.get(Child, child_id)
    if child is None:
        raise ChildNotFoundError
    parent = db.get(Parent, child.parent_id)
    if parent is None:
        raise ChildNotFoundError

    if idempotency_key is not None:
        existing = _find_idempotency_story(
            db=db,
            parent_id=child.parent_id,
            key=idempotency_key,
        )
        if existing is not None:
            return existing, False

    try:
        reserved_usage = _reserve_free_story_usage(db=db, parent=parent)
    except FreeStoryLimitReachedError:
        if idempotency_key is not None:
            existing = _find_idempotency_story(
                db=db,
                parent_id=child.parent_id,
                key=idempotency_key,
            )
            if existing is not None:
                return existing, False
        raise

    created = False
    try:
        story, created = _create_story_or_replay_race(
            db=db,
            child=child,
            event_text=event_text,
            idempotency_key=idempotency_key,
        )
        return story, created
    finally:
        if reserved_usage and not created:
            _release_free_story_usage(db=db, parent=parent)


def process_queued_story(
    session_factory: Callable[[], Session],
    story_id: UUID | None = None,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    if _worker_is_stopping(should_stop):
        return False
    with session_factory() as db:
        story = story_jobs.claim_story(db, story_id=story_id)
        if story is None or story.generation_claim_token is None:
            return False
        story_id = story.id
        claim_token = story.generation_claim_token
        try:
            child = db.get(Child, story.child_id)
            if child is None:
                return True
            _validate_generation_request(child)
            with story_jobs.maintain_claim(
                session_factory,
                story_id=story_id,
                claim_token=claim_token,
                should_stop=should_stop,
            ):
                _generate_story_content(
                    db=db,
                    child=child,
                    event_text=story.event_text,
                    story=story,
                    claim_token=claim_token,
                    should_stop=should_stop,
                    persist_progress=True,
                )
        except Exception as error:
            db.rollback()
            terminal_status = db.scalar(
                select(Story.status).where(Story.id == story_id)
            )
            if (
                terminal_status is not None
                and terminal_status is not StoryStatus.GENERATING
            ):
                logger.warning(
                    "Background story generation ended with status %s "
                    "for story %s after category %s.",
                    terminal_status.value,
                    story_id,
                    type(error).__name__,
                )
                return True
            logger.error(
                "Background story generation will retry story %s "
                "with category %s.",
                story_id,
                type(error).__name__,
            )
        return True


def process_pending_stories(
    session_factory: Callable[[], Session],
    *,
    limit: int = 1,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Process up to ``limit`` queued or stale-claimed stories."""
    if limit < 1:
        raise ValueError("limit must be positive")
    handled = 0
    for _ in range(limit):
        if not process_queued_story(
            session_factory,
            should_stop=should_stop,
        ):
            break
        handled += 1
    return handled


def try_process_pending_stories(
    session_factory: Callable[[], Session],
    *,
    limit: int = 1,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Run a recovery pass without allowing it to stop the worker loop."""
    try:
        return process_pending_stories(
            session_factory,
            limit=limit,
            should_stop=should_stop,
        )
    except Exception:
        logger.exception("Background story recovery pass failed.")
        return 0


def _prepare_generation_pages(
    *,
    db: Session,
    story: Story | None,
    generated: StoryGenerationResult | None,
    persist_progress: bool,
) -> list[StoryPage]:
    if generated is None:
        assert story is not None
        return list(
            db.scalars(
                select(StoryPage)
                .where(StoryPage.story_id == story.id)
                .order_by(StoryPage.page_number)
            )
        )

    pages = [
        StoryPage(page_number=page_number, text=page_text)
        for page_number, page_text in enumerate(generated.pages, start=1)
    ]
    if story is None:
        return pages

    story.pages = pages
    if not persist_progress:
        return pages

    story.title = generated.title
    story.generation_stage = GenerationStage.ILLUSTRATIONS
    db.add(story)
    db.commit()
    db.refresh(story)
    return list(
        db.scalars(
            select(StoryPage)
            .where(StoryPage.story_id == story.id)
            .order_by(StoryPage.page_number)
        )
    )


def _run_illustration_stage(
    *,
    job: _GenerationJob,
    child: Child,
    pages: list[StoryPage],
    persist_progress: bool,
) -> None:
    job.begin_asset_generation()
    try:
        for page in pages:
            if page.image_url is not None:
                continue
            job.renew()
            page.image_url = generate_illustration(
                avatar_seed=str(child.id),
                page_number=page.page_number,
                page_text=page.text,
                reference_photo_ref=child.reference_photo_ref,
                recorder=job.cost_recorder,
            )
            job.record_asset(page.image_url)
            if persist_progress:
                job.db.commit()
    except (
        story_jobs.GenerationClaimLostError,
        GenerationWorkerStoppingError,
    ):
        job.finalize_interruption()
        raise
    except Exception as error:
        job.record_asset(
            getattr(error, "created_reference", None),
        )
        raise

    if persist_progress and job.story is not None:
        job.story.generation_stage = GenerationStage.NARRATION
        job.db.commit()


def _run_narration_stage(
    *,
    job: _GenerationJob,
    child: Child,
    pages: list[StoryPage],
    persist_progress: bool,
) -> None:
    try:
        for page in pages:
            if page.audio_url is not None:
                continue
            job.renew()
            page.audio_url = generate_narration(
                text=page.text,
                language=child.language,
                recorder=job.cost_recorder,
            )
            job.record_asset(page.audio_url)
            if persist_progress:
                job.db.commit()
    except (
        story_jobs.GenerationClaimLostError,
        GenerationWorkerStoppingError,
    ):
        job.finalize_interruption()
        raise


def _persist_media_generation_failure(
    *,
    job: _GenerationJob,
    child: Child,
    event_text: str,
    failure_reason: str,
) -> Story:
    story = job.prepare_terminal()
    story = _persist_failed_story(
        db=job.db,
        child=child,
        event_text=event_text,
        failure_reason=failure_reason,
        story=story,
    )
    return _finalize_failed_generation_story(
        db=job.db,
        story=story,
        child=child,
        event_text=event_text,
        failure_reason=failure_reason,
        cost_recorder=job.cost_recorder,
        cleanup_references=job.created_asset_references,
        claim_token=job.claim_token,
    )


def _generate_story_content(
    *,
    db: Session,
    child: Child,
    event_text: str,
    story: Story | None = None,
    claim_token: UUID | None = None,
    should_stop: Callable[[], bool] | None = None,
    persist_progress: bool = False,
) -> Story:
    job = _GenerationJob(
        db=db,
        story=story,
        claim_token=claim_token,
        should_stop=should_stop,
    )
    job.renew()

    resume_stage = (
        story.generation_stage
        if story is not None
        else GenerationStage.STORY_TEXT
    )
    generated: StoryGenerationResult | None = None
    if resume_stage is GenerationStage.STORY_TEXT:
        try:
            safety_result = check_text(event_text)
        except Exception:
            _finalize_failed_run(
                db=db,
                cost_recorder=job.cost_recorder,
            )
            raise
        if not safety_result.is_safe:
            story = job.prepare_terminal()
            story = _persist_rejected_story(
                db=db,
                child=child,
                event_text=event_text,
                failure_reason=safety_result.reason,
                safety_reason="unsafe_content",
                story=story,
            )
            job.cost_recorder.finalize(
                status=GenerationRunStatus.REJECTED,
                story=story,
            )
            return story

        try:
            job.renew()
            generated = generate_story(
                child_name=child.name,
                age=child.age,
                interests=child.interests,
                event_text=event_text,
                language=child.language,
                recorder=job.cost_recorder,
                before_provider_call=job.renew,
            )
            job.renew()
        except (
            story_jobs.GenerationClaimLostError,
            GenerationWorkerStoppingError,
        ):
            job.finalize_interruption()
            raise
        except Exception:
            story = job.prepare_terminal()
            story = _persist_failed_story(
                db=db,
                child=child,
                event_text=event_text,
                failure_reason="story_generation_failed",
                story=story,
            )
            if not _finalize_failed_run(
                db=db,
                cost_recorder=job.cost_recorder,
            ):
                story = _restore_failed_story(
                    db=db,
                    story_id=story.id,
                    child=child,
                    event_text=event_text,
                    failure_reason="story_generation_failed",
                    claim_token=claim_token,
                )
                db.commit()
                db.refresh(story)
            return story

        try:
            job.renew()
            generated_safety = safety.check_story(
                generated.title,
                generated.pages,
                recorder=job.cost_recorder,
            )
            job.renew()
        except (
            story_jobs.GenerationClaimLostError,
            GenerationWorkerStoppingError,
        ):
            job.finalize_interruption()
            raise
        except Exception:
            _finalize_failed_run(
                db=db,
                cost_recorder=job.cost_recorder,
            )
            raise
        if not generated_safety.is_safe:
            story = job.prepare_terminal()
            return _persist_moderated_rejection(
                db=db,
                child=child,
                event_text=event_text,
                title=generated.title,
                decision=generated_safety,
                cost_recorder=job.cost_recorder,
                story=story,
            )

    pages = _prepare_generation_pages(
        db=db,
        story=story,
        generated=generated,
        persist_progress=persist_progress,
    )

    try:
        _run_illustration_stage(
            job=job,
            child=child,
            pages=pages,
            persist_progress=persist_progress,
        )
    except (
        story_jobs.GenerationClaimLostError,
        GenerationWorkerStoppingError,
    ):
        raise
    except Exception:
        return _persist_media_generation_failure(
            job=job,
            child=child,
            event_text=event_text,
            failure_reason="illustration_generation_failed",
        )

    try:
        _run_narration_stage(
            job=job,
            child=child,
            pages=pages,
            persist_progress=persist_progress,
        )
    except (
        story_jobs.GenerationClaimLostError,
        GenerationWorkerStoppingError,
    ):
        raise
    except Exception:
        return _persist_media_generation_failure(
            job=job,
            child=child,
            event_text=event_text,
            failure_reason="narration_generation_failed",
        )

    story = job.prepare_terminal(complete=True)
    if story is None:
        story = Story(child_id=child.id, event_text=event_text)
    if generated is not None:
        story.title = generated.title
    story.language = child.language
    story.status = StoryStatus.PENDING_REVIEW
    story.failure_reason = None
    story.safety_reason = None
    story.generation_stage = GenerationStage.COMPLETE
    story.pages = pages
    try:
        db.add(story)
        db.flush()
        job.cost_recorder.finalize(
            status=GenerationRunStatus.SUCCEEDED,
            story=story,
        )
    except Exception:
        story_id = story.id
        _cleanup_unpersisted_story_assets(
            db=db,
            story_id=story_id,
            references=job.created_asset_references,
        )
        raise
    return story


def create_story(
    *,
    db: Session,
    child_id: UUID,
    event_text: str,
) -> Story:
    child = db.get(Child, child_id)
    if child is None:
        raise ChildNotFoundError
    _validate_illustration_request(child)
    _validate_safety_request()
    return _generate_story_content(
        db=db,
        child=child,
        event_text=event_text,
    )


def list_stories(
    *,
    db: Session,
    child_id: UUID,
) -> list[Story]:
    child = db.get(Child, child_id)
    if child is None:
        raise ChildNotFoundError

    stories = db.scalars(
        select(Story)
        .where(Story.child_id == child.id)
        .options(selectinload(Story.pages))
        .order_by(Story.created_at.desc(), Story.id.desc())
    )
    return list(stories)


def list_approved_stories(
    *,
    db: Session,
    child_id: UUID,
) -> list[Story]:
    child = db.get(Child, child_id)
    if child is None:
        raise ChildNotFoundError

    stories = db.scalars(
        select(Story)
        .where(
            Story.child_id == child.id,
            Story.status == StoryStatus.APPROVED,
        )
        .options(selectinload(Story.pages))
        .order_by(Story.created_at.desc(), Story.id.desc())
    )
    return list(stories)


def get_approved_story(
    *,
    db: Session,
    child_id: UUID,
    story_id: UUID,
) -> Story:
    story = db.scalar(
        select(Story)
        .where(
            Story.id == story_id,
            Story.child_id == child_id,
            Story.status == StoryStatus.APPROVED,
        )
        .options(selectinload(Story.pages))
    )
    if story is None:
        raise StoryNotFoundError

    return story


def get_story(
    *,
    db: Session,
    story_id: UUID,
) -> Story:
    story = db.scalar(
        select(Story)
        .where(Story.id == story_id)
        .options(selectinload(Story.pages))
    )
    if story is None:
        raise StoryNotFoundError

    return story


def update_story(
    *,
    db: Session,
    story_id: UUID,
    title: str | None,
    pages: dict[int, str],
) -> Story:
    story = db.scalar(
        select(Story)
        .where(Story.id == story_id)
        .options(selectinload(Story.pages))
    )
    if story is None:
        raise StoryNotFoundError
    if story.status is not StoryStatus.PENDING_REVIEW:
        raise StoryNotPendingReviewError

    stored_page_numbers = {page.page_number for page in story.pages}
    if not set(pages).issubset(stored_page_numbers):
        db.rollback()
        raise StoryPageNotFoundError

    safety_result = safety.check_story(
        title if title is not None else story.title,
        [
            pages.get(page.page_number, page.text) for page in story.pages
        ],
    )
    if not safety_result.is_safe:
        db.rollback()
        raise UnsafeStoryEditError

    cost_recorder = None
    narration_urls: dict[int, str] = {}
    created_audio_references: list[str] = []
    previous_audio_references = [
        page.audio_url
        for page in story.pages
        if page.page_number in pages
    ]
    if pages:
        cost_recorder = RunCostRecorder.start(db)
        try:
            for page_number, page_text in pages.items():
                audio_url = generate_narration(
                    text=page_text,
                    language=story.language,
                    recorder=cost_recorder,
                )
                narration_urls[page_number] = audio_url
                created_audio_references.append(audio_url)
        except Exception as error:
            _finalize_failed_story(
                db=db,
                story=story,
                cost_recorder=cost_recorder,
                cleanup_references=created_audio_references,
            )
            raise StoryNarrationGenerationError from error

    try:
        update_result = db.execute(
            update(Story)
            .where(
                Story.id == story_id,
                Story.status == StoryStatus.PENDING_REVIEW,
            )
            .values(
                title=title if title is not None else Story.title,
                failure_reason=None,
            )
            .execution_options(synchronize_session=False)
        )
        if update_result.rowcount == 0:
            if cost_recorder is not None:
                _raise_for_stale_generation_action(
                    db=db,
                    story=story,
                    cost_recorder=cost_recorder,
                )
            _raise_for_unmatched_pending_story(db=db, story_id=story_id)

        for page_number, page_text in pages.items():
            db.execute(
                update(StoryPage)
                .where(
                    StoryPage.story_id == story_id,
                    StoryPage.page_number == page_number,
                )
                .values(
                    text=page_text,
                    audio_url=narration_urls[page_number],
                )
                .execution_options(synchronize_session=False)
            )

        db.flush()
        db.expire(story)
        updated_story = get_story(db=db, story_id=story_id)
        if cost_recorder is not None:
            current_audio_references = set(narration_urls.values())
            asset_cleanup.queue_references(
                db,
                (
                    reference
                    for reference in previous_audio_references
                    if reference not in current_audio_references
                ),
            )
            cost_recorder.finalize(
                status=GenerationRunStatus.SUCCEEDED,
                story=updated_story,
            )
        else:
            db.commit()
    except Exception:
        _cleanup_unpersisted_story_assets(
            db=db,
            story_id=story_id,
            references=created_audio_references,
        )
        raise

    if cost_recorder is not None:
        asset_cleanup.try_process_pending_deletions(db)
    return updated_story


def _reject_regenerated_story(
    *,
    db: Session,
    story: Story,
    generated_title: str,
    decision: safety.SafetyDecision,
    cost_recorder: RunCostRecorder,
) -> Story:
    try:
        rejection_result = db.execute(
            update(Story)
            .where(
                Story.id == story.id,
                Story.status == StoryStatus.PENDING_REVIEW,
            )
            .values(
                title=(
                    ""
                    if decision.flagged_item_kind == "title"
                    else generated_title
                ),
                status=StoryStatus.REJECTED,
                failure_reason=_moderation_failure_reason(decision),
                safety_reason=decision.reason_code,
            )
            .execution_options(synchronize_session=False)
        )
        if rejection_result.rowcount == 0:
            _raise_for_stale_generation_action(
                db=db,
                story=story,
                cost_recorder=cost_recorder,
            )

        previous_asset_references = [
            reference
            for image_url, audio_url in db.execute(
                select(
                    StoryPage.image_url,
                    StoryPage.audio_url,
                ).where(StoryPage.story_id == story.id)
            )
            for reference in (image_url, audio_url)
        ]
        db.execute(
            delete(StoryPage).where(StoryPage.story_id == story.id)
        )
        db.flush()
        db.expire(story)
        rejected_story = get_story(db=db, story_id=story.id)
        moderation_audit.add_record(db, rejected_story, decision)
        asset_cleanup.queue_references(db, previous_asset_references)
        _finalize_rejected_run(
            cost_recorder=cost_recorder,
            story=rejected_story,
        )
    except (StoryNotFoundError, StoryNotPendingReviewError):
        raise
    except Exception:
        db.rollback()
        _finalize_failed_run(db=db, cost_recorder=cost_recorder)
        raise safety.SafetyReviewUnavailable(
            "safety review is unavailable"
        ) from None

    asset_cleanup.try_process_pending_deletions(db)
    return rejected_story


def regenerate_story(
    *,
    db: Session,
    story_id: UUID,
) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError
    if story.status is not StoryStatus.PENDING_REVIEW:
        raise StoryNotPendingReviewError

    child = story.child
    _validate_illustration_request(child)
    _validate_safety_request()
    cost_recorder = RunCostRecorder.start(db)
    try:
        generated = generate_story(
            child_name=child.name,
            age=child.age,
            interests=child.interests,
            event_text=story.event_text,
            language=story.language,
            recorder=cost_recorder,
        )
    except Exception as error:
        _raise_for_regeneration_failure(
            db=db,
            story_id=story_id,
            error=error,
            cost_recorder=cost_recorder,
        )

    try:
        generated_safety = safety.check_story(
            generated.title,
            generated.pages,
            recorder=cost_recorder,
        )
    except Exception:
        _finalize_failed_run(db=db, cost_recorder=cost_recorder)
        raise
    if not generated_safety.is_safe:
        return _reject_regenerated_story(
            db=db,
            story=story,
            generated_title=generated.title,
            decision=generated_safety,
            cost_recorder=cost_recorder,
        )

    previous_asset_references = [
        reference
        for page in story.pages
        for reference in (page.image_url, page.audio_url)
    ]
    created_asset_references: list[str] = []
    regenerated_pages: list[StoryPage] = []
    try:
        for page_number, page_text in enumerate(
            generated.pages,
            start=1,
        ):
            image_url = generate_illustration(
                avatar_seed=str(child.id),
                page_number=page_number,
                page_text=page_text,
                reference_photo_ref=child.reference_photo_ref,
                recorder=cost_recorder,
            )
            created_asset_references.append(image_url)
            audio_url = generate_narration(
                text=page_text,
                language=story.language,
                recorder=cost_recorder,
            )
            created_asset_references.append(audio_url)
            regenerated_pages.append(
                StoryPage(
                    story_id=story_id,
                    page_number=page_number,
                    text=page_text,
                    image_url=image_url,
                    audio_url=audio_url,
                )
            )
    except Exception as error:
        created_reference = getattr(error, "created_reference", None)
        if isinstance(created_reference, str):
            created_asset_references.append(created_reference)
        _raise_for_regeneration_failure(
            db=db,
            story_id=story_id,
            error=error,
            cost_recorder=cost_recorder,
            cleanup_references=created_asset_references,
        )

    try:
        regeneration_result = db.execute(
            update(Story)
            .where(
                Story.id == story_id,
                Story.status == StoryStatus.PENDING_REVIEW,
            )
            .values(
                title=generated.title,
                failure_reason=None,
                safety_reason=None,
            )
            .execution_options(synchronize_session=False)
        )
        if regeneration_result.rowcount == 0:
            _raise_for_stale_generation_action(
                db=db,
                story=story,
                cost_recorder=cost_recorder,
            )

        db.execute(delete(StoryPage).where(StoryPage.story_id == story_id))
        db.add_all(regenerated_pages)
        db.flush()
        db.expire(story)
        regenerated_story = get_story(db=db, story_id=story_id)
        current_asset_references = {
            reference
            for page in regenerated_pages
            for reference in (page.image_url, page.audio_url)
        }
        asset_cleanup.queue_references(
            db,
            (
                reference
                for reference in previous_asset_references
                if reference not in current_asset_references
            ),
        )
        cost_recorder.finalize(
            status=GenerationRunStatus.SUCCEEDED,
            story=regenerated_story,
        )
    except Exception:
        _cleanup_unpersisted_story_assets(
            db=db,
            story_id=story_id,
            references=created_asset_references,
        )
        raise

    asset_cleanup.try_process_pending_deletions(db)
    return regenerated_story


def review_story(
    *,
    db: Session,
    story_id: UUID,
    approve: bool,
) -> Story:
    review_result = db.execute(
        update(Story)
        .where(
            Story.id == story_id,
            Story.status == StoryStatus.PENDING_REVIEW,
        )
        .values(
            status=(
                StoryStatus.APPROVED if approve else StoryStatus.REJECTED
            ),
            approved_at=datetime.now(timezone.utc) if approve else None,
            failure_reason=None,
        )
        .execution_options(synchronize_session=False)
    )
    if review_result.rowcount == 0:
        _raise_for_unmatched_pending_story(db=db, story_id=story_id)

    db.commit()
    return get_story(db=db, story_id=story_id)
