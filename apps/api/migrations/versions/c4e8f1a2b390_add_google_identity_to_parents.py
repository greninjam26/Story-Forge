"""Add Google identity fields to parents.

Revision ID: c4e8f1a2b390
Revises: a9c4e2f7b631
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4e8f1a2b390"
down_revision: Union[str, Sequence[str], None] = "a9c4e2f7b631"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _disable_sqlite_foreign_keys(connection) -> bool:
    enabled = bool(connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
    if enabled:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    return enabled


def _restore_sqlite_foreign_keys(connection, was_enabled: bool) -> None:
    if was_enabled:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """Add nullable Google linking and verified-email state."""
    connection = op.get_bind()
    foreign_keys_were_enabled = False
    if connection.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            foreign_keys_were_enabled = _disable_sqlite_foreign_keys(connection)
    try:
        with op.batch_alter_table("parents") as batch_op:
            batch_op.add_column(
                sa.Column("google_subject", sa.String(length=255), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "email_verified",
                    sa.Boolean(),
                    server_default="0",
                    nullable=False,
                )
            )
            batch_op.create_index(
                "ix_parents_google_subject",
                ["google_subject"],
                unique=True,
            )
    finally:
        if connection.dialect.name == "sqlite":
            _restore_sqlite_foreign_keys(
                connection,
                foreign_keys_were_enabled,
            )


def downgrade() -> None:
    """Remove Google identity fields."""
    connection = op.get_bind()
    foreign_keys_were_enabled = False
    if connection.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            foreign_keys_were_enabled = _disable_sqlite_foreign_keys(connection)
    try:
        with op.batch_alter_table("parents") as batch_op:
            batch_op.drop_index("ix_parents_google_subject")
            batch_op.drop_column("email_verified")
            batch_op.drop_column("google_subject")
    finally:
        if connection.dialect.name == "sqlite":
            _restore_sqlite_foreign_keys(
                connection,
                foreign_keys_were_enabled,
            )
