from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import GenerationRun, GenerationRunStatus


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    stage: str
    provider: str
    model: str | None
    call_count: int
    known_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class CostReport:
    requested_limit: int
    actual_runs: int
    earliest_completed_at: datetime | None
    latest_completed_at: datetime | None
    succeeded_runs: int
    rejected_runs: int
    failed_runs: int
    known_total_usd: Decimal
    average_per_request_usd: Decimal | None
    effective_per_success_usd: Decimal | None
    ceiling_exceeded_runs: int
    unknown_events: int
    unknown_runs: int
    in_progress_runs: int
    oldest_in_progress_at: datetime | None
    breakdown: tuple[CostBreakdown, ...]

    @property
    def is_lower_bound(self) -> bool:
        return self.unknown_runs > 0


def build_cost_report(db: Session, *, last: int) -> CostReport:
    if last < 1:
        raise ValueError("last must be positive")

    terminal_statuses = (
        GenerationRunStatus.SUCCEEDED,
        GenerationRunStatus.REJECTED,
        GenerationRunStatus.FAILED,
    )
    runs = list(
        db.scalars(
            select(GenerationRun)
            .where(GenerationRun.status.in_(terminal_statuses))
            .options(selectinload(GenerationRun.cost_events))
            .order_by(
                GenerationRun.completed_at.desc(),
                GenerationRun.id.desc(),
            )
            .limit(last)
        )
    )
    events = [event for run in runs for event in run.cost_events]
    unknown_events = [event for event in events if not event.cost_known]
    known_total = sum(
        (run.known_cost_usd for run in runs),
        Decimal("0"),
    )
    succeeded_runs = sum(
        run.status is GenerationRunStatus.SUCCEEDED for run in runs
    )

    group_calls: dict[tuple[str, str, str | None], set[UUID]] = {}
    group_costs: dict[tuple[str, str, str | None], Decimal] = {}
    for event in events:
        key = (event.stage, event.provider, event.model)
        group_calls.setdefault(key, set()).add(event.call_id)
        group_costs.setdefault(key, Decimal("0"))
        if event.cost_usd is not None:
            group_costs[key] += event.cost_usd
    breakdown = tuple(
        CostBreakdown(
            stage=stage,
            provider=provider,
            model=model,
            call_count=len(group_calls[key]),
            known_cost_usd=group_costs[key],
        )
        for key in sorted(
            group_calls,
            key=lambda item: (item[0], item[1], item[2] or ""),
        )
        for stage, provider, model in (key,)
    )

    in_progress_runs = list(
        db.scalars(
            select(GenerationRun).where(
                GenerationRun.status == GenerationRunStatus.IN_PROGRESS
            )
        )
    )
    completed_at = [
        run.completed_at for run in runs if run.completed_at is not None
    ]
    return CostReport(
        requested_limit=last,
        actual_runs=len(runs),
        earliest_completed_at=(
            min(completed_at) if completed_at else None
        ),
        latest_completed_at=max(completed_at) if completed_at else None,
        succeeded_runs=succeeded_runs,
        rejected_runs=sum(
            run.status is GenerationRunStatus.REJECTED for run in runs
        ),
        failed_runs=sum(
            run.status is GenerationRunStatus.FAILED for run in runs
        ),
        known_total_usd=known_total,
        average_per_request_usd=(
            known_total / len(runs) if runs else None
        ),
        effective_per_success_usd=(
            known_total / succeeded_runs if succeeded_runs else None
        ),
        ceiling_exceeded_runs=sum(run.ceiling_exceeded for run in runs),
        unknown_events=len(unknown_events),
        unknown_runs=len(
            {event.generation_run_id for event in unknown_events}
        ),
        in_progress_runs=len(in_progress_runs),
        oldest_in_progress_at=min(
            (run.started_at for run in in_progress_runs),
            default=None,
        ),
        breakdown=breakdown,
    )
