from typing import Any

import pytest

from app.config import settings
from app.services import openai_moderation, safety
from app.services.cost_tracking import Usage


class RecordingCostRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_call(self, **values: Any) -> None:
        self.calls.append(values)


def _result(
    *,
    flagged: bool = False,
    categories: dict[str, bool] | None = None,
    scores: dict[str, float] | None = None,
) -> openai_moderation.ModerationResult:
    categories = categories or {"violence": False}
    return openai_moderation.ModerationResult(
        flagged=flagged,
        categories=categories,
        category_scores=scores or {
            name: 0.01 for name in categories
        },
    )


def _response(
    *results: openai_moderation.ModerationResult,
) -> openai_moderation.ModerationResponse:
    return openai_moderation.ModerationResponse(
        request_id="req_test_123",
        model="omni-moderation-test",
        results=tuple(results),
    )


def test_stub_returns_safe_decision_without_a_provider_cost() -> None:
    recorder = RecordingCostRecorder()

    decision = safety.check_story(
        "Camille and the Moon Garden",
        ["Camille learned a new skill."],
        recorder=recorder,
    )

    assert decision == safety.SafetyDecision(is_safe=True)
    assert recorder.calls == []


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("A weapon appeared.", "violence"),
        ("Camille a trouvé une arme.", "violence"),
        ("The character mentioned suicide.", "self_harm"),
        ("Le personnage a trouvé de l'alcool.", "illicit"),
    ],
)
def test_keyword_prefilter_maps_english_and_french_terms(
    text: str,
    reason: str,
) -> None:
    decision = safety.check_story("A Calm Evening", [text])

    assert decision.is_safe is False
    assert decision.reason_code == reason
    assert decision.provider == "keyword"
    assert decision.flagged_item_kind == "page"
    assert decision.flagged_page_number == 1
    assert decision.flagged_text == text
    assert decision.categories == (reason,)
    assert decision.category_scores == {}


def test_keyword_prefilter_checks_title_then_pages_and_keeps_boundaries() -> None:
    title_decision = safety.check_story(
        "The Hidden Weapon",
        ["There was blood on the path."],
    )
    safe_decision = safety.check_story(
        "Chess Night",
        ["Camille learned a new skill and sounded the alarm."],
    )

    assert title_decision.flagged_item_kind == "title"
    assert title_decision.flagged_page_number is None
    assert title_decision.flagged_text == "The Hidden Weapon"
    assert safe_decision.is_safe is True


def test_keyword_hit_skips_openai_and_cost_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(
        safety.openai_moderation,
        "moderate",
        lambda _inputs: pytest.fail("keyword hit must not call OpenAI"),
    )
    recorder = RecordingCostRecorder()

    decision = safety.check_story(
        "A weapon appears",
        ["This page is otherwise safe."],
        recorder=recorder,
    )

    assert decision.provider == "keyword"
    assert recorder.calls == []


def test_openai_receives_title_and_pages_in_one_ordered_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "openai")
    received: list[list[str]] = []

    def moderate(inputs: list[str]) -> openai_moderation.ModerationResponse:
        received.append(list(inputs))
        return _response(_result(), _result(), _result())

    monkeypatch.setattr(safety.openai_moderation, "moderate", moderate)
    recorder = RecordingCostRecorder()

    decision = safety.check_story(
        "A Safe Title",
        ["page one", "page two"],
        recorder=recorder,
    )

    assert decision.is_safe is True
    assert received == [["A Safe Title", "page one", "page two"]]
    assert recorder.calls == [{
        "stage": "moderation",
        "provider": "openai",
        "model": "omni-moderation-test",
        "attempt": 1,
        "outcome": "succeeded",
        "usage": (Usage("moderation_request", 1),),
        "page_number": None,
    }]


def test_openai_keeps_only_the_first_flagged_item_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(
        safety.openai_moderation,
        "moderate",
        lambda _inputs: _response(
            _result(),
            _result(
                flagged=True,
                categories={
                    "violence": True,
                    "sexual": False,
                    "new-category": True,
                },
                scores={
                    "violence": 0.91,
                    "sexual": 0.02,
                    "new-category": 0.88,
                },
            ),
            _result(
                flagged=True,
                categories={"sexual/minors": True},
                scores={"sexual/minors": 0.99},
            ),
        ),
    )

    decision = safety.check_story(
        "Title",
        ["first page", "second page"],
    )

    assert decision.reason_code == "violence"
    assert decision.provider == "openai"
    assert decision.provider_model == "omni-moderation-test"
    assert decision.provider_request_id == "req_test_123"
    assert decision.flagged_item_kind == "page"
    assert decision.flagged_page_number == 1
    assert decision.flagged_text == "first page"
    assert decision.categories == ("violence", "new-category")
    assert decision.category_scores == {
        "violence": 0.91,
        "new-category": 0.88,
    }


def test_openai_maps_a_flagged_title_to_no_page_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(
        safety.openai_moderation,
        "moderate",
        lambda _inputs: _response(
            _result(
                flagged=True,
                categories={"harassment": True},
                scores={"harassment": 0.9},
            ),
            _result(),
        ),
    )

    decision = safety.check_story("Unsafe title", ["safe page"])

    assert decision.reason_code == "hate_or_harassment"
    assert decision.flagged_item_kind == "title"
    assert decision.flagged_page_number is None
    assert decision.flagged_text == "Unsafe title"


@pytest.mark.parametrize(
    ("categories", "expected_reason"),
    [
        ({"sexual/minors": True, "violence": True}, "sexual"),
        ({"self-harm/instructions": True, "violence": True}, "self_harm"),
        ({"illicit/violent": True, "illicit": True}, "violence"),
        (
            {"harassment/threatening": True, "illicit": True},
            "hate_or_harassment",
        ),
        ({"illicit": True}, "illicit"),
        ({"provider-category-added-later": True}, "unsafe_content"),
        ({"violence": False}, "unsafe_content"),
    ],
)
def test_openai_categories_use_stable_parent_reason_priority(
    monkeypatch: pytest.MonkeyPatch,
    categories: dict[str, bool],
    expected_reason: str,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(
        safety.openai_moderation,
        "moderate",
        lambda _inputs: _response(
            _result(
                flagged=True,
                categories=categories,
                scores={name: 0.9 for name in categories},
            ),
            _result(),
        ),
    )

    decision = safety.check_story("Title", ["page"])

    assert decision.reason_code == expected_reason


def test_openai_failure_records_attempt_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(
        settings,
        "openai_moderation_model",
        "configured-model",
    )

    def fail(_inputs: list[str]) -> None:
        raise openai_moderation.ModerationProviderError(
            "private provider detail"
        )

    monkeypatch.setattr(safety.openai_moderation, "moderate", fail)
    recorder = RecordingCostRecorder()

    with pytest.raises(
        safety.SafetyReviewUnavailable,
        match="safety review is unavailable",
    ) as error:
        safety.check_story("Title", ["page"], recorder=recorder)

    assert "private" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert recorder.calls == [{
        "stage": "moderation",
        "provider": "openai",
        "model": "configured-model",
        "attempt": 1,
        "outcome": "provider_failure",
        "usage": (Usage("moderation_request", 1),),
        "page_number": None,
    }]


def test_unknown_safety_provider_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "safety_provider", "typo")

    with pytest.raises(
        safety.SafetyConfigurationError,
        match="SAFETY_PROVIDER",
    ):
        safety.check_story("Title", ["page"])
