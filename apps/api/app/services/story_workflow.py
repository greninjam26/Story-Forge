from datetime import datetime, timezone
from typing import NoReturn
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Child, Story, StoryPage, StoryStatus
from app.services.story_generation import generate_story
from app.services.story_safety import check_text


class ChildNotFoundError(Exception):
    pass


class StoryNotFoundError(Exception):
    pass


class StoryNotPendingReviewError(Exception):
    pass


class StoryPageNotFoundError(Exception):
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


def create_story(
    *,
    db: Session,
    child_id: UUID,
    event_text: str,
) -> Story:
    child = db.get(Child, child_id)
    if child is None:
        raise ChildNotFoundError

    safety_result = check_text(event_text)
    if not safety_result.is_safe:
        story = Story(
            child_id=child.id,
            event_text=event_text,
            title="",
            language=child.language,
            status=StoryStatus.REJECTED,
            failure_reason=safety_result.reason,
        )
        db.add(story)
        db.commit()
        db.refresh(story)
        return story

    generated = generate_story(
        child_name=child.name,
        age=child.age,
        interests=child.interests,
        event_text=event_text,
        language=child.language,
    )
    story = Story(
        child_id=child.id,
        event_text=event_text,
        title=generated.title,
        language=child.language,
        status=StoryStatus.PENDING_REVIEW,
    )
    story.pages = [
        StoryPage(page_number=page_number, text=page_text)
        for page_number, page_text in enumerate(generated.pages, start=1)
    ]
    db.add(story)
    db.commit()
    db.refresh(story)
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
    update_result = db.execute(
        update(Story)
        .where(
            Story.id == story_id,
            Story.status == StoryStatus.PENDING_REVIEW,
        )
        .values(title=title if title is not None else Story.title)
        .execution_options(synchronize_session=False)
    )
    if update_result.rowcount == 0:
        _raise_for_unmatched_pending_story(db=db, story_id=story_id)

    if pages:
        stored_page_numbers = set(
            db.scalars(
                select(StoryPage.page_number).where(
                    StoryPage.story_id == story_id,
                    StoryPage.page_number.in_(list(pages)),
                )
            )
        )
        if stored_page_numbers != set(pages):
            db.rollback()
            raise StoryPageNotFoundError

    for page_number, page_text in pages.items():
        db.execute(
            update(StoryPage)
            .where(
                StoryPage.story_id == story_id,
                StoryPage.page_number == page_number,
            )
            .values(text=page_text)
            .execution_options(synchronize_session=False)
        )

    db.commit()
    return get_story(db=db, story_id=story_id)


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
    try:
        generated = generate_story(
            child_name=child.name,
            age=child.age,
            interests=child.interests,
            event_text=story.event_text,
            language=story.language,
        )
    except Exception as error:
        db.rollback()
        raise StoryRegenerationError from error

    regeneration_result = db.execute(
        update(Story)
        .where(
            Story.id == story_id,
            Story.status == StoryStatus.PENDING_REVIEW,
        )
        .values(title=generated.title)
        .execution_options(synchronize_session=False)
    )
    if regeneration_result.rowcount == 0:
        _raise_for_unmatched_pending_story(db=db, story_id=story_id)

    db.execute(delete(StoryPage).where(StoryPage.story_id == story_id))
    db.add_all(
        StoryPage(
            story_id=story_id,
            page_number=page_number,
            text=page_text,
        )
        for page_number, page_text in enumerate(generated.pages, start=1)
    )
    db.commit()
    db.expire(story)
    return get_story(db=db, story_id=story_id)


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
        )
        .execution_options(synchronize_session=False)
    )
    if review_result.rowcount == 0:
        _raise_for_unmatched_pending_story(db=db, story_id=story_id)

    db.commit()
    return get_story(db=db, story_id=story_id)
