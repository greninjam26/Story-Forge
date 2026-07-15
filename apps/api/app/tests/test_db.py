from sqlalchemy import text

from app.db import Base, create_db_engine


def test_sqlite_database_setup() -> None:
    engine = create_db_engine("sqlite:///:memory:")

    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
        assert Base.metadata is not None
    finally:
        engine.dispose()


def test_postgres_database_uses_psycopg_driver() -> None:
    engine = create_db_engine(
        "postgresql+psycopg://user:password@localhost:5432/storyforge"
    )

    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()
