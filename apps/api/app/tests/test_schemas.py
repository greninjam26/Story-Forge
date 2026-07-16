from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import Child, Parent
from app.schemas import ChildCreate, ChildOut, ChildUpdate, ParentCreate, ParentOut


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
