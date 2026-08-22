from uuid import UUID

from fastapi import APIRouter, Depends
from app.dependencies import require_parent_owner
from app.models import Parent
from app.schemas import ParentOut


router = APIRouter(prefix="/parents", tags=["parents"])


@router.get("/{parent_id}", response_model=ParentOut)
def get_parent(
    parent_id: UUID,
    _current_parent: Parent = Depends(require_parent_owner),
) -> Parent:
    return _current_parent
