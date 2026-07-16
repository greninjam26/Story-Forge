"""Create core tables.

Revision ID: 0f7d9a25c2bb
Revises:
Create Date: 2026-07-16 10:25:30.788317

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0f7d9a25c2bb"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the core Story Forge tables."""
    op.create_table(
        "parents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "locale", sa.String(length=2), server_default="en", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "locale IN ('en', 'fr')", name="ck_parents_locale"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("parents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_parents_email"), ["email"], unique=True
        )

    op.create_table(
        "children",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("interests", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "language", sa.String(length=2), server_default="en", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "language IN ('en', 'fr')", name="ck_children_language"
        ),
        sa.CheckConstraint("age >= 1", name="ck_children_positive_age"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["parents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("children", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_children_parent_id"), ["parent_id"], unique=False
        )

    op.create_table(
        "stories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("child_id", sa.Uuid(), nullable=False),
        sa.Column("event_text", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=200), server_default="", nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "generating",
                "pending_review",
                "approved",
                "rejected",
                "generation_failed",
                name="story_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="generating",
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=10, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "language IN ('en', 'fr')", name="ck_stories_language"
        ),
        sa.CheckConstraint(
            "cost_usd >= 0", name="ck_stories_nonnegative_cost"
        ),
        sa.ForeignKeyConstraint(
            ["child_id"], ["children.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("stories", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_stories_child_id"), ["child_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_stories_status"), ["status"], unique=False
        )

    op.create_table(
        "story_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("audio_url", sa.String(length=2048), nullable=True),
        sa.CheckConstraint(
            "page_number >= 1", name="ck_story_pages_positive_number"
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "story_id",
            "page_number",
            name="uq_story_pages_story_page_number",
        ),
    )
    with op.batch_alter_table("story_pages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_story_pages_story_id"), ["story_id"], unique=False
        )


def downgrade() -> None:
    """Remove the core Story Forge tables."""
    with op.batch_alter_table("story_pages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_story_pages_story_id"))
    op.drop_table("story_pages")

    with op.batch_alter_table("stories", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_stories_status"))
        batch_op.drop_index(batch_op.f("ix_stories_child_id"))
    op.drop_table("stories")

    with op.batch_alter_table("children", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_children_parent_id"))
    op.drop_table("children")

    with op.batch_alter_table("parents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_parents_email"))
    op.drop_table("parents")
