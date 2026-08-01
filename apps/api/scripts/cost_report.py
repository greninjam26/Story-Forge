import argparse
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.cost_tracking import build_cost_report, format_cost_report


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
        description="Report Story Forge generation costs"
    )
    parser.add_argument(
        "--last",
        type=positive_int,
        default=100,
        help="terminal runs to include (default: 100)",
    )
    args = parser.parse_args(argv)

    try:
        with session_factory() as db:
            report = build_cost_report(db, last=args.last)
    except Exception as exc:
        print(f"cost report failed: {exc}", file=sys.stderr)
        return 1

    print(format_cost_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
