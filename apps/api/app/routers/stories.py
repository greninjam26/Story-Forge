from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Story
from app.schemas import StoryCreate, StoryOut
from app.services.story_workflow import (
    ChildNotFoundError,
    create_story as create_story_workflow,
    list_stories as list_stories_workflow,
)


router = APIRouter(prefix="/stories", tags=["stories"])


@router.post("", response_model=StoryOut, status_code=status.HTTP_201_CREATED)
def create_story(
    payload: StoryCreate,
    db: Session = Depends(get_db),
) -> Story:
    try:
        return create_story_workflow(
            db=db,
            child_id=payload.child_id,
            event_text=payload.event_text,
        )
    except ChildNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        ) from error


@router.get("/by-child/{child_id}", response_model=list[StoryOut])
def list_stories(
    child_id: UUID,
    db: Session = Depends(get_db),
) -> list[Story]:
    try:
        return list_stories_workflow(db=db, child_id=child_id)
    except ChildNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        ) from error
