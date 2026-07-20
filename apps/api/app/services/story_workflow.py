from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Child, Story, StoryPage, StoryStatus
from app.services.story_generation import generate_story


class ChildNotFoundError(Exception):
    pass


def create_story(
    *,
    db: Session,
    child_id: UUID,
    event_text: str,
) -> Story:
    child = db.get(Child, child_id)
    if child is None:
        raise ChildNotFoundError

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
