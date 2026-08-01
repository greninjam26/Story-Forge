from datetime import datetime, timezone
from typing import NoReturn
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Child,
    GenerationRunStatus,
    Story,
    StoryPage,
    StoryStatus,
)
from app.services.cost_tracking import RunCostRecorder
from app.services.illustration import generate_illustration
from app.services.narration import generate_narration
from app.services.story_generation import generate_story
from app.services.story_safety import check_generated_story, check_text


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


class StoryNarrationGenerationError(Exception):
    pass


class StoryRegenerationError(Exception):
    pass


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
) -> NoReturn:
    db.rollback()
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
        cost_recorder.finalize(status=GenerationRunStatus.FAILED)
        _raise_for_unmatched_pending_story(db=db, story_id=story_id)
    db.commit()
    failed_story = db.get(Story, story_id)
    cost_recorder.finalize(
        status=GenerationRunStatus.FAILED,
        story=failed_story,
    )
    raise StoryRegenerationError from error


def _raise_for_stale_generation_action(
    *,
    db: Session,
    story: Story,
    cost_recorder: RunCostRecorder,
) -> NoReturn:
    cost_recorder.finalize(
        status=GenerationRunStatus.FAILED,
        story=story,
    )
    _raise_for_unmatched_pending_story(db=db, story_id=story.id)


def _persist_rejected_story(
    *,
    db: Session,
    child: Child,
    event_text: str,
    failure_reason: str | None,
) -> Story:
    story = Story(
        child_id=child.id,
        event_text=event_text,
        title="",
        language=child.language,
        status=StoryStatus.REJECTED,
        failure_reason=failure_reason,
    )
    db.add(story)
    db.commit()
    db.refresh(story)
    return story


def _persist_failed_story(
    *,
    db: Session,
    child: Child,
    event_text: str,
    failure_reason: str,
) -> Story:
    story = Story(
        child_id=child.id,
        event_text=event_text,
        title="",
        language=child.language,
        status=StoryStatus.GENERATION_FAILED,
        failure_reason=failure_reason,
    )
    db.add(story)
    db.commit()
    db.refresh(story)
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

    cost_recorder = RunCostRecorder.start(db)
    try:
        safety_result = check_text(event_text)
    except Exception:
        cost_recorder.finalize(status=GenerationRunStatus.FAILED)
        raise
    if not safety_result.is_safe:
        story = _persist_rejected_story(
            db=db,
            child=child,
            event_text=event_text,
            failure_reason=safety_result.reason,
        )
        cost_recorder.finalize(
            status=GenerationRunStatus.REJECTED,
            story=story,
        )
        return story

    try:
        generated = generate_story(
            child_name=child.name,
            age=child.age,
            interests=child.interests,
            event_text=event_text,
            language=child.language,
            recorder=cost_recorder,
        )
    except Exception:
        story = _persist_failed_story(
            db=db,
            child=child,
            event_text=event_text,
            failure_reason="story_generation_failed",
        )
        cost_recorder.finalize(
            status=GenerationRunStatus.FAILED,
            story=story,
        )
        return story

    try:
        generated_safety = check_generated_story(
            title=generated.title,
            page_texts=generated.pages,
        )
    except Exception:
        cost_recorder.finalize(status=GenerationRunStatus.FAILED)
        raise
    if not generated_safety.is_safe:
        story = _persist_rejected_story(
            db=db,
            child=child,
            event_text=event_text,
            failure_reason=generated_safety.reason,
        )
        cost_recorder.finalize(
            status=GenerationRunStatus.REJECTED,
            story=story,
        )
        return story

    pages = [
        StoryPage(page_number=page_number, text=page_text)
        for page_number, page_text in enumerate(generated.pages, start=1)
    ]
    try:
        for page in pages:
            page.image_url = generate_illustration(
                avatar_seed=str(child.id),
                page_number=page.page_number,
                page_text=page.text,
                recorder=cost_recorder,
            )
    except Exception:
        story = _persist_failed_story(
            db=db,
            child=child,
            event_text=event_text,
            failure_reason="illustration_generation_failed",
        )
        cost_recorder.finalize(
            status=GenerationRunStatus.FAILED,
            story=story,
        )
        return story

    try:
        for page in pages:
            page.audio_url = generate_narration(
                text=page.text,
                language=child.language,
                recorder=cost_recorder,
            )
    except Exception:
        story = _persist_failed_story(
            db=db,
            child=child,
            event_text=event_text,
            failure_reason="narration_generation_failed",
        )
        cost_recorder.finalize(
            status=GenerationRunStatus.FAILED,
            story=story,
        )
        return story

    story = Story(
        child_id=child.id,
        event_text=event_text,
        title=generated.title,
        language=child.language,
        status=StoryStatus.PENDING_REVIEW,
        pages=pages,
    )
    db.add(story)
    db.commit()
    db.refresh(story)
    cost_recorder.finalize(
        status=GenerationRunStatus.SUCCEEDED,
        story=story,
    )
    return story


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
    story_id: UUID,
) -> Story:
    story = db.scalar(
        select(Story)
        .where(
            Story.id == story_id,
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

    safety_result = check_generated_story(
        title=title if title is not None else story.title,
        page_texts=[
            pages.get(page.page_number, page.text) for page in story.pages
        ],
    )
    if not safety_result.is_safe:
        db.rollback()
        raise UnsafeStoryEditError

    cost_recorder = None
    narration_urls: dict[int, str] = {}
    if pages:
        cost_recorder = RunCostRecorder.start(db)
        try:
            narration_urls = {
                page_number: generate_narration(
                    text=page_text,
                    language=story.language,
                    recorder=cost_recorder,
                )
                for page_number, page_text in pages.items()
            }
        except Exception as error:
            db.rollback()
            cost_recorder.finalize(
                status=GenerationRunStatus.FAILED,
                story=story,
            )
            raise StoryNarrationGenerationError from error

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

    db.commit()
    db.expire(story)
    updated_story = get_story(db=db, story_id=story_id)
    if cost_recorder is not None:
        cost_recorder.finalize(
            status=GenerationRunStatus.SUCCEEDED,
            story=updated_story,
        )
    return updated_story


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
        generated_safety = check_generated_story(
            title=generated.title,
            page_texts=generated.pages,
        )
    except Exception:
        cost_recorder.finalize(
            status=GenerationRunStatus.FAILED,
            story=story,
        )
        raise
    if not generated_safety.is_safe:
        rejection_result = db.execute(
            update(Story)
            .where(
                Story.id == story_id,
                Story.status == StoryStatus.PENDING_REVIEW,
            )
            .values(
                title="",
                status=StoryStatus.REJECTED,
                failure_reason=generated_safety.reason,
            )
            .execution_options(synchronize_session=False)
        )
        if rejection_result.rowcount == 0:
            _raise_for_stale_generation_action(
                db=db,
                story=story,
                cost_recorder=cost_recorder,
            )

        db.execute(
            delete(StoryPage).where(StoryPage.story_id == story_id)
        )
        db.commit()
        db.expire(story)
        rejected_story = get_story(db=db, story_id=story_id)
        cost_recorder.finalize(
            status=GenerationRunStatus.REJECTED,
            story=rejected_story,
        )
        return rejected_story

    try:
        regenerated_pages = [
            StoryPage(
                story_id=story_id,
                page_number=page_number,
                text=page_text,
                image_url=generate_illustration(
                    avatar_seed=str(child.id),
                    page_number=page_number,
                    page_text=page_text,
                    recorder=cost_recorder,
                ),
                audio_url=generate_narration(
                    text=page_text,
                    language=story.language,
                    recorder=cost_recorder,
                ),
            )
            for page_number, page_text in enumerate(
                generated.pages,
                start=1,
            )
        ]
    except Exception as error:
        _raise_for_regeneration_failure(
            db=db,
            story_id=story_id,
            error=error,
            cost_recorder=cost_recorder,
        )

    regeneration_result = db.execute(
        update(Story)
        .where(
            Story.id == story_id,
            Story.status == StoryStatus.PENDING_REVIEW,
        )
        .values(
            title=generated.title,
            failure_reason=None,
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
    db.commit()
    db.expire(story)
    regenerated_story = get_story(db=db, story_id=story_id)
    cost_recorder.finalize(
        status=GenerationRunStatus.SUCCEEDED,
        story=regenerated_story,
    )
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
