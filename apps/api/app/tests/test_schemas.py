from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import Child, Parent, Story, StoryPage, StoryStatus
from app.schemas import (
    ChildCreate,
    ChildOut,
    ChildUpdate,
    ParentCreate,
    ParentOut,
    StoryCreate,
    StoryGenerationResult,
    StoryOut,
)


def test_parent_create_uses_english_locale_by_default() -> None:
    parent = ParentCreate(email="parent@example.com")

    assert str(parent.email) == "parent@example.com"
    assert parent.locale == "en"


def test_parent_create_accepts_french_locale() -> None:
    parent = ParentCreate(email="parent@example.com", locale="fr")

    assert parent.locale == "fr"


@pytest.mark.parametrize(
    ("email", "locale"),
    [("not-an-email", "en"), ("parent@example.com", "es")],
)
def test_parent_create_rejects_invalid_values(email: str, locale: str) -> None:
    with pytest.raises(ValidationError):
        ParentCreate.model_validate({"email": email, "locale": locale})


def test_parent_out_reads_parent_model_attributes() -> None:
    parent = Parent(
        id=uuid4(),
        email="parent@example.com",
        locale="fr",
        created_at=datetime.now(timezone.utc),
    )

    response = ParentOut.model_validate(parent)

    assert response.id == parent.id
    assert str(response.email) == parent.email
    assert response.locale == parent.locale
    assert response.created_at == parent.created_at


def test_child_create_uses_defaults_and_trims_text() -> None:
    child = ChildCreate(name="  Camille  ", age=7)

    assert child.name == "Camille"
    assert child.interests == ""
    assert child.language == "en"


def test_child_create_accepts_interests_and_french_language() -> None:
    child = ChildCreate(
        name="Camille",
        age=7,
        interests="  les etoiles et les dinosaures  ",
        language="fr",
    )

    assert child.interests == "les etoiles et les dinosaures"
    assert child.language == "fr"


@pytest.mark.parametrize(
    "child_data",
    [
        {"name": "", "age": 7},
        {"name": "   ", "age": 7},
        {"name": "Camille", "age": 0},
        {"name": "Camille", "age": 13},
        {"name": "Camille", "age": 7, "interests": "a" * 501},
        {"name": "Camille", "age": 7, "language": "es"},
    ],
)
def test_child_create_rejects_invalid_values(
    child_data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ChildCreate.model_validate(child_data)


def test_child_update_accepts_partial_changes() -> None:
    update = ChildUpdate(name="  Camille-Marie  ")

    assert update.model_dump(exclude_unset=True) == {"name": "Camille-Marie"}


@pytest.mark.parametrize("field_name", ["name", "age", "interests", "language"])
def test_child_update_rejects_explicit_null(field_name: str) -> None:
    with pytest.raises(ValidationError):
        ChildUpdate.model_validate({field_name: None})


def test_child_out_reads_child_model_attributes() -> None:
    child = Child(
        id=uuid4(),
        parent_id=uuid4(),
        name="Camille",
        age=7,
        interests="stars",
        language="fr",
        created_at=datetime.now(timezone.utc),
    )

    response = ChildOut.model_validate(child)

    assert response.id == child.id
    assert response.parent_id == child.parent_id
    assert response.name == child.name
    assert response.age == child.age
    assert response.interests == child.interests
    assert response.language == child.language
    assert response.created_at == child.created_at


def test_story_create_trims_event_text() -> None:
    child_id = uuid4()

    request = StoryCreate(
        child_id=child_id,
        event_text="  Camille helped make dinner.  ",
    )

    assert request.child_id == child_id
    assert request.event_text == "Camille helped make dinner."


@pytest.mark.parametrize(
    "story_data",
    [
        {"child_id": "not-a-uuid", "event_text": "A good day."},
        {"child_id": str(uuid4()), "event_text": ""},
        {"child_id": str(uuid4()), "event_text": "   "},
        {"child_id": str(uuid4()), "event_text": "a" * 2001},
    ],
)
def test_story_create_rejects_invalid_values(
    story_data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        StoryCreate.model_validate(story_data)


def test_story_generation_result_trims_valid_output() -> None:
    result = StoryGenerationResult(
        title="  Camille and the Evening Star  ",
        pages=["  Camille looked up at the sky.  ", "The star winked."],
    )

    assert result.title == "Camille and the Evening Star"
    assert result.pages == [
        "Camille looked up at the sky.",
        "The star winked.",
    ]


@pytest.mark.parametrize(
    "generated_data",
    [
        {"title": "", "pages": ["A page."]},
        {"title": "A title", "pages": []},
        {"title": "A title", "pages": ["   "]},
        {"title": "A title", "pages": ["A page."] * 13},
        {"title": "A title", "pages": ["A page."], "summary": "Extra"},
    ],
)
def test_story_generation_result_rejects_invalid_output(
    generated_data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        StoryGenerationResult.model_validate(generated_data)


def test_story_out_reads_story_and_page_model_attributes() -> None:
    story = Story(
        id=uuid4(),
        child_id=uuid4(),
        event_text="Camille planted a seed.",
        title="Camille's Little Garden",
        language="en",
        status=StoryStatus.PENDING_REVIEW,
        failure_reason=None,
        cost_usd=Decimal("0.0000"),
        created_at=datetime.now(timezone.utc),
        approved_at=None,
    )
    story.pages.append(
        StoryPage(
            id=uuid4(),
            story_id=story.id,
            page_number=1,
            text="Camille tucked a seed into the soil.",
            image_url=None,
            audio_url=None,
        )
    )

    response = StoryOut.model_validate(story)

    assert response.id == story.id
    assert response.child_id == story.child_id
    assert response.title == story.title
    assert response.language == "en"
    assert response.status is StoryStatus.PENDING_REVIEW
    assert response.failure_reason is None
    assert response.cost_usd == Decimal("0.0000")
    assert response.created_at == story.created_at
    assert response.approved_at is None
    assert len(response.pages) == 1
    assert response.pages[0].id == story.pages[0].id
    assert response.pages[0].page_number == 1
    assert response.pages[0].text == story.pages[0].text
    assert response.pages[0].image_url is None
    assert response.pages[0].audio_url is None
