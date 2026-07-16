from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, create_db_engine
from app.models import Parent


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
