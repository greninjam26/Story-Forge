from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    GenerationCostEvent,
    GenerationRun,
    GenerationRunStatus,
    Story,
)


RateKey = tuple[str, str | None, str]


@dataclass(frozen=True, slots=True)
class Usage:
    unit: str
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError("usage quantity must be non-negative")


class PricingCatalog:
    def __init__(self, rates: dict[RateKey, Decimal]):
        if any(rate < 0 for rate in rates.values()):
            raise ValueError("cost rates must be non-negative")
        self._rates = rates.copy()

    def rate_for(
        self,
        provider: str,
        model: str | None,
        unit: str,
    ) -> Decimal | None:
        return self._rates.get(
            (provider, model, unit),
            self._rates.get((provider, None, unit)),
        )


def build_pricing_catalog() -> PricingCatalog:
    return PricingCatalog(
        {
            ("stub", None, "request"): Decimal("0"),
            ("stub", None, "image"): Decimal("0"),
            ("stub", None, "character"): Decimal("0"),
        }
    )


class CostRecorder(Protocol):
    def record_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str | None,
        attempt: int,
        outcome: str,
        usage: Sequence[Usage] | None,
        page_number: int | None = None,
    ) -> None: ...


class NoopCostRecorder:
    def record_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str | None,
        attempt: int,
        outcome: str,
        usage: Sequence[Usage] | None,
        page_number: int | None = None,
    ) -> None:
        return None


NOOP_COST_RECORDER: CostRecorder = NoopCostRecorder()


class RunCostRecorder:
    def __init__(
        self,
        db: Session,
        run_id: UUID,
        catalog: PricingCatalog,
        ceiling_usd: Decimal | None,
    ) -> None:
        if ceiling_usd is not None and ceiling_usd < 0:
            raise ValueError("cost ceiling must be non-negative")
        self._db = db
        self.run_id = run_id
        self._catalog = catalog
        self._ceiling_usd = ceiling_usd

    @classmethod
    def start(
        cls,
        db: Session,
        *,
        catalog: PricingCatalog | None = None,
        ceiling_usd: Decimal | None = None,
    ) -> "RunCostRecorder":
        run = GenerationRun()
        db.add(run)
        db.commit()
        db.refresh(run)
        return cls(
            db,
            run.id,
            catalog or build_pricing_catalog(),
            ceiling_usd,
        )

    @property
    def known_total(self) -> Decimal:
        return self._get_run().known_cost_usd

    def record_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str | None,
        attempt: int,
        outcome: str,
        usage: Sequence[Usage] | None,
        page_number: int | None = None,
    ) -> None:
        if usage is not None and not usage:
            raise ValueError("usage must contain at least one item or be None")

        run = self._get_run()
        call_id = uuid4()
        if usage is None:
            run.cost_complete = False
            run.cost_events.append(
                GenerationCostEvent(
                    call_id=call_id,
                    stage=stage,
                    provider=provider,
                    model=model,
                    attempt=attempt,
                    page_number=page_number,
                    outcome=outcome,
                    usage_unit="unknown",
                    quantity=None,
                    unit_rate_usd=None,
                    cost_usd=None,
                    cost_known=False,
                )
            )
        else:
            for item in usage:
                rate = self._catalog.rate_for(provider, model, item.unit)
                cost = rate * item.quantity if rate is not None else None
                if cost is None:
                    run.cost_complete = False
                else:
                    run.known_cost_usd += cost
                run.cost_events.append(
                    GenerationCostEvent(
                        call_id=call_id,
                        stage=stage,
                        provider=provider,
                        model=model,
                        attempt=attempt,
                        page_number=page_number,
                        outcome=outcome,
                        usage_unit=item.unit,
                        quantity=item.quantity,
                        unit_rate_usd=rate,
                        cost_usd=cost,
                        cost_known=cost is not None,
                    )
                )
        if (
            self._ceiling_usd is not None
            and run.known_cost_usd > self._ceiling_usd
        ):
            run.ceiling_exceeded = True
        self._db.commit()

    def finalize(
        self,
        *,
        status: GenerationRunStatus,
        story: Story | None = None,
    ) -> None:
        if status is GenerationRunStatus.IN_PROGRESS:
            raise ValueError("final status cannot be in progress")
        if (
            status
            in {GenerationRunStatus.SUCCEEDED, GenerationRunStatus.REJECTED}
            and story is None
        ):
            raise ValueError(f"{status.value} run requires a story")

        run = self._get_run()
        run.status = status
        run.completed_at = datetime.now(timezone.utc)
        if story is not None:
            run.story = story
            story.cost_usd = run.known_cost_usd
        self._db.commit()
        if story is not None:
            self._db.refresh(story)

    def _get_run(self) -> GenerationRun:
        run = self._db.get(GenerationRun, self.run_id)
        if run is None:
            raise RuntimeError("generation run no longer exists")
        return run


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
