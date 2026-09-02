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
from app.schemas import (
    GoogleAuthRequest,
    ParentLocaleUpdate,
    ParentLogin,
    ParentOut,
    ParentRegister,
    TokenResponse,
)
from app.services import asset_cleanup
from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.email_validation import email_domain_can_receive_mail
from app.services.google_auth import (
    GoogleIdentityInvalid,
    GoogleIdentityUnavailable,
    verify_google_credential,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: ParentRegister,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("auth-register")),
) -> dict[str, str]:
    email = str(payload.email).lower()
    if (
        settings.registration_email_domain_check_enabled
        and not email_domain_can_receive_mail(email)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Enter an email address with a domain that can receive email."
            ),
        )

    parent = Parent(
        email=email,
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
    return {"access_token": token, "locale": parent.locale}


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
    return {"access_token": token, "locale": parent.locale}


@router.post("/google", response_model=TokenResponse)
def google_login(
    payload: GoogleAuthRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("auth-google")),
) -> dict[str, str]:
    try:
        claims = verify_google_credential(payload.credential)
    except GoogleIdentityInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed.",
        ) from error
    except GoogleIdentityUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is temporarily unavailable.",
        ) from error

    subject = claims["sub"]
    email = claims["email"].lower()
    parent = db.query(Parent).filter(Parent.google_subject == subject).first()

    if parent is None:
        parent = db.query(Parent).filter(Parent.email == email).first()
        if parent is None:
            parent = Parent(
                email=email,
                locale=payload.locale,
                google_subject=subject,
                email_verified=True,
            )
            db.add(parent)
        elif parent.google_subject is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "google_account_conflict",
                    "message": "This email is linked to another Google account.",
                },
            )
        elif payload.link_password is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "google_link_password_required",
                    "message": "Confirm your Story Forge password to link Google.",
                },
            )
        elif (
            parent.hashed_password is None
            or not verify_password(payload.link_password, parent.hashed_password)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        else:
            parent.google_subject = subject
            parent.email_verified = True

        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "google_account_conflict",
                    "message": "This Google account could not be linked.",
                },
            ) from error
        db.refresh(parent)

    token = create_access_token(parent.id)
    return {"access_token": token, "locale": parent.locale}


@router.get("/me", response_model=ParentOut)
def get_me(
    parent: Parent = Depends(get_current_parent),
) -> Parent:
    return parent


@router.patch("/me", response_model=ParentOut)
def update_me(
    payload: ParentLocaleUpdate,
    parent: Parent = Depends(get_current_parent),
    db: Session = Depends(get_db),
) -> Parent:
    parent.locale = payload.locale
    db.commit()
    db.refresh(parent)
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
