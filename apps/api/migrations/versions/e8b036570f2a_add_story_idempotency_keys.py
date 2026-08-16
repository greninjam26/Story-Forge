"""Add request-level idempotency keys for story creation.

Revision ID: e8b036570f2a
Revises: e8f3a1c7d902
Create Date: 2026-08-16 10:46:27.494665

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e8b036570f2a"
down_revision: Union[str, Sequence[str], None] = "e8f3a1c7d902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the parent-scoped story idempotency key registry."""
    op.create_table(
        "story_idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["parents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_id",
            "key",
            name="uq_story_idempotency_keys_parent_key",
        ),
    )
    op.create_index(
        "ix_story_idempotency_keys_parent_created_at",
        "story_idempotency_keys",
        ["parent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_story_idempotency_keys_story_id",
        "story_idempotency_keys",
        ["story_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the story idempotency key registry."""
    op.drop_index(
        "ix_story_idempotency_keys_story_id",
        table_name="story_idempotency_keys",
    )
    op.drop_index(
        "ix_story_idempotency_keys_parent_created_at",
        table_name="story_idempotency_keys",
    )
    op.drop_table("story_idempotency_keys")
