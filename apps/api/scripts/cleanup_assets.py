import argparse
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.asset_cleanup import (
    cleanup_backlog,
    process_pending_deletions,
    retry_terminal_deletions,
)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> int:
    parser = argparse.ArgumentParser(
        description="Retry pending Story Forge asset deletions"
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        help="maximum queued objects to attempt",
    )
    parser.add_argument(
        "--retry-terminal",
        action="store_true",
        help="return terminal deletions to the automatic retry queue",
    )
    args = parser.parse_args(argv)

    try:
        with session_factory() as db:
            if args.retry_terminal:
                retry_terminal_deletions(db)
            result = process_pending_deletions(db, limit=args.limit)
            backlog = cleanup_backlog(db)
    except Exception as error:
        print(f"asset cleanup failed: {error}", file=sys.stderr)
        return 1

    print(
        f"deleted: {result.deleted}; failed: {result.failed}; "
        f"pending: {backlog.pending}; terminal: {backlog.terminal}"
    )
    return 1 if backlog.pending or backlog.terminal else 0


if __name__ == "__main__":
    raise SystemExit(main())
