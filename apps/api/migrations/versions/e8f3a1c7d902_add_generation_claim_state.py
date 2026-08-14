"""Add durable story generation claim state.

Revision ID: e8f3a1c7d902
Revises: c1d5e7a9b302
Create Date: 2026-08-14 00:00:00.000000

"""

from collections.abc import Callable
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from alembic.operations import BatchOperations


revision: str = "e8f3a1c7d902"
down_revision: Union[str, Sequence[str], None] = "c1d5e7a9b302"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _alter_stories(
    operation: Callable[[BatchOperations], None],
) -> None:
    connection = op.get_bind()

    def alter_table() -> None:
        with op.batch_alter_table("stories", schema=None) as batch_op:
            operation(batch_op)

    if connection.dialect.name != "sqlite":
        alter_table()
        return

    # SQLite batch mode rebuilds the stories table. Disable foreign-key
    # actions while replacing it so owned pages and audit rows survive.
    with op.get_context().autocommit_block():
        foreign_keys_enabled = bool(
            connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        )
        if foreign_keys_enabled:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            alter_table()
        finally:
            if foreign_keys_enabled:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """Add claim fencing, retry count, and resumable stage state."""

    def add_claim_state(batch_op: BatchOperations) -> None:
        batch_op.add_column(
            sa.Column("generation_claim_token", sa.Uuid(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "generation_claimed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "generation_attempts",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "generation_stage",
                sa.Enum(
                    "story_text",
                    "moderation",
                    "illustrations",
                    "narration",
                    "complete",
                    name="generation_stage",
                    native_enum=False,
                    create_constraint=True,
                ),
                server_default="story_text",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_stories_nonnegative_generation_attempts",
            "generation_attempts >= 0",
        )
        batch_op.create_check_constraint(
            "ck_stories_generation_claim_pair",
            "(generation_claim_token IS NULL AND "
            "generation_claimed_at IS NULL) OR "
            "(generation_claim_token IS NOT NULL AND "
            "generation_claimed_at IS NOT NULL)",
        )

    _alter_stories(add_claim_state)


def downgrade() -> None:
    """Remove durable story generation claim state."""

    def remove_claim_state(batch_op: BatchOperations) -> None:
        batch_op.drop_constraint(
            "ck_stories_generation_claim_pair",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_stories_nonnegative_generation_attempts",
            type_="check",
        )
        batch_op.drop_constraint("generation_stage", type_="check")
        batch_op.drop_column("generation_stage")
        batch_op.drop_column("generation_attempts")
        batch_op.drop_column("generation_claimed_at")
        batch_op.drop_column("generation_claim_token")

    _alter_stories(remove_claim_state)
