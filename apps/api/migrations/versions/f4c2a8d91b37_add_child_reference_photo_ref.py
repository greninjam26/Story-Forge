"""Add a private reference-photo storage field to children.

Revision ID: f4c2a8d91b37
Revises: a62f4d9e8b13
Create Date: 2026-08-04 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4c2a8d91b37"
down_revision: Union[str, Sequence[str], None] = "a62f4d9e8b13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow each child to reference one private source photo."""
    op.add_column(
        "children",
        sa.Column(
            "reference_photo_ref",
            sa.String(length=2048),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove child reference-photo storage references."""
    op.drop_column("children", "reference_photo_ref")
