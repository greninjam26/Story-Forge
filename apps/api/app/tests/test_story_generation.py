import json
import traceback
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.schemas import StoryGenerationResult, StoryLanguage
from app.services import story_generation, story_providers as provider_module
from app.services.cost_tracking import Usage
from app.services.story_providers import (
    ClaudeStoryProvider,
    StoryProviderResponse,
)
from app.services.story_generation import (
    age_band_for,
    generate_story,
    page_count_for_age,
)


@pytest.fixture(autouse=True)
def use_stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "story_provider", "stub")


@pytest.mark.parametrize(
    ("age", "band_name", "page_count"),
    [
        (1, "early", 8),
        (4, "early", 8),
        (5, "growing", 10),
        (7, "growing", 10),
        (8, "independent", 12),
        (12, "independent", 12),
    ],
)
def test_age_bands_define_page_count(
    age: int,
    band_name: str,
    page_count: int,
) -> None:
    assert age_band_for(age).name == band_name
    assert page_count_for_age(age) == page_count


@pytest.mark.parametrize("age", [0, 13])
def test_age_band_rejects_unsupported_age(age: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 12"):
        age_band_for(age)


def test_story_schema_requires_exact_page_count() -> None:
    schema = story_generation.story_schema(10)

    pages = schema["properties"]["pages"]
    assert pages["minItems"] == 10
    assert pages["maxItems"] == 10
    assert schema["required"] == ["title", "pages"]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("language", "language_name"),
    [("en", "English"), ("fr", "French")],
)
def test_story_prompt_includes_language_age_and_child_context(
    language: StoryLanguage,
    language_name: str,
) -> None:
    prompt = story_generation.build_story_prompt(
        child_name="Camille",
        age=3,
        age_band=age_band_for(3),
        interests="stars",
        event_text="Camille helped make dinner.",
        language=language,
    )

    assert f"Write the story in {language_name}." in prompt.system
    assert "exactly 8 page strings" in prompt.system
    assert "very short sentences" in prompt.system
    assert "Child name: Camille" in prompt.user
    assert "Interests: stars" in prompt.user
    assert "Today's event: Camille helped make dinner." in prompt.user


@pytest.mark.parametrize(
    ("age", "expected_guidance"),
    [
        (6, "simple cause and effect"),
        (10, "richer vocabulary and sentence structure"),
    ],
)
def test_story_prompt_adjusts_language_complexity_by_age(
    age: int,
    expected_guidance: str,
) -> None:
    prompt = story_generation.build_story_prompt(
        child_name="Camille",
        age=age,
        age_band=age_band_for(age),
        interests="stars",
        event_text="Camille helped make dinner.",
        language="en",
    )

    assert expected_guidance in prompt.system


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize(("age", "expected_pages"), [(3, 8), (6, 10), (10, 12)])
def test_stub_returns_validated_exact_page_count(
    age: int,
    expected_pages: int,
    language: StoryLanguage,
) -> None:
    story = generate_story(
        child_name="Camille",
        age=age,
        interests="stars",
        event_text="Camille helped make dinner.",
        language=language,
    )

    assert isinstance(story, StoryGenerationResult)
    assert len(story.pages) == expected_pages
    assert all(page.strip() for page in story.pages)


def test_stub_is_deterministic() -> None:
    story_data = {
        "child_name": "Camille",
        "age": 7,
        "interests": "dinosaurs",
        "event_text": "Camille shared a favorite toy.",
        "language": "en",
    }

    first_story = generate_story(**story_data)
    second_story = generate_story(**story_data)

    assert first_story == second_story


def test_stub_accepts_maximum_length_event_text() -> None:
    story = generate_story(
        child_name="Camille",
        age=3,
        interests="stars",
        event_text="a" * 2000,
        language="en",
    )

    assert len(story.pages) == 8


def test_stub_generates_english_story() -> None:
    story = generate_story(
        child_name="Camille",
        age=6,
        interests="dinosaurs",
        event_text="Camille shared a favorite toy.",
        language="en",
    )

    assert story.title == "Camille and the Gentle Star"
    assert any("dinosaurs" in page for page in story.pages)
    assert any("courage" in page for page in story.pages)


def test_stub_generates_french_story() -> None:
    story = generate_story(
        child_name="Camille",
        age=6,
        interests="les dinosaures",
        event_text="Camille a partagé son jouet préféré.",
        language="fr",
    )

    assert story.title == "Camille et la douce étoile"
    assert any("les dinosaures" in page for page in story.pages)
    assert any("courage" in page for page in story.pages)


@pytest.mark.parametrize(
    ("age", "expected_text"),
    [
        (
            3,
            "Camille a retrouvé la sécurité, la fierté et le calme avant de dormir.",
        ),
        (
            6,
            "La fierté de Camille a grandi après ce choix courageux et bienveillant.",
        ),
        (
            10,
            "Ce soir-là, le sommeil est venu paisiblement, avec la fierté du chemin parcouru.",
        ),
    ],
)
def test_stub_uses_gender_neutral_french_wording(
    age: int,
    expected_text: str,
) -> None:
    story = generate_story(
        child_name="Camille",
        age=age,
        interests="les étoiles",
        event_text="Camille a essayé quelque chose de nouveau.",
        language="fr",
    )

    assert expected_text in story.pages


def test_stub_uses_language_specific_default_interest() -> None:
    english_story = generate_story(
        child_name="Camille",
        age=6,
        interests="",
        event_text="Camille tried something new.",
        language="en",
    )
    french_story = generate_story(
        child_name="Camille",
        age=6,
        interests="",
        event_text="Camille a essayé quelque chose de nouveau.",
        language="fr",
    )

    assert any("the stars" in page for page in english_story.pages)
    assert any("les étoiles" in page for page in french_story.pages)


def test_stub_increases_language_complexity_with_age() -> None:
    stories = [
        generate_story(
            child_name="Camille",
            age=age,
            interests="stars",
            event_text="A small challenge appeared.",
            language="en",
        )
        for age in (3, 6, 10)
    ]
    average_words = [
        sum(len(page.split()) for page in story.pages) / len(story.pages)
        for story in stories
    ]

    assert average_words[0] < average_words[1] < average_words[2]


@pytest.mark.parametrize(
    ("child_name", "event_text", "message"),
    [("", "A good day.", "Child name"), ("Camille", "", "Event text")],
)
def test_stub_rejects_empty_required_text(
    child_name: str,
    event_text: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        generate_story(
            child_name=child_name,
            age=6,
            interests="stars",
            event_text=event_text,
            language="en",
        )


def test_generate_story_rejects_unsupported_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "story_provider", "unknown")

    with pytest.raises(ValueError, match="Unsupported story provider"):
        generate_story(
            child_name="Camille",
            age=6,
            interests="stars",
            event_text="A good day.",
            language="en",
        )


def test_generate_story_rejects_unsupported_language() -> None:
    invalid_language = cast(StoryLanguage, "es")

    with pytest.raises(ValueError, match="Unsupported story language"):
        generate_story(
            child_name="Camille",
            age=6,
            interests="stars",
            event_text="A good day.",
            language=invalid_language,
        )


def test_claude_story_is_validated_and_records_token_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Recorder:
        def record_call(self, **values: Any) -> None:
            calls.append(values)

    def generate(
        _provider: ClaudeStoryProvider,
        _request: object,
    ) -> StoryProviderResponse:
        return StoryProviderResponse(
            payload={
                "title": "Camille's Gentle Evening",
                "pages": [f"Page {number}." for number in range(1, 11)],
            },
            provider="claude",
            model="claude-test",
            usage=(
                Usage("input_token", 120),
                Usage("output_token", 45),
            ),
        )

    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    monkeypatch.setattr(ClaudeStoryProvider, "generate", generate)

    story = generate_story(
        child_name="Camille",
        age=6,
        interests="stars",
        event_text="Camille helped make dinner.",
        language="en",
        recorder=Recorder(),
    )

    assert story.title == "Camille's Gentle Evening"
    assert len(story.pages) == 10
    assert calls == [
        {
            "stage": "story_text",
            "provider": "claude",
            "model": "claude-test",
            "attempt": 1,
            "outcome": "succeeded",
            "usage": (
                Usage("input_token", 120),
                Usage("output_token", 45),
            ),
            "page_number": None,
        }
    ]


def test_groq_story_is_validated_and_records_token_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Recorder:
        def record_call(self, **values: Any) -> None:
            calls.append(values)

    def generate(
        _provider: object,
        _request: object,
    ) -> StoryProviderResponse:
        return StoryProviderResponse(
            payload={
                "title": "Camille's Fast Evening",
                "pages": [f"Page {number}." for number in range(1, 11)],
            },
            provider="groq",
            model="openai/gpt-oss-20b",
            usage=(
                Usage("input_token", 130),
                Usage("output_token", 50),
            ),
        )

    class TestGroqProvider:
        def __init__(self, **_: object) -> None:
            pass

        def generate(self, request: object) -> StoryProviderResponse:
            return generate(self, request)

    monkeypatch.setattr(settings, "story_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(
        story_generation,
        "GroqStoryProvider",
        TestGroqProvider,
        raising=False,
    )

    story = generate_story(
        child_name="Camille",
        age=6,
        interests="stars",
        event_text="Camille helped make dinner.",
        language="en",
        recorder=Recorder(),
    )

    assert story.title == "Camille's Fast Evening"
    assert len(story.pages) == 10
    assert calls == [
        {
            "stage": "story_text",
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
            "attempt": 1,
            "outcome": "succeeded",
            "usage": (
                Usage("input_token", 130),
                Usage("output_token", 50),
            ),
            "page_number": None,
        }
    ]


def test_real_provider_fails_immediately_after_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []

    class Recorder:
        def record_call(self, **values: Any) -> None:
            recorded.append(values)

    def generate(
        _provider: ClaudeStoryProvider,
        _request: object,
    ) -> StoryProviderResponse:
        return StoryProviderResponse(
            payload={"title": "Too short", "pages": ["Only one page."]},
            provider="claude",
            model="claude-test",
            usage=(Usage("input_token", 100), Usage("output_token", 20)),
        )

    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    monkeypatch.setattr(ClaudeStoryProvider, "generate", generate)

    with pytest.raises(RuntimeError) as captured:
        generate_story(
            child_name="Camille",
            age=6,
            interests="stars",
            event_text="Camille helped make dinner.",
            language="en",
            recorder=Recorder(),
        )

    assert str(captured.value).startswith(
        "Story generation failed after retry: "
    )
    assert len(recorded) == 1
    assert recorded[0]["outcome"] == "invalid_response"


def test_real_provider_retries_once_after_request_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []
    attempt = 0
    monkeypatch.setattr("time.sleep", lambda _: None)

    class Recorder:
        def record_call(self, **values: Any) -> None:
            recorded.append(values)

    def generate(
        _provider: ClaudeStoryProvider,
        _request: object,
    ) -> StoryProviderResponse:
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise provider_module.StoryProviderRequestError(
                provider="claude",
                model="claude-test",
                usage=None,
            )
        return StoryProviderResponse(
            payload={
                "title": "Recovered Story",
                "pages": [f"Page {number}." for number in range(1, 11)],
            },
            provider="claude",
            model="claude-test",
            usage=(Usage("input_token", 100), Usage("output_token", 40)),
        )

    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    monkeypatch.setattr(ClaudeStoryProvider, "generate", generate)

    story = generate_story(
        child_name="Camille",
        age=6,
        interests="stars",
        event_text="Camille helped make dinner.",
        language="en",
        recorder=Recorder(),
    )

    assert story.title == "Recovered Story"
    assert [(call["attempt"], call["outcome"]) for call in recorded] == [
        (1, "provider_failure"),
        (2, "succeeded"),
    ]
    assert recorded[0]["usage"] is None


def test_ollama_fails_immediately_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []
    malformed = MagicMock()
    malformed.json.return_value = {"message": {"content": "not json"}}

    class Recorder:
        def record_call(self, **values: Any) -> None:
            recorded.append(values)

    monkeypatch.setattr(settings, "story_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "local-test")
    monkeypatch.setattr(
        provider_module.httpx,
        "post",
        MagicMock(return_value=malformed),
    )

    with pytest.raises(RuntimeError):
        generate_story(
            child_name="Camille",
            age=6,
            interests="stars",
            event_text="Camille helped make dinner.",
            language="en",
            recorder=Recorder(),
        )

    assert len(recorded) == 1
    assert recorded[0]["outcome"] == "invalid_response"


def test_real_provider_validation_error_propagates_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_payload = {
        "title": "PRIVATE CHILD EVENT",
        "pages": "PRIVATE INVALID PAGES",
    }

    def generate(
        _provider: ClaudeStoryProvider,
        _request: object,
    ) -> StoryProviderResponse:
        return StoryProviderResponse(
            payload=private_payload,
            provider="claude",
            model="claude-test",
            usage=(Usage("input_token", 100), Usage("output_token", 20)),
        )

    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    monkeypatch.setattr(ClaudeStoryProvider, "generate", generate)

    with pytest.raises(RuntimeError) as captured:
        generate_story(
            child_name="Camille",
            age=6,
            interests="stars",
            event_text="Camille helped make dinner.",
            language="en",
        )

    assert str(captured.value) == (
        "Story generation failed after retry: ValidationError."
    )
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "PRIVATE CHILD EVENT" not in rendered_error
    assert "PRIVATE INVALID PAGES" not in rendered_error
