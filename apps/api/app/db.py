from collections.abc import Generator
from sqlite3 import Connection as SQLiteConnection
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(
    dbapi_connection: Any, _connection_record: Any
) -> None:
    if isinstance(dbapi_connection, SQLiteConnection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def create_db_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            return create_engine(
                database_url,
                connect_args=connect_args,
                poolclass=StaticPool,
            )
        return create_engine(database_url, connect_args=connect_args)

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


engine = create_db_engine(settings.database_url)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
