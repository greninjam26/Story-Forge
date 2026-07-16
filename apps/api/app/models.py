import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class StoryStatus(str, Enum):
    GENERATING = "generating"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    GENERATION_FAILED = "generation_failed"


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
    stories: Mapped[list["Story"]] = relationship(
        back_populates="child",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (
        CheckConstraint("language IN ('en', 'fr')",
                        name="ck_stories_language"),
        CheckConstraint("cost_usd >= 0", name="ck_stories_nonnegative_cost"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("children.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(
        String(200), default="", server_default="", nullable=False
    )
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[StoryStatus] = mapped_column(
        SqlEnum(
            StoryStatus,
            name="story_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda statuses: [
                status.value for status in statuses],
        ),
        default=StoryStatus.GENERATING,
        server_default=StoryStatus.GENERATING.value,
        index=True,
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        default=Decimal("0"),
        server_default="0",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    child: Mapped[Child] = relationship(back_populates="stories")
    pages: Mapped[list["StoryPage"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StoryPage.page_number",
    )


class StoryPage(Base):
    __tablename__ = "story_pages"
    __table_args__ = (
        CheckConstraint("page_number >= 1",
                        name="ck_story_pages_positive_number"),
        UniqueConstraint(
            "story_id", "page_number", name="uq_story_pages_story_page_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    story: Mapped[Story] = relationship(back_populates="pages")
