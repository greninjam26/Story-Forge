import logging
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import (
    Child,
    GenerationCostEvent,
    GenerationRun,
    GenerationRunStatus,
    Parent,
    Story,
)
from app.schemas import StoryGenerationResult
from app.services import illustration, narration, story_generation
from app.services.cost_tracking import (
    PricingCatalog,
    RunCostRecorder,
    Usage,
    build_pricing_catalog,
)
from app.services.illustration import generate_illustration
from app.services.narration import generate_narration
from app.services.story_generation import generate_story


def test_pricing_catalog_uses_exact_and_provider_default_rates() -> None:
    catalog = PricingCatalog(
        {
            ("provider", "model-a", "token"): Decimal("0.002"),
            ("provider", None, "request"): Decimal("0.01"),
        }
    )

    assert catalog.rate_for("provider", "model-a", "token") == Decimal(
        "0.002"
    )
    assert catalog.rate_for("provider", "model-a", "request") == Decimal(
        "0.01"
    )
    assert catalog.rate_for("provider", "model-a", "image") is None


def test_pricing_catalog_and_usage_reject_negative_values() -> None:
    with pytest.raises(ValueError, match="rates must be non-negative"):
        PricingCatalog(
            {("provider", None, "request"): Decimal("-0.01")}
        )

    with pytest.raises(ValueError, match="quantity must be non-negative"):
        Usage(unit="request", quantity=-1)


def test_default_catalog_prices_stub_usage_at_zero() -> None:
    catalog = build_pricing_catalog()

    assert catalog.rate_for("stub", "story-v1", "request") == Decimal("0")
    assert catalog.rate_for("stub", "image-v1", "image") == Decimal("0")
    assert catalog.rate_for("stub", "voice-v1", "character") == Decimal("0")


def test_default_catalog_prices_real_story_providers() -> None:
    catalog = build_pricing_catalog()

    assert catalog.rate_for(
        "claude",
        settings.anthropic_model,
        "input_token",
    ) == Decimal("0.000003")
    assert catalog.rate_for(
        "claude",
        settings.anthropic_model,
        "output_token",
    ) == Decimal("0.000015")
    assert catalog.rate_for(
        "ollama",
        settings.ollama_model,
        "request",
    ) == Decimal("0")
    assert catalog.rate_for(
        "groq",
        settings.groq_model,
        "input_token",
    ) == Decimal("0")
    assert catalog.rate_for(
        "groq",
        settings.groq_model,
        "output_token",
    ) == Decimal("0")


def test_default_catalog_prices_flux_provider_microcredits() -> None:
    catalog = build_pricing_catalog()

    assert catalog.rate_for(
        "flux",
        settings.image_gen_model,
        "micro_credit",
    ) == Decimal("0.00000001")


def test_default_catalog_prices_cloudflare_images_at_configured_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "cloudflare_ai_cost_per_image_usd",
        Decimal("0.001207"),
    )
    catalog = build_pricing_catalog()

    assert catalog.rate_for(
        "cloudflare",
        settings.cloudflare_ai_model,
        "image",
    ) == Decimal("0.001207")


def test_default_catalog_prices_cloudflare_tts_millineurons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "cloudflare_tts_cost_per_thousand_neurons_usd",
        Decimal("0.011"),
    )
    catalog = build_pricing_catalog()

    assert catalog.rate_for(
        "cloudflare",
        settings.cloudflare_tts_model,
        "millineuron",
    ) == Decimal("0.000000011")


def test_default_catalog_prices_configured_elevenlabs_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "elevenlabs_cost_per_character_usd",
        Decimal("0.0002"),
    )

    catalog = build_pricing_catalog()

    assert catalog.rate_for(
        "elevenlabs",
        "eleven-v3",
        "character",
    ) == Decimal("0.0002")


def test_default_catalog_leaves_unconfigured_elevenlabs_cost_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "elevenlabs_cost_per_character_usd",
        None,
    )

    catalog = build_pricing_catalog()

    assert catalog.rate_for(
        "elevenlabs",
        "eleven-v3",
        "character",
    ) is None


def test_default_catalog_prices_deepinfra_kokoro_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "deepinfra_tts_cost_per_character_usd",
        Decimal("0.00000062"),
    )

    catalog = build_pricing_catalog()

    assert catalog.rate_for(
        "deepinfra",
        settings.deepinfra_tts_model,
        "character",
    ) == Decimal("0.00000062")


def test_run_recorder_persists_stub_events_and_finalizes_story(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        parent = Parent(email="parent@example.com")
        child = Child(name="Camille", age=7)
        story = Story(
            event_text="Camille helped make dinner.",
            language="en",
        )
        child.stories.append(story)
        parent.children.append(child)
        db.add(parent)
        db.commit()

        recorder = RunCostRecorder.start(db)
        recorder.record_call(
            stage="story",
            provider="stub",
            model="story-v1",
            attempt=1,
            outcome="succeeded",
            usage=[Usage(unit="request", quantity=1)],
        )
        recorder.record_call(
            stage="illustration",
            provider="stub",
            model="image-v1",
            attempt=1,
            outcome="succeeded",
            usage=[Usage(unit="image", quantity=1)],
            page_number=1,
        )
        recorder.record_call(
            stage="narration",
            provider="stub",
            model="voice-v1",
            attempt=1,
            outcome="succeeded",
            usage=[Usage(unit="character", quantity=42)],
            page_number=1,
        )
        recorder.finalize(
            status=GenerationRunStatus.SUCCEEDED,
            story=story,
        )

        db.expire_all()
        saved_run = db.get(GenerationRun, recorder.run_id)
        assert saved_run is not None
        assert saved_run.story_id == story.id
        assert saved_run.status is GenerationRunStatus.SUCCEEDED
        assert saved_run.completed_at is not None
        assert saved_run.known_cost_usd == Decimal("0")
        assert saved_run.cost_complete is True
        assert saved_run.ceiling_exceeded is False
        assert story.cost_usd == Decimal("0")
        assert {
            (event.stage, event.usage_unit, event.page_number)
            for event in saved_run.cost_events
        } == {
            ("story", "request", None),
            ("illustration", "image", 1),
            ("narration", "character", 1),
        }
        assert all(event.cost_known for event in saved_run.cost_events)


def test_run_recorder_marks_unknown_costs_incomplete(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recorder = RunCostRecorder.start(
            db,
            catalog=PricingCatalog({}),
        )
        recorder.record_call(
            stage="story",
            provider="unpriced-provider",
            model="model-v1",
            attempt=1,
            outcome="succeeded",
            usage=[Usage(unit="input_token", quantity=25)],
        )
        recorder.record_call(
            stage="narration",
            provider="opaque-provider",
            model=None,
            attempt=1,
            outcome="failed",
            usage=None,
        )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        db.expire_all()
        saved_run = db.get(GenerationRun, recorder.run_id)
        assert saved_run is not None
        assert saved_run.status is GenerationRunStatus.FAILED
        assert saved_run.known_cost_usd == Decimal("0")
        assert saved_run.cost_complete is False
        assert {
            (event.usage_unit, event.quantity, event.cost_known)
            for event in saved_run.cost_events
        } == {
            ("input_token", 25, False),
            ("unknown", None, False),
        }
        assert all(event.cost_usd is None for event in saved_run.cost_events)


def test_run_recorder_totals_multi_unit_call_and_flags_ceiling(
    db_session_factory: sessionmaker[Session],
) -> None:
    catalog = PricingCatalog(
        {
            ("provider", "model-v1", "input_token"): Decimal("0.01"),
            ("provider", "model-v1", "output_token"): Decimal("0.02"),
        }
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(
            db,
            catalog=catalog,
            ceiling_usd=Decimal("0.03"),
        )
        recorder.record_call(
            stage="story",
            provider="provider",
            model="model-v1",
            attempt=1,
            outcome="succeeded",
            usage=[
                Usage(unit="input_token", quantity=2),
                Usage(unit="output_token", quantity=1),
            ],
        )
        assert recorder.known_total == Decimal("0.04")
        recorder.finalize(status=GenerationRunStatus.FAILED)

        db.expire_all()
        saved_run = db.get(GenerationRun, recorder.run_id)
        assert saved_run is not None
        assert saved_run.known_cost_usd == Decimal("0.04")
        assert saved_run.cost_complete is True
        assert saved_run.ceiling_exceeded is True
        assert len({event.call_id for event in saved_run.cost_events}) == 1


def test_run_recorder_buffers_events_until_finalization(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)
        recorder.record_call(
            stage="story",
            provider="stub",
            model=None,
            attempt=1,
            outcome="succeeded",
            usage=[Usage(unit="request", quantity=1)],
        )

        db.expire_all()
        active_run = db.get(GenerationRun, recorder.run_id)
        assert active_run is not None
        assert active_run.status is GenerationRunStatus.IN_PROGRESS
        assert active_run.cost_events == []

        recorder.finalize(status=GenerationRunStatus.FAILED)
        db.expire_all()
        completed_run = db.get(GenerationRun, recorder.run_id)
        assert completed_run is not None
        assert completed_run.status is GenerationRunStatus.FAILED
        assert len(completed_run.cost_events) == 1


def test_run_recorder_persists_accepted_call_before_finalization(
    db_session_factory: sessionmaker[Session],
) -> None:
    catalog = PricingCatalog(
        {("flux", "flux-model", "micro_credit"): Decimal("0.00000001")}
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db, catalog=catalog)

        call_id = recorder.record_accepted_call(
            stage="illustration",
            provider="flux",
            model="flux-model",
            attempt=1,
            usage=[Usage(unit="micro_credit", quantity=1_500_000)],
            page_number=4,
        )

        db.expire_all()
        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.call_id == call_id
            )
        )
        active_run = db.get(GenerationRun, recorder.run_id)
        assert event is not None
        assert event.outcome == "accepted"
        assert event.page_number == 4
        assert event.cost_usd == Decimal("0.015")
        assert active_run is not None
        assert active_run.status is GenerationRunStatus.IN_PROGRESS
        assert active_run.known_cost_usd == Decimal("0.015")

        recorder.update_call_outcome(call_id, "provider_failure")
        recorder.finalize(status=GenerationRunStatus.FAILED)

        db.expire_all()
        events = list(
            db.scalars(
                select(GenerationCostEvent).where(
                    GenerationCostEvent.call_id == call_id
                )
            )
        )
        assert len(events) == 1
        assert events[0].outcome == "provider_failure"


def test_run_recorder_uses_configured_ceiling_by_default(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "story_cost_ceiling_usd",
        Decimal("0.01"),
    )
    catalog = PricingCatalog(
        {("provider", None, "request"): Decimal("0.02")}
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db, catalog=catalog)
        recorder.record_call(
            stage="story",
            provider="provider",
            model=None,
            attempt=1,
            outcome="succeeded",
            usage=[Usage(unit="request", quantity=1)],
        )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        db.expire_all()
        saved_run = db.get(GenerationRun, recorder.run_id)
        assert saved_run is not None
        assert saved_run.ceiling_exceeded is True


def test_run_recorder_warns_once_when_cost_crosses_ceiling(
    db_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = PricingCatalog(
        {("provider", None, "request"): Decimal("0.02")}
    )

    with db_session_factory() as db, caplog.at_level(
        logging.WARNING,
        logger="app.services.cost_tracking",
    ):
        recorder = RunCostRecorder.start(
            db,
            catalog=catalog,
            ceiling_usd=Decimal("0.01"),
        )
        for _ in range(2):
            recorder.record_call(
                stage="story",
                provider="provider",
                model=None,
                attempt=1,
                outcome="succeeded",
                usage=[Usage(unit="request", quantity=1)],
            )

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.cost_tracking"
    ]
    assert len(warnings) == 1
    assert "exceeded cost ceiling" in warnings[0]


def test_run_recorder_only_allows_storyless_failed_run(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(ValueError, match="succeeded run requires a story"):
            recorder.finalize(status=GenerationRunStatus.SUCCEEDED)

        recorder.finalize(status=GenerationRunStatus.FAILED)
        db.expire_all()
        saved_run = db.get(GenerationRun, recorder.run_id)
        assert saved_run is not None
        assert saved_run.story_id is None
        assert saved_run.status is GenerationRunStatus.FAILED
        assert saved_run.completed_at is not None


def test_stub_story_generation_records_zero_cost_request(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        generate_story(
            child_name="Camille",
            age=7,
            interests="stars",
            event_text="Camille helped make dinner.",
            language="en",
            recorder=recorder,
        )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.stage == "story_text"
        assert event.provider == "stub"
        assert event.model is None
        assert event.attempt == 1
        assert event.outcome == "succeeded"
        assert event.usage_unit == "request"
        assert event.quantity == 1
        assert event.cost_usd == Decimal("0")
        assert event.cost_known is True


def test_stub_illustration_records_zero_cost_image(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        generate_illustration(
            avatar_seed="child-id",
            page_number=3,
            page_text="Camille followed the starlight.",
            recorder=recorder,
        )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.stage == "illustration"
        assert event.provider == "stub"
        assert event.model is None
        assert event.attempt == 1
        assert event.outcome == "succeeded"
        assert event.usage_unit == "image"
        assert event.quantity == 1
        assert event.page_number == 3
        assert event.cost_usd == Decimal("0")
        assert event.cost_known is True


def test_stub_narration_records_zero_cost_characters(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        generate_narration(
            text="Good night.",
            language="en",
            recorder=recorder,
        )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.stage == "tts"
        assert event.provider == "stub"
        assert event.model is None
        assert event.attempt == 1
        assert event.outcome == "succeeded"
        assert event.usage_unit == "character"
        assert event.quantity == 11
        assert event.page_number is None
        assert event.cost_usd == Decimal("0")
        assert event.cost_known is True


def test_story_provider_failure_records_attempt(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        def generate(self, **_: object) -> StoryGenerationResult:
            raise RuntimeError("provider unavailable")

    monkeypatch.setitem(
        story_generation._PROVIDERS,
        "stub",
        FailingProvider(),
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(RuntimeError, match="provider unavailable"):
            story_generation.generate_story(
                child_name="Camille",
                age=7,
                interests="stars",
                event_text="Camille helped make dinner.",
                language="en",
                recorder=recorder,
            )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.stage == "story_text"
        assert event.outcome == "provider_failure"
        assert event.cost_known is False


def test_cost_recording_failure_does_not_replace_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        def generate(self, **_: object) -> StoryGenerationResult:
            raise RuntimeError("provider unavailable")

    class FailingRecorder:
        def record_call(self, **_: object) -> None:
            raise RuntimeError("accounting unavailable")

    monkeypatch.setitem(
        story_generation._PROVIDERS,
        "stub",
        FailingProvider(),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        story_generation.generate_story(
            child_name="Camille",
            age=7,
            interests="stars",
            event_text="Camille helped make dinner.",
            language="en",
            recorder=FailingRecorder(),
        )


def test_invalid_story_response_records_attempt(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidProvider:
        def generate(self, **_: object) -> StoryGenerationResult:
            return StoryGenerationResult(title="Too short", pages=["One page."])

    monkeypatch.setitem(
        story_generation._PROVIDERS,
        "stub",
        InvalidProvider(),
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(ValueError, match="Expected 10 pages"):
            story_generation.generate_story(
                child_name="Camille",
                age=7,
                interests="stars",
                event_text="Camille helped make dinner.",
                language="en",
                recorder=recorder,
            )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.stage == "story_text"
        assert event.outcome == "invalid_response"
        assert event.cost_known is True


def test_missing_story_response_records_invalid_attempt(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingProvider:
        def generate(self, **_: object) -> StoryGenerationResult:
            return None  # type: ignore[return-value]

    monkeypatch.setitem(
        story_generation._PROVIDERS,
        "stub",
        MissingProvider(),
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(ValueError, match="invalid result"):
            story_generation.generate_story(
                child_name="Camille",
                age=7,
                interests="stars",
                event_text="Camille helped make dinner.",
                language="en",
                recorder=recorder,
            )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.outcome == "invalid_response"


def test_illustration_provider_failure_records_attempt(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        def generate(self, **_: object) -> str:
            raise RuntimeError("provider unavailable")

    monkeypatch.setitem(
        illustration._PROVIDERS,
        "stub",
        FailingProvider(),
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(RuntimeError, match="provider unavailable"):
            illustration.generate_illustration(
                avatar_seed="child-id",
                page_number=1,
                page_text="A moonlit garden.",
                recorder=recorder,
            )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.stage == "illustration"
        assert event.outcome == "provider_failure"
        assert event.cost_known is False


def test_missing_illustration_response_records_invalid_attempt(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingProvider:
        def generate(self, **_: object) -> str:
            return None  # type: ignore[return-value]

    monkeypatch.setitem(
        illustration._PROVIDERS,
        "stub",
        MissingProvider(),
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(ValueError, match="invalid result"):
            illustration.generate_illustration(
                avatar_seed="child-id",
                page_number=1,
                page_text="A moonlit garden.",
                recorder=recorder,
            )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.outcome == "invalid_response"


def test_narration_provider_failure_records_attempt(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        def generate(self, **_: object) -> str:
            raise RuntimeError("provider unavailable")

    monkeypatch.setitem(
        narration._PROVIDERS,
        "stub",
        FailingProvider(),
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(RuntimeError, match="provider unavailable"):
            narration.generate_narration(
                text="Good night.",
                language="en",
                recorder=recorder,
            )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.stage == "tts"
        assert event.outcome == "provider_failure"
        assert event.cost_known is False


def test_missing_narration_response_records_invalid_attempt(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingProvider:
        def generate(self, **_: object) -> str:
            return None  # type: ignore[return-value]

    monkeypatch.setitem(
        narration._PROVIDERS,
        "stub",
        MissingProvider(),
    )

    with db_session_factory() as db:
        recorder = RunCostRecorder.start(db)

        with pytest.raises(ValueError, match="invalid result"):
            narration.generate_narration(
                text="Good night.",
                language="en",
                recorder=recorder,
            )
        recorder.finalize(status=GenerationRunStatus.FAILED)

        event = db.scalar(
            select(GenerationCostEvent).where(
                GenerationCostEvent.generation_run_id == recorder.run_id
            )
        )
        assert event is not None
        assert event.outcome == "invalid_response"
