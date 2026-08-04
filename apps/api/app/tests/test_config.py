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


def test_story_provider_settings_accept_real_provider_configuration() -> None:
    configured = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        anthropic_model="claude-test",
        ollama_base_url="http://ollama.internal:11434",
        ollama_model="local-test",
    )

    assert configured.anthropic_api_key == "test-key"
    assert configured.anthropic_model == "claude-test"
    assert configured.ollama_base_url == "http://ollama.internal:11434"
    assert configured.ollama_model == "local-test"


@pytest.mark.parametrize(
    "setting_name",
    [
        "anthropic_input_cost_per_million_usd",
        "anthropic_output_cost_per_million_usd",
    ],
)
def test_story_provider_costs_reject_negative_values(
    setting_name: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            **{setting_name: Decimal("-0.01")},
        )
