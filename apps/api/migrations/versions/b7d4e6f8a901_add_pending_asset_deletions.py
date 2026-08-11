"""Add pending asset deletions.

Revision ID: b7d4e6f8a901
Revises: f4c2a8d91b37
Create Date: 2026-08-11 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7d4e6f8a901"
down_revision: Union[str, Sequence[str], None] = "f4c2a8d91b37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the durable private-asset deletion queue."""
    op.create_table(
        "pending_asset_deletions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=2048), nullable=False),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "terminal_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_pending_asset_deletions_nonnegative_attempts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_asset_deletions_due",
        "pending_asset_deletions",
        ["terminal_at", "next_attempt_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the private-asset deletion queue."""
    op.drop_index(
        "ix_pending_asset_deletions_due",
        table_name="pending_asset_deletions",
    )
    op.drop_table("pending_asset_deletions")
