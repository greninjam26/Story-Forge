"""Private database CLI for reviewing retained moderation evidence."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ModerationRecord


logger = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "limit must be a positive integer"
        ) from error
    if parsed < 1:
        raise argparse.ArgumentTypeError(
            "limit must be a positive integer"
        )
    return parsed


def _record_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "record id must be a UUID"
        ) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moderation-review")
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser("list")
    list_parser.add_argument("--limit", type=_positive_int, default=50)

    show_parser = commands.add_parser("show")
    show_parser.add_argument("record_id", type=_record_id)

    review_parser = commands.add_parser("review")
    review_parser.add_argument("record_id", type=_record_id)
    review_parser.add_argument(
        "--decision",
        required=True,
        choices=("confirmed", "false_positive"),
    )
    return parser


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _metadata(record: ModerationRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "story_id": str(record.story_id),
        "created_at": record.created_at.isoformat(),
        "provider": record.provider,
        "model": record.model,
        "provider_request_id": record.provider_request_id,
        "flagged_item_kind": record.flagged_item_kind,
        "flagged_page_number": record.flagged_page_number,
        "categories": record.categories,
        "review_status": record.review_status,
    }


def _list(db: Session, limit: int) -> int:
    rows = db.execute(
        select(
            ModerationRecord.id,
            ModerationRecord.story_id,
            ModerationRecord.created_at,
            ModerationRecord.provider,
            ModerationRecord.model,
            ModerationRecord.provider_request_id,
            ModerationRecord.flagged_item_kind,
            ModerationRecord.flagged_page_number,
            ModerationRecord.categories,
            ModerationRecord.review_status,
        )
        .where(ModerationRecord.review_status == "pending")
        .order_by(ModerationRecord.created_at, ModerationRecord.id)
        .limit(limit)
    ).mappings()
    for row in rows:
        value = dict(row)
        value["id"] = str(value["id"])
        value["story_id"] = str(value["story_id"])
        value["created_at"] = value["created_at"].isoformat()
        _print_json(value)
    return 0


def _show(db: Session, record_id: UUID) -> int:
    record = db.get(ModerationRecord, record_id)
    if record is None:
        print("moderation record not found", file=sys.stderr)
        return 1
    value = _metadata(record)
    value["flagged_text"] = record.flagged_text
    _print_json(value)
    return 0


def _review(db: Session, record_id: UUID, decision: str) -> int:
    try:
        result = db.execute(
            update(ModerationRecord)
            .where(
                ModerationRecord.id == record_id,
                ModerationRecord.review_status == "pending",
            )
            .values(
                review_status=decision,
                reviewed_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            db.rollback()
            exists = db.scalar(
                select(ModerationRecord.id).where(
                    ModerationRecord.id == record_id
                )
            )
            if exists is None:
                print("moderation record not found", file=sys.stderr)
            else:
                print(
                    "moderation record already reviewed",
                    file=sys.stderr,
                )
            return 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "moderation review update failed (record_id=%s)",
            record_id,
        )
        print("moderation review update failed", file=sys.stderr)
        return 1

    _print_json({"id": str(record_id), "review_status": decision})
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> int:
    args = _parser().parse_args(argv)
    with session_factory() as db:
        if args.command == "list":
            return _list(db, args.limit)
        if args.command == "show":
            return _show(db, args.record_id)
        return _review(db, args.record_id, args.decision)


if __name__ == "__main__":
    raise SystemExit(main())
