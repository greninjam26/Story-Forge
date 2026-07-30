"""Enforce the supported child age range.

Revision ID: d3a7c4b91f20
Revises: 0f7d9a25c2bb
Create Date: 2026-07-29 20:55:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3a7c4b91f20"
down_revision: Union[str, Sequence[str], None] = "0f7d9a25c2bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_age_constraint(
    *,
    old_name: str,
    new_name: str,
    condition: str,
) -> None:
    connection = op.get_bind()

    def replace_constraint() -> None:
        with op.batch_alter_table("children", schema=None) as batch_op:
            batch_op.drop_constraint(old_name, type_="check")
            batch_op.create_check_constraint(new_name, condition)

    if connection.dialect.name != "sqlite":
        replace_constraint()
        return

    with op.get_context().autocommit_block():
        foreign_keys_enabled = bool(
            connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        )
        if foreign_keys_enabled:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            replace_constraint()
        finally:
            if foreign_keys_enabled:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """Restrict child ages to the product-supported range."""
    connection = op.get_bind()
    invalid_age_count = connection.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM children
            WHERE age NOT BETWEEN 1 AND 12
            """
        )
    )
    if invalid_age_count:
        raise RuntimeError(
            "Cannot enforce the child age range while children have ages "
            "outside 1 through 12. Update or delete those records before "
            "retrying the migration."
        )

    _replace_age_constraint(
        old_name="ck_children_positive_age",
        new_name="ck_children_age_range",
        condition="age BETWEEN 1 AND 12",
    )


def downgrade() -> None:
    """Restore the original positive-age-only constraint."""
    _replace_age_constraint(
        old_name="ck_children_age_range",
        new_name="ck_children_positive_age",
        condition="age >= 1",
    )
