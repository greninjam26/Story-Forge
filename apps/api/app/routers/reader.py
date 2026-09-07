from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Story
from app.schemas import ReaderStoryOut
from app.services.story_workflow import (
    ChildNotFoundError,
    StoryNotFoundError,
    get_approved_story as get_approved_story_workflow,
    list_approved_stories as list_approved_stories_workflow,
)


router = APIRouter(prefix="/reader", tags=["reader"])


@router.get(
    "/{reader_access_token}/stories",
    response_model=list[ReaderStoryOut],
)
def list_approved_stories(
    reader_access_token: UUID,
    db: Session = Depends(get_db),
) -> list[Story]:
    try:
        return list_approved_stories_workflow(
            db=db,
            reader_access_token=reader_access_token,
        )
    except ChildNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reader not found.",
        ) from error


@router.get(
    "/{reader_access_token}/stories/{story_id}",
    response_model=ReaderStoryOut,
)
def get_approved_story(
    reader_access_token: UUID,
    story_id: UUID,
    db: Session = Depends(get_db),
) -> Story:
    try:
        return get_approved_story_workflow(
            db=db,
            reader_access_token=reader_access_token,
            story_id=story_id,
        )
    except (ChildNotFoundError, StoryNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reader story not found.",
        ) from error
