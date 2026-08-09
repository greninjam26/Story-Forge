import logging

from sqlalchemy.orm import Session

from app.models import Child
from app.services import storage


logger = logging.getLogger(__name__)


class ReferencePhotoPersistenceError(Exception):
    pass


def remove_reference_photo(db: Session, child: Child) -> None:
    previous_reference = child.reference_photo_ref
    child.reference_photo_ref = None
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise ReferencePhotoPersistenceError from exc

    if previous_reference is not None:
        try:
            storage.delete_object(previous_reference)
        except Exception:
            logger.exception("Reference photo cleanup failed after removal.")
