"""Add moderation audit storage.

Revision ID: c1d5e7a9b302
Revises: b7d4e6f8a901
Create Date: 2026-08-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c1d5e7a9b302"
down_revision: Union[str, Sequence[str], None] = "b7d4e6f8a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add structured safety reasons and private moderation evidence."""
    with op.batch_alter_table("stories", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("safety_reason", sa.String(length=50), nullable=True)
        )

    op.execute(sa.text(
        "UPDATE stories SET safety_reason = 'unsafe_content' "
        "WHERE failure_reason IN ("
        "'safety_content_blocked', "
        "'safety_generated_title_blocked'"
        ") OR failure_reason LIKE "
        "'safety\\_generated\\_page\\_%\\_blocked' ESCAPE '\\'"
    ))

    op.create_table(
        "moderation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column(
            "provider_request_id",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column(
            "flagged_item_kind",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column("flagged_page_number", sa.Integer(), nullable=True),
        sa.Column("flagged_text", sa.Text(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("category_scores", sa.JSON(), nullable=False),
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "flagged_item_kind IN ('title', 'page')",
            name="ck_moderation_records_item_kind",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'false_positive')",
            name="ck_moderation_records_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_moderation_records_story_id",
        "moderation_records",
        ["story_id"],
        unique=True,
    )
    op.create_index(
        "ix_moderation_records_review_status_created_at",
        "moderation_records",
        ["review_status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove private moderation evidence and structured safety reasons."""
    op.drop_index(
        "ix_moderation_records_review_status_created_at",
        table_name="moderation_records",
    )
    op.drop_index(
        "ix_moderation_records_story_id",
        table_name="moderation_records",
    )
    op.drop_table("moderation_records")

    # A SQLite batch rebuild drops the old stories table and fires its
    # ON DELETE CASCADE relationships. Modern supported SQLite versions can
    # drop this standalone column directly without deleting owned rows.
    op.drop_column("stories", "safety_reason")
