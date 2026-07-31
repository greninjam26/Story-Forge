"""Add generation cost ledger.

Revision ID: a62f4d9e8b13
Revises: d3a7c4b91f20
Create Date: 2026-07-31 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a62f4d9e8b13"
down_revision: Union[str, Sequence[str], None] = "d3a7c4b91f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create generation runs and their provider cost events."""
    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "in_progress",
                "succeeded",
                "rejected",
                "failed",
                name="generation_run_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="in_progress",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "known_cost_usd",
            sa.Numeric(precision=18, scale=12),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "cost_complete",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "ceiling_exceeded",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "known_cost_usd >= 0",
            name="ck_generation_runs_nonnegative_known_cost",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_generation_runs_status_completed_at",
        "generation_runs",
        ["status", "completed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_runs_story_id"),
        "generation_runs",
        ["story_id"],
        unique=False,
    )

    op.create_table(
        "generation_cost_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_run_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("usage_unit", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column(
            "unit_rate_usd",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column("cost_known", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt >= 1",
            name="ck_generation_cost_events_positive_attempt",
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_generation_cost_events_positive_page_number",
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_generation_cost_events_nonnegative_quantity",
        ),
        sa.CheckConstraint(
            "unit_rate_usd IS NULL OR unit_rate_usd >= 0",
            name="ck_generation_cost_events_nonnegative_unit_rate",
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0",
            name="ck_generation_cost_events_nonnegative_cost",
        ),
        sa.CheckConstraint(
            "(cost_known AND quantity IS NOT NULL "
            "AND unit_rate_usd IS NOT NULL AND cost_usd IS NOT NULL) "
            "OR (NOT cost_known AND cost_usd IS NULL)",
            name="ck_generation_cost_events_known_cost_details",
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["generation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generation_cost_events_call_id"),
        "generation_cost_events",
        ["call_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_cost_events_generation_run_id"),
        "generation_cost_events",
        ["generation_run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove generation runs and provider cost events."""
    op.drop_index(
        op.f("ix_generation_cost_events_generation_run_id"),
        table_name="generation_cost_events",
    )
    op.drop_index(
        op.f("ix_generation_cost_events_call_id"),
        table_name="generation_cost_events",
    )
    op.drop_table("generation_cost_events")

    op.drop_index(
        op.f("ix_generation_runs_story_id"),
        table_name="generation_runs",
    )
    op.drop_index(
        "ix_generation_runs_status_completed_at",
        table_name="generation_runs",
    )
    op.drop_table("generation_runs")
