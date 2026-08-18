"""add billing fields and stripe_events table

Revision ID: 537bbd8aacb6
Revises: d1ef64a9bdb0
Create Date: 2026-08-17 18:50:45.080139

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '537bbd8aacb6'
down_revision: Union[str, Sequence[str], None] = 'd1ef64a9bdb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _disable_fk_for_batch(connection) -> bool:
    foreign_keys_enabled = bool(
        connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    )
    if foreign_keys_enabled:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    return foreign_keys_enabled


def _restore_fk(connection, was_enabled: bool) -> None:
    if was_enabled:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """Apply this migration."""
    op.create_table('stripe_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('stripe_customer_id', sa.String(), nullable=True),
    sa.Column('parent_id', sa.String(), nullable=True),
    sa.Column('stripe_created', sa.Integer(), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('stripe_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stripe_events_stripe_customer_id'), ['stripe_customer_id'], unique=False)

    connection = op.get_bind()
    fk_was_enabled = False
    if connection.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            fk_was_enabled = _disable_fk_for_batch(connection)
    try:
        with op.batch_alter_table('parents', schema=None) as batch_op:
            batch_op.add_column(sa.Column('free_stories_used', sa.Integer(), server_default='0', nullable=False))
            batch_op.add_column(sa.Column('is_subscribed', sa.Boolean(), server_default='0', nullable=False))
            batch_op.add_column(sa.Column('stripe_customer_id', sa.String(), nullable=True))
            batch_op.add_column(sa.Column('stripe_subscription_id', sa.String(), nullable=True))
    finally:
        if connection.dialect.name == "sqlite":
            _restore_fk(connection, fk_was_enabled)


def downgrade() -> None:
    """Revert this migration."""
    connection = op.get_bind()
    fk_was_enabled = False
    if connection.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            fk_was_enabled = _disable_fk_for_batch(connection)
    try:
        with op.batch_alter_table('parents', schema=None) as batch_op:
            batch_op.drop_column('stripe_subscription_id')
            batch_op.drop_column('stripe_customer_id')
            batch_op.drop_column('is_subscribed')
            batch_op.drop_column('free_stories_used')
    finally:
        if connection.dialect.name == "sqlite":
            _restore_fk(connection, fk_was_enabled)

    with op.batch_alter_table('stripe_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stripe_events_stripe_customer_id'))

    op.drop_table('stripe_events')
