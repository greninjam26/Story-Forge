from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Story
from app.schemas import (
    StoryApprove,
    StoryCreate,
    StoryDetailOut,
    StoryOut,
    StoryUpdate,
)
from app.services.safety import SafetyReviewUnavailable
from app.services.story_workflow import (
    ChildNotFoundError,
    IllustrationProviderNotConfiguredError,
    NarrationProviderNotConfiguredError,
    ReferencePhotoRequiredError,
    SafetyProviderNotConfiguredError,
    StoryProviderNotConfiguredError,
    StoryNotFoundError,
    StoryNotPendingReviewError,
    StoryNarrationGenerationError,
    StoryPageNotFoundError,
    StoryRegenerationError,
    UnsafeStoryEditError,
    create_story as create_story_workflow,
    get_story as get_story_workflow,
    list_stories as list_stories_workflow,
    process_queued_story,
    production_generation_enabled,
    queue_story,
    regenerate_story as regenerate_story_workflow,
    review_story as review_story_workflow,
    update_story as update_story_workflow,
)


router = APIRouter(prefix="/stories", tags=["stories"])


@router.post("", response_model=StoryOut, status_code=status.HTTP_201_CREATED)
def create_story(
    payload: StoryCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
) -> Story:
    try:
        if production_generation_enabled():
            story = queue_story(
                db=db,
                child_id=payload.child_id,
                event_text=payload.event_text,
            )
            background_tasks.add_task(
                process_queued_story,
                request.app.state.story_generation_session_factory,
                story.id,
            )
            return story
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
    except ReferencePhotoRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "add a reference photo before generating illustrations"
            ),
        ) from error
    except IllustrationProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="illustration_provider_not_configured",
        ) from error
    except SafetyProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="safety_provider_not_configured",
        ) from error
    except StoryProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="story_provider_not_configured",
        ) from error
    except NarrationProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="narration_provider_not_configured",
        ) from error
    except SafetyReviewUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="safety_review_unavailable",
        ) from None


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


@router.get("/{story_id}", response_model=StoryDetailOut)
def get_story(
    story_id: UUID,
    db: Session = Depends(get_db),
) -> Story:
    try:
        return get_story_workflow(db=db, story_id=story_id)
    except StoryNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        ) from error


@router.patch("/{story_id}", response_model=StoryOut)
def update_story(
    story_id: UUID,
    payload: StoryUpdate,
    db: Session = Depends(get_db),
) -> Story:
    try:
        return update_story_workflow(
            db=db,
            story_id=story_id,
            title=payload.title,
            pages={
                page.page_number: page.text for page in payload.pages or []
            },
        )
    except StoryNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        ) from error
    except StoryNotPendingReviewError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Story is not pending review.",
        ) from error
    except StoryPageNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Story page not found.",
        ) from error
    except UnsafeStoryEditError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Story content failed safety checks.",
        ) from error
    except StoryNarrationGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Story narration generation failed.",
        ) from error


@router.patch("/{story_id}/approve", response_model=StoryOut)
def approve_story(
    story_id: UUID,
    payload: StoryApprove,
    db: Session = Depends(get_db),
) -> Story:
    try:
        return review_story_workflow(
            db=db,
            story_id=story_id,
            approve=payload.approve,
        )
    except StoryNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        ) from error
    except StoryNotPendingReviewError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Story is not pending review.",
        ) from error


@router.post("/{story_id}/regenerate", response_model=StoryOut)
def regenerate_story(
    story_id: UUID,
    db: Session = Depends(get_db),
) -> Story:
    try:
        return regenerate_story_workflow(db=db, story_id=story_id)
    except StoryNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        ) from error
    except StoryNotPendingReviewError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Story is not pending review.",
        ) from error
    except StoryRegenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Story regeneration failed.",
        ) from error
    except ReferencePhotoRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "add a reference photo before generating illustrations"
            ),
        ) from error
    except IllustrationProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="illustration_provider_not_configured",
        ) from error
    except SafetyProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="safety_provider_not_configured",
        ) from error
    except SafetyReviewUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="safety_review_unavailable",
        ) from None
