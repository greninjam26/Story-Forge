from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, create_db_engine, get_db
from app.main import app


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_db_engine("sqlite:///:memory:")
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)

    try:
        yield testing_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
