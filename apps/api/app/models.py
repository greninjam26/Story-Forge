import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class StoryStatus(str, Enum):
    GENERATING = "generating"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    GENERATION_FAILED = "generation_failed"


class GenerationStage(str, Enum):
    STORY_TEXT = "story_text"
    MODERATION = "moderation"
    ILLUSTRATIONS = "illustrations"
    NARRATION = "narration"
    COMPLETE = "complete"


class GenerationRunStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class PendingAssetDeletion(Base):
    __tablename__ = "pending_asset_deletions"
    __table_args__ = (
        CheckConstraint(
            "attempts >= 0",
            name="ck_pending_asset_deletions_nonnegative_attempts",
        ),
        Index(
            "ix_pending_asset_deletions_due",
            "terminal_at",
            "next_attempt_at",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    reference: Mapped[str] = mapped_column(String(2048), nullable=False)
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StripeEvent(Base):
    """Every webhook event we acted on (or deliberately skipped).

    Three jobs, one table:
      - dedupe/replay: the Stripe event id is the primary key, so a redelivered
        or captured-and-replayed signed event hits the PK and is acked without
        re-running its side effects;
      - ordering: Stripe does not guarantee delivery order, so handlers compare
        against previously recorded events (a subscription.deleted that arrived
        first must beat a checkout.session.completed that arrives second);
      - audit: "which event, at what time, changed this parent's access" has a
        row to point at when a charge is disputed.
    """

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Stripe evt_…
    type: Mapped[str] = mapped_column(String)
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Stripe's own creation timestamp — the ordering authority.
    stripe_created: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )


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
    hashed_password: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    free_stories_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    is_subscribed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String, nullable=True
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
        CheckConstraint(
            "age BETWEEN 1 AND 12",
            name="ck_children_age_range",
        ),
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
    reference_photo_ref: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
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
        CheckConstraint(
            "generation_attempts >= 0",
            name="ck_stories_nonnegative_generation_attempts",
        ),
        CheckConstraint(
            "(generation_claim_token IS NULL AND "
            "generation_claimed_at IS NULL) OR "
            "(generation_claim_token IS NOT NULL AND "
            "generation_claimed_at IS NOT NULL)",
            name="ck_stories_generation_claim_pair",
        ),
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
    safety_reason: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        default=Decimal("0"),
        server_default="0",
        nullable=False,
    )
    generation_claim_token: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    generation_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    generation_stage: Mapped[GenerationStage] = mapped_column(
        SqlEnum(
            GenerationStage,
            name="generation_stage",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda stages: [stage.value for stage in stages],
        ),
        default=GenerationStage.STORY_TEXT,
        server_default=GenerationStage.STORY_TEXT.value,
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
    generation_runs: Mapped[list["GenerationRun"]] = relationship(
        back_populates="story",
        passive_deletes=True,
        order_by="GenerationRun.started_at",
    )
    moderation_record: Mapped["ModerationRecord | None"] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
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


class StoryIdempotencyKey(Base):
    __tablename__ = "story_idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "parent_id",
            "key",
            name="uq_story_idempotency_keys_parent_key",
        ),
        Index(
            "ix_story_idempotency_keys_parent_created_at",
            "parent_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parents.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )


class ModerationRecord(Base):
    __tablename__ = "moderation_records"
    __table_args__ = (
        CheckConstraint(
            "flagged_item_kind IN ('title', 'page')",
            name="ck_moderation_records_item_kind",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'false_positive')",
            name="ck_moderation_records_review_status",
        ),
        Index(
            "ix_moderation_records_review_status_created_at",
            "review_status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    flagged_item_kind: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    flagged_page_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    flagged_text: Mapped[str] = mapped_column(Text, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    category_scores: Mapped[dict[str, float]] = mapped_column(
        JSON, nullable=False
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    story: Mapped[Story] = relationship(back_populates="moderation_record")


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        CheckConstraint(
            "known_cost_usd >= 0",
            name="ck_generation_runs_nonnegative_known_cost",
        ),
        Index(
            "ix_generation_runs_status_completed_at",
            "status",
            "completed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    story_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stories.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[GenerationRunStatus] = mapped_column(
        SqlEnum(
            GenerationRunStatus,
            name="generation_run_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda statuses: [
                status.value for status in statuses
            ],
        ),
        default=GenerationRunStatus.IN_PROGRESS,
        server_default=GenerationRunStatus.IN_PROGRESS.value,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    known_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 12),
        default=Decimal("0"),
        server_default="0",
        nullable=False,
    )
    cost_complete: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    ceiling_exceeded: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )

    story: Mapped[Story | None] = relationship(
        back_populates="generation_runs"
    )
    cost_events: Mapped[list["GenerationCostEvent"]] = relationship(
        back_populates="generation_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GenerationCostEvent.created_at",
    )


class GenerationCostEvent(Base):
    __tablename__ = "generation_cost_events"
    __table_args__ = (
        CheckConstraint(
            "attempt >= 1",
            name="ck_generation_cost_events_positive_attempt",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_generation_cost_events_positive_page_number",
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_generation_cost_events_nonnegative_quantity",
        ),
        CheckConstraint(
            "unit_rate_usd IS NULL OR unit_rate_usd >= 0",
            name="ck_generation_cost_events_nonnegative_unit_rate",
        ),
        CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0",
            name="ck_generation_cost_events_nonnegative_cost",
        ),
        CheckConstraint(
            "(cost_known AND quantity IS NOT NULL "
            "AND unit_rate_usd IS NOT NULL AND cost_usd IS NOT NULL) "
            "OR (NOT cost_known AND cost_usd IS NULL)",
            name="ck_generation_cost_events_known_cost_details",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    generation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, index=True, nullable=False
    )
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    usage_unit: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_rate_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12), nullable=True
    )
    cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12), nullable=True
    )
    cost_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    generation_run: Mapped[GenerationRun] = relationship(
        back_populates="cost_events"
    )
