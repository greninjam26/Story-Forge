from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

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
