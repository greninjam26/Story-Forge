import logging
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Child, Parent
from app.request_limits import REFERENCE_PHOTO_FILE_BYTES
from app.schemas import ChildCreate, ChildOut, ChildUpdate
from app.services import storage
from app.services.image_files import InvalidImageError, normalize_webp


router = APIRouter(
    prefix="/parents/{parent_id}/children",
    tags=["children"],
)
logger = logging.getLogger(__name__)


def _get_parent(db: Session, parent_id: UUID) -> Parent:
    parent = db.get(Parent, parent_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent not found.",
        )
    return parent


def _get_child(
    db: Session,
    parent_id: UUID,
    child_id: UUID,
) -> Child:
    child = db.scalar(
        select(Child).where(
            Child.id == child_id,
            Child.parent_id == parent_id,
        )
    )
    if child is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        )
    return child


@router.post("", response_model=ChildOut, status_code=status.HTTP_201_CREATED)
def create_child(
    parent_id: UUID,
    payload: ChildCreate,
    db: Session = Depends(get_db),
) -> Child:
    parent = _get_parent(db, parent_id)
    child = Child(
        parent_id=parent.id,
        name=payload.name,
        age=payload.age,
        interests=payload.interests,
        language=payload.language,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


@router.get("", response_model=list[ChildOut])
def list_children(
    parent_id: UUID,
    db: Session = Depends(get_db),
) -> list[Child]:
    _get_parent(db, parent_id)
    children = db.scalars(
        select(Child)
        .where(Child.parent_id == parent_id)
        .order_by(Child.created_at, Child.id)
    )
    return list(children)


@router.get("/{child_id}", response_model=ChildOut)
def get_child(
    parent_id: UUID,
    child_id: UUID,
    db: Session = Depends(get_db),
) -> Child:
    return _get_child(db, parent_id, child_id)


@router.patch("/{child_id}", response_model=ChildOut)
def update_child(
    parent_id: UUID,
    child_id: UUID,
    payload: ChildUpdate,
    db: Session = Depends(get_db),
) -> Child:
    child = _get_child(db, parent_id, child_id)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(child, field_name, value)

    db.commit()
    db.refresh(child)
    return child


@router.put(
    "/{child_id}/reference-photo",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def upload_reference_photo(
    parent_id: UUID,
    child_id: UUID,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Response:
    child = _get_child(db, parent_id, child_id)
    data = await photo.read(REFERENCE_PHOTO_FILE_BYTES + 1)
    if len(data) > REFERENCE_PHOTO_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Reference photo must be 10 MB or smaller.",
        )
    try:
        normalized = normalize_webp(data)
    except InvalidImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    try:
        new_reference = storage.put_object(
            normalized,
            storage.new_key("references", ".webp"),
            "image/webp",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reference photo storage is temporarily unavailable.",
        ) from exc

    previous_reference = child.reference_photo_ref
    child.reference_photo_ref = new_reference
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            storage.delete_object(new_reference)
        except Exception:
            logger.exception(
                "New reference photo cleanup failed after database rollback."
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reference photo could not be saved.",
        ) from exc
    if previous_reference is not None:
        try:
            storage.delete_object(previous_reference)
        except Exception:
            logger.exception(
                "Previous reference photo cleanup failed after replacement."
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{child_id}/reference-photo",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_reference_photo(
    parent_id: UUID,
    child_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    child = _get_child(db, parent_id, child_id)
    previous_reference = child.reference_photo_ref
    child.reference_photo_ref = None
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reference photo could not be removed.",
        ) from exc
    if previous_reference is not None:
        try:
            storage.delete_object(previous_reference)
        except Exception:
            logger.exception(
                "Reference photo cleanup failed after removal."
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_child(
    parent_id: UUID,
    child_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    child = _get_child(db, parent_id, child_id)
    db.delete(child)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
