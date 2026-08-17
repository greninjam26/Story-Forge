from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Parent
from app.ratelimit import rate_limit
from app.schemas import ParentLogin, ParentOut, ParentRegister, TokenResponse
from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ParentOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: ParentRegister,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("auth-register")),
) -> Parent:
    parent = Parent(
        email=str(payload.email).lower(),
        locale=payload.locale,
        hashed_password=hash_password(payload.password),
    )
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


@router.post("/register/token", response_model=TokenResponse)
def register_and_get_token(
    payload: ParentRegister,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    parent = Parent(
        email=str(payload.email).lower(),
        locale=payload.locale,
        hashed_password=hash_password(payload.password),
    )
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
    token = create_access_token(parent.id)
    return {"access_token": token}


@router.post("/login", response_model=TokenResponse)
def login(
    payload: ParentLogin,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("auth-login")),
) -> dict[str, str]:
    parent = db.query(Parent).filter(Parent.email == str(payload.email).lower()).first()
    if parent is None or parent.hashed_password is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not verify_password(payload.password, parent.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    token = create_access_token(parent.id)
    return {"access_token": token}
