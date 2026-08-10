import logging

from sqlalchemy.orm import Session

from app.models import Child
from app.services import storage
from app.services.image_files import normalize_webp


logger = logging.getLogger(__name__)


class ReferencePhotoPersistenceError(Exception):
    pass


class ReferencePhotoStorageError(Exception):
    pass


def _delete_reference_best_effort(
    reference: str | None,
    failure_message: str,
) -> None:
    if reference is None:
        return
    try:
        storage.delete_object(reference)
    except Exception:
        logger.exception(failure_message)


def replace_reference_photo(db: Session, child: Child, data: bytes) -> None:
    normalized = normalize_webp(data)
    try:
        new_reference = storage.put_object(
            normalized,
            storage.new_key("references", ".webp"),
            "image/webp",
        )
    except Exception as exc:
        raise ReferencePhotoStorageError from exc
    previous_reference = child.reference_photo_ref
    child.reference_photo_ref = new_reference
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _delete_reference_best_effort(
            new_reference,
            "New reference photo cleanup failed after database rollback.",
        )
        raise ReferencePhotoPersistenceError from exc

    _delete_reference_best_effort(
        previous_reference,
        "Previous reference photo cleanup failed after replacement.",
    )


def remove_reference_photo(db: Session, child: Child) -> None:
    previous_reference = child.reference_photo_ref
    child.reference_photo_ref = None
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise ReferencePhotoPersistenceError from exc

    _delete_reference_best_effort(
        previous_reference,
        "Reference photo cleanup failed after removal.",
    )
