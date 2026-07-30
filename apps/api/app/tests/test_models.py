from collections.abc import Generator
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, create_db_engine
from app.models import Child, Parent, Story, StoryPage, StoryStatus


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


@pytest.mark.parametrize(
    ("age", "language"),
    [(0, "en"), (13, "en"), (7, "es")],
)
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


def test_story_uses_defaults_and_belongs_to_child(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7, language="fr")
    story = Story(
        event_text="Camille helped make dinner.",
        language=child.language,
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_story = db_session.scalar(
        select(Story).where(Story.event_text == "Camille helped make dinner.")
    )

    assert saved_story is not None
    assert isinstance(saved_story.id, UUID)
    assert saved_story.child.name == "Camille"
    assert saved_story.language == "fr"
    assert saved_story.status is StoryStatus.GENERATING
    assert saved_story.title == ""
    assert saved_story.failure_reason is None
    assert saved_story.cost_usd == Decimal("0.0000")
    assert saved_story.created_at is not None
    assert saved_story.approved_at is None


def test_story_status_can_move_to_pending_review(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille shared a toy.", language="en")
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    story.title = "The Shared Star"
    story.status = StoryStatus.PENDING_REVIEW
    db_session.commit()
    db_session.refresh(story)

    assert story.title == "The Shared Star"
    assert story.status is StoryStatus.PENDING_REVIEW


@pytest.mark.parametrize(
    ("language", "cost_usd"),
    [("es", Decimal("0")), ("en", Decimal("-0.01"))],
)
def test_story_rejects_invalid_values(
    db_session: Session, language: str, cost_usd: Decimal
) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    child.stories.append(
        Story(
            event_text="Camille went to the park.",
            language=language,
            cost_usd=cost_usd,
        )
    )
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_deleting_child_deletes_stories(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    child.stories.append(
        Story(event_text="Camille learned to whistle.", language="en")
    )
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    db_session.delete(child)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Story)) == 0


def test_story_pages_are_ordered_and_allow_pending_assets(
    db_session: Session,
) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille planted a seed.", language="en")
    story.pages.extend(
        [
            StoryPage(page_number=2, text="A green shoot appeared."),
            StoryPage(page_number=1, text="Camille planted a tiny seed."),
        ]
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()
    db_session.expire_all()

    saved_story = db_session.scalar(
        select(Story).where(Story.event_text == "Camille planted a seed.")
    )

    assert saved_story is not None
    assert [page.page_number for page in saved_story.pages] == [1, 2]
    assert saved_story.pages[0].story is saved_story
    assert saved_story.pages[0].image_url is None
    assert saved_story.pages[0].audio_url is None


def test_story_page_number_must_be_positive(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille drew a picture.", language="en")
    story.pages.append(StoryPage(page_number=0, text="A bright picture."))
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_story_page_numbers_are_unique_within_story(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille built a tower.", language="en")
    story.pages.extend(
        [
            StoryPage(page_number=1, text="The first block."),
            StoryPage(page_number=1, text="Another first page."),
        ]
    )
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_deleting_story_deletes_pages(db_session: Session) -> None:
    parent = Parent(email="parent@example.com")
    child = Child(name="Camille", age=7)
    story = Story(event_text="Camille found a shell.", language="en")
    story.pages.append(StoryPage(page_number=1, text="A shell by the water."))
    child.stories.append(story)
    parent.children.append(child)
    db_session.add(parent)
    db_session.commit()

    db_session.delete(story)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(StoryPage)) == 0
