from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    GenerationCostEvent,
    GenerationRun,
    GenerationRunStatus,
)
from app.services import cost_reporting
from scripts.cost_report import format_cost_report


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _known_event(
    *,
    call_id,
    stage: str,
    provider: str,
    model: str | None,
    usage_unit: str,
    cost_usd: Decimal,
) -> GenerationCostEvent:
    return GenerationCostEvent(
        call_id=call_id,
        stage=stage,
        provider=provider,
        model=model,
        attempt=1,
        outcome="succeeded",
        usage_unit=usage_unit,
        quantity=1,
        unit_rate_usd=cost_usd,
        cost_usd=cost_usd,
        cost_known=True,
    )


def test_cost_report_aggregates_most_recent_terminal_runs(
    db_session_factory: sessionmaker[Session],
) -> None:
    story_call_id = uuid4()
    succeeded_run = GenerationRun(
        status=GenerationRunStatus.SUCCEEDED,
        started_at=datetime(2026, 1, 3, 11, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 3, 12, tzinfo=timezone.utc),
        known_cost_usd=Decimal("0.05"),
    )
    succeeded_run.cost_events.extend(
        [
            _known_event(
                call_id=story_call_id,
                stage="story_text",
                provider="claude",
                model="model-a",
                usage_unit="input_token",
                cost_usd=Decimal("0.02"),
            ),
            _known_event(
                call_id=story_call_id,
                stage="story_text",
                provider="claude",
                model="model-a",
                usage_unit="output_token",
                cost_usd=Decimal("0.03"),
            ),
        ]
    )

    failed_run = GenerationRun(
        status=GenerationRunStatus.FAILED,
        started_at=datetime(2026, 1, 2, 11, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        known_cost_usd=Decimal("0.02"),
        cost_complete=False,
        ceiling_exceeded=True,
    )
    failed_run.cost_events.extend(
        [
            _known_event(
                call_id=uuid4(),
                stage="illustration",
                provider="flux",
                model="model-b",
                usage_unit="image",
                cost_usd=Decimal("0.02"),
            ),
            GenerationCostEvent(
                call_id=uuid4(),
                stage="tts",
                provider="opaque",
                model=None,
                attempt=1,
                outcome="provider_failure",
                usage_unit="unknown",
                quantity=None,
                unit_rate_usd=None,
                cost_usd=None,
                cost_known=False,
            ),
        ]
    )

    excluded_rejected_run = GenerationRun(
        status=GenerationRunStatus.REJECTED,
        started_at=datetime(2026, 1, 1, 11, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        known_cost_usd=Decimal("0.50"),
    )
    active_run = GenerationRun(
        status=GenerationRunStatus.IN_PROGRESS,
        started_at=datetime(2026, 1, 4, 12, tzinfo=timezone.utc),
    )

    with db_session_factory() as db:
        db.add_all(
            [
                succeeded_run,
                failed_run,
                excluded_rejected_run,
                active_run,
            ]
        )
        db.commit()

        report = cost_reporting.build_cost_report(db, last=2)

        assert report.requested_limit == 2
        assert report.actual_runs == 2
        assert report.succeeded_runs == 1
        assert report.rejected_runs == 0
        assert report.failed_runs == 1
        assert report.known_total_usd == Decimal("0.07")
        assert report.average_per_request_usd == Decimal("0.035")
        assert report.effective_per_success_usd == Decimal("0.07")
        assert report.ceiling_exceeded_runs == 1
        assert report.unknown_events == 1
        assert report.unknown_runs == 1
        assert report.is_lower_bound is True
        assert report.in_progress_runs == 1
        assert _as_utc(report.earliest_completed_at) == datetime(
            2026, 1, 2, 12, tzinfo=timezone.utc
        )
        assert _as_utc(report.latest_completed_at) == datetime(
            2026, 1, 3, 12, tzinfo=timezone.utc
        )
        assert _as_utc(report.oldest_in_progress_at) == datetime(
            2026, 1, 4, 12, tzinfo=timezone.utc
        )
        assert [
            (
                row.stage,
                row.provider,
                row.model,
                row.call_count,
                row.known_cost_usd,
            )
            for row in report.breakdown
        ] == [
            ("illustration", "flux", "model-b", 1, Decimal("0.02")),
            ("story_text", "claude", "model-a", 1, Decimal("0.05")),
            ("tts", "opaque", None, 1, Decimal("0")),
        ]


def test_cost_report_rejects_nonpositive_limit(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        with pytest.raises(ValueError, match="last must be positive"):
            cost_reporting.build_cost_report(db, last=0)


def test_cost_report_handles_window_without_terminal_runs(
    db_session_factory: sessionmaker[Session],
) -> None:
    active_started_at = datetime(2026, 1, 4, 12, tzinfo=timezone.utc)

    with db_session_factory() as db:
        db.add(
            GenerationRun(
                status=GenerationRunStatus.IN_PROGRESS,
                started_at=active_started_at,
            )
        )
        db.commit()

        report = cost_reporting.build_cost_report(db, last=10)

        assert report.requested_limit == 10
        assert report.actual_runs == 0
        assert report.known_total_usd == Decimal("0")
        assert report.average_per_request_usd is None
        assert report.effective_per_success_usd is None
        assert report.is_lower_bound is False
        assert report.breakdown == ()
        assert report.in_progress_runs == 1
        assert _as_utc(report.oldest_in_progress_at) == active_started_at
        assert format_cost_report(report) == (
            "no completed generation runs\n"
            "In progress: 1 oldest=2026-01-04T12:00:00"
        )


def test_format_cost_report_labels_unknown_costs_as_lower_bounds() -> None:
    report = cost_reporting.CostReport(
        requested_limit=100,
        actual_runs=2,
        earliest_completed_at=datetime(
            2026, 1, 2, 12, tzinfo=timezone.utc
        ),
        latest_completed_at=datetime(
            2026, 1, 3, 12, tzinfo=timezone.utc
        ),
        succeeded_runs=1,
        rejected_runs=0,
        failed_runs=1,
        known_total_usd=Decimal("0.07"),
        average_per_request_usd=Decimal("0.035"),
        effective_per_success_usd=Decimal("0.07"),
        ceiling_exceeded_runs=1,
        unknown_events=1,
        unknown_runs=1,
        in_progress_runs=1,
        oldest_in_progress_at=datetime(
            2026, 1, 4, 12, tzinfo=timezone.utc
        ),
        breakdown=(
            cost_reporting.CostBreakdown(
                stage="story_text",
                provider="claude",
                model="model-a",
                call_count=1,
                known_cost_usd=Decimal("0.05"),
            ),
            cost_reporting.CostBreakdown(
                stage="tts",
                provider="opaque",
                model=None,
                call_count=1,
                known_cost_usd=Decimal("0"),
            ),
        ),
    )

    assert format_cost_report(report) == (
        "Cost report: 2 of requested 100 terminal runs\n"
        "Window: 2026-01-02T12:00:00+00:00 to "
        "2026-01-03T12:00:00+00:00\n"
        "Runs: succeeded=1 rejected=0 failed=1\n"
        "Known spend (lower bound): $0.070000\n"
        "Average/request (lower bound): $0.035000\n"
        "Effective/success (lower bound): $0.070000\n"
        "Unknown: events=1 runs=1\n"
        "Ceiling exceeded: 1\n"
        "In progress: 1 oldest=2026-01-04T12:00:00+00:00\n"
        "Breakdown:\n"
        "  story_text    claude       model-a                  "
        "calls=1    known=$0.050000\n"
        "  tts           opaque       -                        "
        "calls=1    known=$0.000000"
    )
