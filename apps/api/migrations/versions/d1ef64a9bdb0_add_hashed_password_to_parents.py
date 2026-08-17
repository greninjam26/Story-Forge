"""add hashed_password to parents

Revision ID: d1ef64a9bdb0
Revises: e8b036570f2a
Create Date: 2026-08-17 13:10:35.629401

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1ef64a9bdb0'
down_revision: Union[str, Sequence[str], None] = 'e8b036570f2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply this migration."""
    op.add_column(
        "parents",
        sa.Column("hashed_password", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    """Revert this migration."""
    op.drop_column("parents", "hashed_password")
