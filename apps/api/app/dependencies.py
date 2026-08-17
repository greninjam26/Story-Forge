"""FastAPI dependencies for authentication and authorization."""

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Child, Parent, Story
from app.services.auth import decode_access_token


def get_current_parent(
    request: Request,
    db: Session = Depends(get_db),
) -> Parent:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )
    token = auth_header[7:]
    try:
        parent_id = decode_access_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    parent = db.get(Parent, parent_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Parent not found.",
        )
    return parent


def require_parent_owner(
    parent_id: UUID,
    current_parent: Parent = Depends(get_current_parent),
) -> Parent:
    if current_parent.id != parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )
    return current_parent


def require_child_owner(
    parent_id: UUID,
    child_id: UUID,
    current_parent: Parent = Depends(get_current_parent),
    db: Session = Depends(get_db),
) -> Parent:
    if current_parent.id != parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )
    child = db.get(Child, child_id)
    if child is None or child.parent_id != parent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child not found.",
        )
    return current_parent


def require_story_owner(
    story_id: UUID,
    current_parent: Parent = Depends(get_current_parent),
    db: Session = Depends(get_db),
) -> Parent:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        )
    child = db.get(Child, story.child_id)
    if child is None or child.parent_id != current_parent.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )
    return current_parent
