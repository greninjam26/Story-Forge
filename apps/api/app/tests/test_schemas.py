from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app import schemas
from app.models import (
    Child,
    GenerationStage,
    Parent,
    Story,
    StoryPage,
    StoryStatus,
)
from app.schemas import (
    ChildCreate,
    ChildOut,
    ChildUpdate,
    ParentOut,
    StoryApprove,
    StoryCreate,
    StoryGenerationResult,
    StoryOut,
)
from app.services import storage


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


def test_story_approve_requires_a_boolean_decision() -> None:
    approve_request = StoryApprove(approve=True)
    reject_request = StoryApprove(approve=False)

    assert approve_request.approve is True
    assert reject_request.approve is False

    with pytest.raises(ValidationError):
        StoryApprove.model_validate({})

    with pytest.raises(ValidationError):
        StoryApprove.model_validate({"approve": "true"})


def test_story_update_accepts_partial_title_and_page_changes() -> None:
    title_update = schemas.StoryUpdate(title="  A Better Title  ")
    page_update = schemas.StoryUpdate(
        pages=[{"page_number": 3, "text": "  Updated page text.  "}]
    )

    assert title_update.model_dump(exclude_unset=True) == {
        "title": "A Better Title"
    }
    assert page_update.pages is not None
    assert page_update.pages[0].page_number == 3
    assert page_update.pages[0].text == "Updated page text."


@pytest.mark.parametrize(
    "update_data",
    [
        {},
        {"title": None},
        {"title": "   "},
        {"pages": None},
        {"pages": []},
        {"pages": [{"page_number": 0, "text": "Text."}]},
        {"pages": [{"page_number": 1, "text": "   "}]},
        {
            "pages": [
                {"page_number": 1, "text": "First."},
                {"page_number": 1, "text": "Duplicate."},
            ]
        },
        {"title": "Title", "unexpected": "value"},
        {
            "pages": [
                {
                    "page_number": 1,
                    "text": "Text.",
                    "unexpected": "value",
                }
            ]
        },
    ],
)
def test_story_update_rejects_invalid_values(
    update_data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schemas.StoryUpdate.model_validate(update_data)


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
        generation_stage=GenerationStage.COMPLETE,
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
    assert response.generation_stage is GenerationStage.COMPLETE
    assert len(response.pages) == 1
    assert response.pages[0].id == story.pages[0].id
    assert response.pages[0].page_number == 1
    assert response.pages[0].text == story.pages[0].text
    assert response.pages[0].image_url is None
    assert response.pages[0].audio_url is None


def test_story_out_resolves_r2_page_references_without_mutating_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_reference = (
        "r2://illustrations/"
        "0123456789abcdef0123456789abcdef.webp"
    )
    audio_reference = (
        "r2://narration/"
        "abcdef0123456789abcdef0123456789.mp3"
    )
    story = Story(
        id=uuid4(),
        child_id=uuid4(),
        event_text="Camille planted a seed.",
        title="Camille's Little Garden",
        language="en",
        status=StoryStatus.PENDING_REVIEW,
        failure_reason=None,
        cost_usd=Decimal("0"),
        created_at=datetime.now(timezone.utc),
        approved_at=None,
        generation_stage=GenerationStage.COMPLETE,
        pages=[
            StoryPage(
                id=uuid4(),
                page_number=1,
                text="Camille tucked a seed into the soil.",
                image_url=image_reference,
                audio_url=audio_reference,
            )
        ],
    )
    signed_urls = {
        image_reference: "https://signed.example/image.webp",
        audio_reference: "https://signed.example/audio.mp3",
    }
    monkeypatch.setattr(
        storage,
        "resolve_url",
        signed_urls.__getitem__,
        raising=False,
    )

    response = StoryOut.model_validate(story)

    assert response.pages[0].image_url == signed_urls[image_reference]
    assert response.pages[0].audio_url == signed_urls[audio_reference]
    assert story.pages[0].image_url == image_reference
    assert story.pages[0].audio_url == audio_reference
