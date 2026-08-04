from decimal import Decimal
from pathlib import Path

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


def test_narration_provider_defaults_keep_paid_calls_disabled() -> None:
    configured = Settings(_env_file=None)

    assert configured.tts_provider == "stub"
    assert configured.paid_tts_enabled is False
    assert configured.elevenlabs_api_key is None
    assert configured.elevenlabs_voice_id is None
    assert configured.elevenlabs_model_id == "eleven_v3"
    assert configured.elevenlabs_base_url == "https://api.elevenlabs.io/v1"
    assert configured.elevenlabs_request_timeout_seconds == 60
    assert configured.elevenlabs_cost_per_character_usd is None


def test_narration_provider_settings_accept_elevenlabs_configuration() -> None:
    configured = Settings(
        _env_file=None,
        tts_provider="elevenlabs",
        paid_tts_enabled=True,
        elevenlabs_api_key="test-key",
        elevenlabs_voice_id="voice-test",
        elevenlabs_model_id="model-test",
        elevenlabs_base_url="https://elevenlabs.internal/v1",
        elevenlabs_request_timeout_seconds=90,
        elevenlabs_cost_per_character_usd=Decimal("0.0002"),
    )

    assert configured.tts_provider == "elevenlabs"
    assert configured.paid_tts_enabled is True
    assert configured.elevenlabs_api_key == "test-key"
    assert configured.elevenlabs_voice_id == "voice-test"
    assert configured.elevenlabs_model_id == "model-test"
    assert configured.elevenlabs_base_url == "https://elevenlabs.internal/v1"
    assert configured.elevenlabs_request_timeout_seconds == 90
    assert configured.elevenlabs_cost_per_character_usd == Decimal("0.0002")


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


def test_narration_provider_cost_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            elevenlabs_cost_per_character_usd=Decimal("-0.01"),
        )


def test_narration_provider_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            elevenlabs_request_timeout_seconds=0,
        )


def test_narration_cache_directory_is_configurable() -> None:
    defaults = Settings(_env_file=None)
    configured = Settings(
        _env_file=None,
        narration_cache_dir="/tmp/story-forge-audio",
    )

    assert defaults.narration_cache_dir == Path("audio_cache")
    assert configured.narration_cache_dir == Path("/tmp/story-forge-audio")
