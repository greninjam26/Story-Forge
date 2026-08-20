from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Child, Story
from app.schemas import ReaderChildOut, ReaderStoryOut
from app.services.story_workflow import (
    ChildNotFoundError,
    StoryNotFoundError,
    get_approved_story as get_approved_story_workflow,
    get_reader_child as get_reader_child_workflow,
    list_approved_stories as list_approved_stories_workflow,
)


router = APIRouter(prefix="/reader", tags=["reader"])


@router.get(
    "/children/{child_id}",
    response_model=ReaderChildOut,
)
def get_reader_child(
    child_id: UUID,
    db: Session = Depends(get_db),
) -> Child:
    try:
        return get_reader_child_workflow(db=db, child_id=child_id)
    except ChildNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        ) from error


@router.get(
    "/children/{child_id}/stories",
    response_model=list[ReaderStoryOut],
)
def list_approved_stories(
    child_id: UUID,
    db: Session = Depends(get_db),
) -> list[Story]:
    try:
        return list_approved_stories_workflow(db=db, child_id=child_id)
    except ChildNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        ) from error


@router.get("/stories/{story_id}", response_model=ReaderStoryOut)
def get_approved_story(
    story_id: UUID,
    db: Session = Depends(get_db),
) -> Story:
    try:
        return get_approved_story_workflow(db=db, story_id=story_id)
    except StoryNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        ) from error
