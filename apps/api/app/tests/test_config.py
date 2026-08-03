from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_story_cost_ceiling_defaults_to_quarter_dollar() -> None:
    settings = Settings(_env_file=None)

    assert settings.story_cost_ceiling_usd == Decimal("0.25")


def test_story_cost_ceiling_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            story_cost_ceiling_usd=Decimal("-0.01"),
        )
