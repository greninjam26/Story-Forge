import argparse
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.cost_reporting import CostReport, build_cost_report


def format_cost_report(report: CostReport) -> str:
    if report.actual_runs == 0:
        lines = ["no completed generation runs"]
        if report.in_progress_runs:
            oldest_active = (
                report.oldest_in_progress_at.isoformat()
                if report.oldest_in_progress_at
                else "n/a"
            )
            lines.append(
                f"In progress: {report.in_progress_runs} "
                f"oldest={oldest_active}"
            )
        return "\n".join(lines)

    qualifier = " (lower bound)" if report.is_lower_bound else ""
    window_start = (
        report.earliest_completed_at.isoformat()
        if report.earliest_completed_at
        else "n/a"
    )
    window_end = (
        report.latest_completed_at.isoformat()
        if report.latest_completed_at
        else "n/a"
    )
    oldest_active = (
        report.oldest_in_progress_at.isoformat()
        if report.oldest_in_progress_at
        else "n/a"
    )
    effective_cost = (
        "Effective/success: n/a"
        if report.effective_per_success_usd is None
        else (
            f"Effective/success{qualifier}: "
            f"${report.effective_per_success_usd:.6f}"
        )
    )
    lines = [
        (
            f"Cost report: {report.actual_runs} of requested "
            f"{report.requested_limit} terminal runs"
        ),
        f"Window: {window_start} to {window_end}",
        (
            f"Runs: succeeded={report.succeeded_runs} "
            f"rejected={report.rejected_runs} failed={report.failed_runs}"
        ),
        f"Known spend{qualifier}: ${report.known_total_usd:.6f}",
        (
            f"Average/request{qualifier}: "
            f"${report.average_per_request_usd:.6f}"
        ),
        effective_cost,
        f"Unknown: events={report.unknown_events} runs={report.unknown_runs}",
        f"Ceiling exceeded: {report.ceiling_exceeded_runs}",
        f"In progress: {report.in_progress_runs} oldest={oldest_active}",
        "Breakdown:",
    ]
    for row in report.breakdown:
        model = row.model or "-"
        lines.append(
            f"  {row.stage:<13} {row.provider:<12} {model:<24} "
            f"calls={row.call_count:<4} known=${row.known_cost_usd:.6f}"
        )
    return "\n".join(lines)


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
