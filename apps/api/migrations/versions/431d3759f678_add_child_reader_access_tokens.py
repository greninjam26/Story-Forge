"""add child reader access tokens

Revision ID: 431d3759f678
Revises: c4e8f1a2b390
Create Date: 2026-09-03 22:54:54.350255

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '431d3759f678'
down_revision: Union[str, Sequence[str], None] = 'c4e8f1a2b390'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _set_reader_access_token_not_null() -> None:
    connection = op.get_bind()

    def alter_children() -> None:
        with op.batch_alter_table("children", schema=None) as batch_op:
            batch_op.alter_column(
                "reader_access_token",
                existing_type=sa.Uuid(),
                nullable=False,
            )
            batch_op.create_index(
                "ix_children_reader_access_token",
                ["reader_access_token"],
                unique=True,
            )

    if connection.dialect.name != "sqlite":
        alter_children()
        return

    with op.get_context().autocommit_block():
        foreign_keys_enabled = bool(
            connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        )
        if foreign_keys_enabled:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            alter_children()
        finally:
            if foreign_keys_enabled:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def _drop_reader_access_token() -> None:
    connection = op.get_bind()

    def alter_children() -> None:
        with op.batch_alter_table("children", schema=None) as batch_op:
            batch_op.drop_index("ix_children_reader_access_token")
            batch_op.drop_column("reader_access_token")

    if connection.dialect.name != "sqlite":
        alter_children()
        return

    with op.get_context().autocommit_block():
        foreign_keys_enabled = bool(
            connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        )
        if foreign_keys_enabled:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            alter_children()
        finally:
            if foreign_keys_enabled:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """Add revocable, unique reader capability tokens to children."""
    op.add_column(
        "children",
        sa.Column("reader_access_token", sa.Uuid(), nullable=True),
    )

    connection = op.get_bind()
    child_ids = connection.execute(sa.text("SELECT id FROM children"))
    for (child_id,) in child_ids:
        connection.execute(
            sa.text(
                "UPDATE children SET reader_access_token = :token "
                "WHERE id = :child_id"
            ),
            {"token": str(uuid.uuid4()), "child_id": child_id},
        )

    _set_reader_access_token_not_null()


def downgrade() -> None:
    """Remove reader capability tokens."""
    _drop_reader_access_token()
