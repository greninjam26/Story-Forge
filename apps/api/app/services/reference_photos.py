import logging

from sqlalchemy.orm import Session

from app.models import Child
from app.services import asset_cleanup, storage
from app.services.image_files import normalize_webp


logger = logging.getLogger(__name__)


class ChildDeletionError(Exception):
    pass


class ReferencePhotoPersistenceError(Exception):
    pass


class ReferencePhotoStorageError(Exception):
    pass


def _delete_reference_best_effort(
    reference: str | None,
    failure_message: str,
) -> bool:
    if reference is None:
        return True
    try:
        storage.delete_object(reference)
    except Exception:
        logger.exception(failure_message)
        return False
    return True


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
    asset_cleanup.queue_references(db, [previous_reference])
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        deleted = _delete_reference_best_effort(
            new_reference,
            "New reference photo cleanup failed after database rollback.",
        )
        if not deleted:
            try:
                asset_cleanup.queue_references(db, [new_reference])
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "Could not retain new reference photo cleanup for retry."
                )
        raise ReferencePhotoPersistenceError from exc

    asset_cleanup.try_process_pending_deletions(db)


def delete_child_with_reference_photo(db: Session, child: Child) -> None:
    asset_cleanup.queue_child_assets(db, child)
    db.delete(child)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise ChildDeletionError from exc
    asset_cleanup.try_process_pending_deletions(db)


def remove_reference_photo(db: Session, child: Child) -> None:
    previous_reference = child.reference_photo_ref
    child.reference_photo_ref = None
    asset_cleanup.queue_references(db, [previous_reference])
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise ReferencePhotoPersistenceError from exc

    asset_cleanup.try_process_pending_deletions(db)
