from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, create_db_engine
from app.models import Child, Parent


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_parent_uses_defaults_and_persists(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_parent = db_session.scalar(
        select(Parent).where(Parent.email == "parent@example.com")
    )

    assert saved_parent is not None
    assert isinstance(saved_parent.id, UUID)
    assert saved_parent.locale == "en"
    assert saved_parent.created_at is not None


def test_parent_rejects_unsupported_locale(db_session: Session) -> None:
    db_session.add(Parent(email="parent@example.com", locale="es"))

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_parent_email_must_be_unique(db_session: Session) -> None:
    db_session.add(Parent(email="parent@example.com"))
    db_session.commit()
    db_session.add(Parent(email="parent@example.com"))

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_child_uses_defaults_and_belongs_to_parent(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_child = db_session.scalar(select(Child).where(Child.name == "Camille"))

    assert saved_child is not None
    assert isinstance(saved_child.id, UUID)
    assert saved_child.parent.email == "parent@example.com"
    assert saved_child.language == "en"
    assert saved_child.interests == ""
    assert saved_child.created_at is not None


def test_child_accepts_french_story_language(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    parent.children.append(Child(name="Camille", age=7, language="fr"))
    db_session.add(parent)
    db_session.commit()

    assert parent.children[0].language == "fr"


@pytest.mark.parametrize(("age", "language"), [(0, "en"), (7, "es")])
def test_child_rejects_invalid_values(
    db_session: Session, age: int, language: str
) -> None:
    parent = Parent(email="parent@example.com")
    parent.children.append(Child(name="Camille", age=age, language=language))
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_deleting_parent_deletes_children(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    parent.children.append(Child(name="Camille", age=7))
    db_session.add(parent)
    db_session.commit()

    db_session.delete(parent)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Child)) == 0
