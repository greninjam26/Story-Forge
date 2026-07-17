from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Parent
from app.schemas import ParentCreate, ParentOut


router = APIRouter(prefix="/parents", tags=["parents"])


@router.post("", response_model=ParentOut, status_code=status.HTTP_201_CREATED)
def create_parent(
    payload: ParentCreate,
    db: Session = Depends(get_db),
) -> Parent:
    parent = Parent(email=str(payload.email).lower(), locale=payload.locale)
    db.add(parent)

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A parent with this email already exists.",
        ) from error

    db.refresh(parent)
    return parent


@router.get("/{parent_id}", response_model=ParentOut)
def get_parent(
    parent_id: UUID,
    db: Session = Depends(get_db),
) -> Parent:
    parent = db.get(Parent, parent_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent not found.",
        )
    return parent
