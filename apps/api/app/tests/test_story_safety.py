import pytest

from app.services import story_safety
from app.services.story_safety import check_text


def test_check_text_allows_safe_content() -> None:
    result = check_text(
        "Camille helped a friend build a paper dragon."
    )

    assert result.is_safe is True
    assert result.reason is None


@pytest.mark.parametrize(
    "text",
    [
        "The story described violence.",
        "A weapon appeared in the story.",
        "There was blood on the floor.",
        "The villain threatened to kill someone.",
        "The event mentioned suicide.",
        "Someone offered a drug.",
        "The character found alcohol.",
        "Camille a trouvé une ARME.",
        "Il y avait du sang.",
        "Le personnage voulait tuer quelqu'un.",
        "Une drogue est apparue.",
        "Le personnage a trouvé de l'alcool.",
    ],
)
def test_check_text_flags_english_and_french_blocked_terms(
    text: str,
) -> None:
    result = check_text(text)

    assert result.is_safe is False
    assert result.reason == "safety_content_blocked"


@pytest.mark.parametrize(
    "text",
    [
        "Camille practiced a new skill.",
        "Une alarme a sonné dans la maison.",
    ],
)
def test_check_text_does_not_match_terms_inside_other_words(
    text: str,
) -> None:
    result = check_text(text)

    assert result.is_safe is True
    assert result.reason is None


def test_check_story_allows_safe_pages() -> None:
    result = story_safety.check_story(
        [
            "Camille helped prepare dinner.",
            "Everyone felt proud and ready for sleep.",
        ]
    )

    assert result.is_safe is True
    assert result.reason is None


def test_check_story_identifies_the_first_blocked_page() -> None:
    result = story_safety.check_story(
        [
            "Camille followed a friendly guide.",
            "The guide found a weapon.",
            "They later discovered blood on the path.",
        ]
    )

    assert result.is_safe is False
    assert result.reason == "safety_generated_page_2_blocked"


def test_check_story_rejects_a_plain_string() -> None:
    with pytest.raises(TypeError):
        story_safety.check_story("weapon")


def test_check_generated_story_flags_a_blocked_title() -> None:
    result = story_safety.check_generated_story(
        title="Camille and the Hidden Weapon",
        page_texts=["Camille followed a friendly guide home."],
    )

    assert result.is_safe is False
    assert result.reason == "safety_generated_title_blocked"


def test_check_generated_story_flags_the_first_blocked_page() -> None:
    result = story_safety.check_generated_story(
        title="Camille and the Gentle Star",
        page_texts=[
            "Camille followed a friendly guide.",
            "The guide discovered blood on the path.",
        ],
    )

    assert result.is_safe is False
    assert result.reason == "safety_generated_page_2_blocked"


def test_check_generated_story_allows_safe_content() -> None:
    result = story_safety.check_generated_story(
        title="Camille and the Gentle Star",
        page_texts=[
            "Camille followed a friendly guide.",
            "They returned home safely.",
        ],
    )

    assert result.is_safe is True
    assert result.reason is None


def test_check_generated_story_checks_title_before_pages() -> None:
    result = story_safety.check_generated_story(
        title="Camille and the Hidden Weapon",
        page_texts=["The guide discovered blood on the path."],
    )

    assert result.is_safe is False
    assert result.reason == "safety_generated_title_blocked"
