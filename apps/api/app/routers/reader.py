from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Story
from app.schemas import StoryOut
from app.services.story_workflow import (
    ChildNotFoundError,
    list_approved_stories as list_approved_stories_workflow,
)


router = APIRouter(prefix="/reader", tags=["reader"])


@router.get(
    "/children/{child_id}/stories",
    response_model=list[StoryOut],
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
