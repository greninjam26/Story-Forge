import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from jose import JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import observability
from app.config import settings
from app.db import get_db
from app.dependencies import get_current_parent
from app.models import Parent
from app.ratelimit import rate_limit
from app.schemas import ParentLogin, ParentOut, ParentRegister, TokenResponse
from app.services import asset_cleanup
from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)


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
    _rate_limit: None = Depends(rate_limit("auth-register")),
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


@router.get("/me", response_model=ParentOut)
def get_me(
    parent: Parent = Depends(get_current_parent),
) -> Parent:
    return parent


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    response: Response,
    parent: Parent = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    """Parent-initiated full account deletion.

    Cancels the Stripe subscription first (best-effort), then deletes
    all child assets and the parent row.
    """
    if parent.stripe_subscription_id and settings.stripe_secret_key:
        try:
            import stripe

            stripe.api_key = settings.stripe_secret_key
            stripe.Subscription.cancel(parent.stripe_subscription_id)
        except Exception as exc:
            logger.warning(
                "could not cancel stripe subscription %s during account "
                "deletion",
                parent.stripe_subscription_id,
            )
            observability.report(
                exc,
                stage="account_deletion_stripe_cancel",
                stripe_subscription=parent.stripe_subscription_id,
                stripe_customer=parent.stripe_customer_id,
            )
    for child in parent.children:
        asset_cleanup.queue_child_assets(db, child)
    db.delete(parent)
    db.commit()
    response.delete_cookie("session")
