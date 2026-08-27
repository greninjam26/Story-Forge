from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_parent, require_story_owner
from app.ratelimit import rate_limit
from app.models import Child, Parent, Story
from app.schemas import (
    StoryApprove,
    StoryCreate,
    StoryDetailOut,
    StoryOut,
    StoryRestart,
    StoryUpdate,
)
from app.services.safety import SafetyReviewUnavailable
from app.services.story_workflow import (
    ChildNotFoundError,
    FreeStoryLimitReachedError,
    IllustrationProviderNotConfiguredError,
    NarrationProviderNotConfiguredError,
    ReferencePhotoRequiredError,
    SafetyProviderNotConfiguredError,
    StoryProviderNotConfiguredError,
    StoryNotFoundError,
    StoryNotGenerationFailedError,
    StoryNotPendingReviewError,
    StoryRecoveryAttemptsExhaustedError,
    StoryNarrationGenerationError,
    StoryPageNotFoundError,
    StoryRegenerationError,
    UnsafeStoryEditError,
    create_story_with_idempotency,
    get_story as get_story_workflow,
    list_stories as list_stories_workflow,
    production_generation_enabled,
    regenerate_story as regenerate_story_workflow,
    review_story as review_story_workflow,
    update_story as update_story_workflow,
    retry_failed_story as retry_failed_story_workflow,
    restart_failed_story as restart_failed_story_workflow,
)


router = APIRouter(prefix="/stories", tags=["stories"])

_IDEMPOTENCY_KEY_MAX_LENGTH = 200


def _validated_idempotency_key(request: Request) -> str | None:
    value = request.headers.get("Idempotency-Key")
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must not be blank.",
        )
    if len(value) > _IDEMPOTENCY_KEY_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key is too long.",
        )
    return value


@router.post("", response_model=StoryOut, status_code=status.HTTP_201_CREATED)
def create_story(
    payload: StoryCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _current_parent: Parent = Depends(get_current_parent),
    _rate_limit: None = Depends(rate_limit("stories-create")),
) -> Story:
    child = db.get(Child, payload.child_id)
    if child is None or child.parent_id != _current_parent.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        )

    idempotency_key = _validated_idempotency_key(request)
    try:
        story, created = create_story_with_idempotency(
            db=db,
            child_id=payload.child_id,
            event_text=payload.event_text,
            idempotency_key=idempotency_key,
        )
    except ChildNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        ) from error
    except FreeStoryLimitReachedError as error:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="free story limit reached, subscription required",
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
    if created and production_generation_enabled():
        request.app.state.notify_story_generation(story.id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return story


def _raise_recovery_error(error: Exception) -> None:
    if isinstance(error, StoryNotFoundError):
        raise HTTPException(status_code=404, detail="Story not found.") from error
    if isinstance(error, StoryRecoveryAttemptsExhaustedError):
        raise HTTPException(
            status_code=409,
            detail="story_recovery_attempts_exhausted",
        ) from error
    if isinstance(error, StoryNotGenerationFailedError):
        raise HTTPException(
            status_code=409,
            detail="Story is not generation failed.",
        ) from error
    if isinstance(error, ReferencePhotoRequiredError):
        raise HTTPException(
            status_code=409,
            detail="add a reference photo before generating illustrations",
        ) from error
    details = {
        IllustrationProviderNotConfiguredError: "illustration_provider_not_configured",
        SafetyProviderNotConfiguredError: "safety_provider_not_configured",
        StoryProviderNotConfiguredError: "story_provider_not_configured",
        NarrationProviderNotConfiguredError: "narration_provider_not_configured",
    }
    for error_type, detail in details.items():
        if isinstance(error, error_type):
            raise HTTPException(status_code=503, detail=detail) from error
    if isinstance(error, SafetyReviewUnavailable):
        raise HTTPException(
            status_code=503,
            detail="safety_review_unavailable",
        ) from None
    raise error


@router.post(
    "/{story_id}/retry",
    response_model=StoryOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_failed_story(
    story_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    _current_parent: Parent = Depends(require_story_owner),
) -> Story:
    try:
        story = retry_failed_story_workflow(db=db, story_id=story_id)
    except (
        StoryNotFoundError,
        StoryNotGenerationFailedError,
        StoryRecoveryAttemptsExhaustedError,
        ReferencePhotoRequiredError,
        IllustrationProviderNotConfiguredError,
        SafetyProviderNotConfiguredError,
        StoryProviderNotConfiguredError,
        NarrationProviderNotConfiguredError,
        SafetyReviewUnavailable,
    ) as error:
        _raise_recovery_error(error)
    request.app.state.notify_story_generation(story.id)
    return story


@router.post(
    "/{story_id}/restart",
    response_model=StoryOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def restart_failed_story(
    story_id: UUID,
    payload: StoryRestart,
    request: Request,
    db: Session = Depends(get_db),
    _current_parent: Parent = Depends(require_story_owner),
) -> Story:
    try:
        story = restart_failed_story_workflow(
            db=db,
            story_id=story_id,
            event_text=payload.event_text,
        )
    except (
        StoryNotFoundError,
        StoryNotGenerationFailedError,
        StoryRecoveryAttemptsExhaustedError,
        ReferencePhotoRequiredError,
        IllustrationProviderNotConfiguredError,
        SafetyProviderNotConfiguredError,
        StoryProviderNotConfiguredError,
        NarrationProviderNotConfiguredError,
        SafetyReviewUnavailable,
    ) as error:
        _raise_recovery_error(error)
    request.app.state.notify_story_generation(story.id)
    return story


@router.get("/by-child/{child_id}", response_model=list[StoryOut])
def list_stories(
    child_id: UUID,
    db: Session = Depends(get_db),
    _current_parent: Parent = Depends(get_current_parent),
) -> list[Story]:
    child = db.get(Child, child_id)
    if child is None or child.parent_id != _current_parent.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        )
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
    _current_parent: Parent = Depends(require_story_owner),
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
    _current_parent: Parent = Depends(require_story_owner),
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
    except SafetyReviewUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="safety_review_unavailable",
        ) from None
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
    _current_parent: Parent = Depends(require_story_owner),
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
    _current_parent: Parent = Depends(require_story_owner),
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
