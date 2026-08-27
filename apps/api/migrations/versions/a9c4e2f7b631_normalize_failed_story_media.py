"""Normalize legacy failed story media for safe recovery.

Revision ID: a9c4e2f7b631
Revises: 537bbd8aacb6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a9c4e2f7b631"
down_revision: Union[str, Sequence[str], None] = "537bbd8aacb6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clear potentially deleted media and reset legacy failed rows."""
    op.execute(
        sa.text(
            """
            UPDATE story_pages
            SET image_url = NULL, audio_url = NULL
            WHERE EXISTS (
                SELECT 1 FROM stories
                WHERE stories.id = story_pages.story_id
                  AND stories.status = 'generation_failed'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM story_pages
            WHERE EXISTS (
                SELECT 1 FROM stories
                WHERE stories.id = story_pages.story_id
                  AND stories.status = 'generation_failed'
                  AND TRIM(stories.title) = ''
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE stories
            SET generation_stage = CASE
                    WHEN TRIM(title) <> '' AND EXISTS (
                        SELECT 1 FROM story_pages
                        WHERE story_pages.story_id = stories.id
                    ) THEN 'illustrations'
                    ELSE 'story_text'
                END,
                generation_claim_token = NULL,
                generation_claimed_at = NULL
            WHERE status = 'generation_failed'
            """
        )
    )


def downgrade() -> None:
    """Data repair is irreversible; cleared references cannot be reconstructed."""
    pass
