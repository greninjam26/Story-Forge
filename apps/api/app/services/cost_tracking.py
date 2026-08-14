import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    GenerationCostEvent,
    GenerationRun,
    GenerationRunStatus,
    Story,
)


logger = logging.getLogger(__name__)

RateKey = tuple[str, str | None, str]
PER_MILLION = Decimal("1000000")
MICROCREDITS_PER_CREDIT = Decimal("1000000")
BFL_USD_PER_CREDIT = Decimal("0.01")


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
    rates = {
        (
            "claude",
            settings.anthropic_model,
            "input_token",
        ): settings.anthropic_input_cost_per_million_usd / PER_MILLION,
        (
            "claude",
            settings.anthropic_model,
            "output_token",
        ): settings.anthropic_output_cost_per_million_usd / PER_MILLION,
        ("ollama", None, "request"): Decimal("0"),
        ("stub", None, "request"): Decimal("0"),
        ("stub", None, "image"): Decimal("0"),
        ("stub", None, "character"): Decimal("0"),
        ("openai", None, "moderation_request"): Decimal("0"),
        ("flux", settings.image_gen_model, "micro_credit"): (
            BFL_USD_PER_CREDIT / MICROCREDITS_PER_CREDIT
        ),
    }
    if settings.elevenlabs_cost_per_character_usd is not None:
        rates[("elevenlabs", None, "character")] = (
            settings.elevenlabs_cost_per_character_usd
        )
    return PricingCatalog(rates)


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

    def record_accepted_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str | None,
        attempt: int,
        usage: Sequence[Usage] | None,
        page_number: int | None = None,
    ) -> UUID: ...

    def update_call_outcome(
        self,
        call_id: UUID,
        outcome: str,
    ) -> None: ...


def record_cost_call(
    recorder: CostRecorder,
    *,
    stage: str,
    provider: str,
    model: str | None,
    attempt: int,
    outcome: str,
    usage: Sequence[Usage] | None,
    page_number: int | None = None,
) -> None:
    """Record accounting data without changing provider-call behavior."""
    try:
        recorder.record_call(
            stage=stage,
            provider=provider,
            model=model,
            attempt=attempt,
            outcome=outcome,
            usage=usage,
            page_number=page_number,
        )
    except Exception:
        logger.exception(
            "failed to record generation cost event for stage=%s",
            stage,
        )


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

    def record_accepted_call(self, **_kwargs: object) -> UUID:
        return uuid4()

    def update_call_outcome(
        self,
        _call_id: UUID,
        _outcome: str,
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
        self._events: list[GenerationCostEvent] = []
        self._persisted_call_ids: set[UUID] = set()
        self._known_total = Decimal("0")
        self._cost_complete = True
        self._ceiling_exceeded = False

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
            (
                ceiling_usd
                if ceiling_usd is not None
                else settings.story_cost_ceiling_usd
            ),
        )

    @property
    def known_total(self) -> Decimal:
        return self._known_total

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
        self._append_call(
            stage=stage,
            provider=provider,
            model=model,
            attempt=attempt,
            outcome=outcome,
            usage=usage,
            page_number=page_number,
        )

    def _append_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str | None,
        attempt: int,
        outcome: str,
        usage: Sequence[Usage] | None,
        page_number: int | None,
    ) -> UUID:
        if usage is not None and not usage:
            raise ValueError("usage must contain at least one item or be None")

        call_id = uuid4()
        if usage is None:
            self._cost_complete = False
            self._events.append(
                GenerationCostEvent(
                    generation_run_id=self.run_id,
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
                    self._cost_complete = False
                else:
                    self._known_total += cost
                self._events.append(
                    GenerationCostEvent(
                        generation_run_id=self.run_id,
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
            and self._known_total > self._ceiling_usd
            and not self._ceiling_exceeded
        ):
            logger.warning(
                "generation run %s exceeded cost ceiling: known=%s ceiling=%s",
                self.run_id,
                self._known_total,
                self._ceiling_usd,
            )
            self._ceiling_exceeded = True
        return call_id

    def record_accepted_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str | None,
        attempt: int,
        usage: Sequence[Usage] | None,
        page_number: int | None = None,
    ) -> UUID:
        """Persist an accepted provider charge before work continues."""
        call_id = self._append_call(
            stage=stage,
            provider=provider,
            model=model,
            attempt=attempt,
            outcome="accepted",
            usage=usage,
            page_number=page_number,
        )
        run = self._get_run()
        self._db.add_all(
            event for event in self._events if event.call_id == call_id
        )
        run.known_cost_usd = self._known_total
        run.cost_complete = self._cost_complete
        run.ceiling_exceeded = self._ceiling_exceeded
        self._db.commit()
        self._persisted_call_ids.add(call_id)
        return call_id

    def update_call_outcome(
        self,
        call_id: UUID,
        outcome: str,
    ) -> None:
        if call_id not in self._persisted_call_ids:
            raise ValueError("provider call was not persisted as accepted")
        matching_events = [
            event for event in self._events if event.call_id == call_id
        ]
        if not matching_events:
            raise ValueError("provider call does not exist")
        for event in matching_events:
            event.outcome = outcome
        self._db.commit()

    def finalize(
        self,
        *,
        status: GenerationRunStatus,
        story: Story | None = None,
        refresh_story: bool = True,
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
        run.known_cost_usd = self._known_total
        run.cost_complete = self._cost_complete
        run.ceiling_exceeded = self._ceiling_exceeded
        self._db.add_all(
            event
            for event in self._events
            if event.call_id not in self._persisted_call_ids
        )
        if story is not None and status in {
            GenerationRunStatus.SUCCEEDED,
            GenerationRunStatus.REJECTED,
        }:
            run.story = story
            story.cost_usd = self._known_total
        self._db.commit()
        if story is not None and refresh_story:
            self._db.refresh(story)

    def _get_run(self) -> GenerationRun:
        run = self._db.get(GenerationRun, self.run_id)
        if run is None:
            raise RuntimeError("generation run no longer exists")
        return run
