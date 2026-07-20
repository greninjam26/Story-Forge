from typing import cast

import pytest

from app.config import settings
from app.schemas import StoryGenerationResult, StoryLanguage
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
