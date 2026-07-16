import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Parent(Base):
    __tablename__ = "parents"
    __table_args__ = (
        CheckConstraint("locale IN ('en', 'fr')", name="ck_parents_locale"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    locale: Mapped[str] = mapped_column(
        String(2), default="en", server_default="en", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    children: Mapped[list["Child"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Child(Base):
    __tablename__ = "children"
    __table_args__ = (
        CheckConstraint("age >= 1", name="ck_children_positive_age"),
        CheckConstraint("language IN ('en', 'fr')",
                        name="ck_children_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    interests: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )
    language: Mapped[str] = mapped_column(
        String(2), default="en", server_default="en", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    parent: Mapped[Parent] = relationship(back_populates="children")
