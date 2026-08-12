import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Child, PendingAssetDeletion
from app.services import storage


logger = logging.getLogger(__name__)
PROCESSING_LIMIT = 100
BASE_RETRY_DELAY = timedelta(minutes=1)
MAX_RETRY_DELAY = timedelta(hours=24)
MAX_AUTO_ATTEMPTS = 12


@dataclass(frozen=True, slots=True)
class CleanupResult:
    deleted: int
    failed: int


def queue_references(
    db: Session,
    references: Iterable[str | None],
) -> list[PendingAssetDeletion]:
    pending = [
        PendingAssetDeletion(reference=reference)
        for reference in dict.fromkeys(references)
        if reference and storage.is_managed_reference(reference)
    ]
    db.add_all(pending)
    return pending


def queue_child_assets(
    db: Session,
    child: Child,
) -> list[PendingAssetDeletion]:
    references: list[str | None] = [child.reference_photo_ref]
    for story in child.stories:
        for page in story.pages:
            references.extend((page.image_url, page.audio_url))
    return queue_references(db, references)


def process_pending_deletions(
    db: Session,
    *,
    now: datetime | None = None,
) -> CleanupResult:
    attempted_at = now or datetime.now(timezone.utc)
    statement = (
        select(PendingAssetDeletion)
        .where(
            PendingAssetDeletion.terminal_at.is_(None),
            or_(
                PendingAssetDeletion.next_attempt_at.is_(None),
                PendingAssetDeletion.next_attempt_at <= attempted_at,
            ),
        )
        .order_by(
            PendingAssetDeletion.created_at,
            PendingAssetDeletion.id,
        )
        .limit(PROCESSING_LIMIT)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    deleted = 0
    failed = 0
    for pending in db.scalars(statement):
        try:
            storage.delete_object(pending.reference)
        except Exception as error:
            failed += 1
            pending.attempts += 1
            pending.last_error = type(error).__name__
            pending.last_attempt_at = attempted_at
            if pending.attempts >= MAX_AUTO_ATTEMPTS:
                pending.next_attempt_at = None
                pending.terminal_at = attempted_at
            else:
                pending.next_attempt_at = attempted_at + min(
                    BASE_RETRY_DELAY * (2 ** (pending.attempts - 1)),
                    MAX_RETRY_DELAY,
                )
            logger.warning(
                "Asset deletion failed and was retained for retry: "
                "reference=%s error_type=%s",
                pending.reference,
                pending.last_error,
            )
        else:
            deleted += 1
            db.delete(pending)

    db.commit()
    return CleanupResult(deleted=deleted, failed=failed)


def try_process_pending_deletions(
    db: Session,
) -> CleanupResult | None:
    try:
        return process_pending_deletions(db)
    except Exception:
        db.rollback()
        logger.exception("Pending asset deletion processing failed.")
        return None
