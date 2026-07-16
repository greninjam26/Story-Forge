import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

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
