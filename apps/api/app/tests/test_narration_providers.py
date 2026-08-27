import traceback
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import narration_providers
from app.services.cost_tracking import Usage


def test_request_error_keeps_adapter_metadata_and_retryability() -> None:
    error = narration_providers.NarrationProviderRequestError(
        provider="cloudflare",
        model="@cf/myshell-ai/melotts",
        usage=(Usage("millineuron", 700),),
        transient=False,
        provider_code=3036,
    )

    assert error.provider == "cloudflare"
    assert error.model == "@cf/myshell-ai/melotts"
    assert error.usage == (Usage("millineuron", 700),)
    assert error.transient is False
    assert error.provider_code == 3036
    assert str(error) == "Narration provider request failed."


def test_elevenlabs_provider_requires_explicit_paid_call_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock()
    monkeypatch.setattr(narration_providers, "_post", post)

    with pytest.raises(
        narration_providers.PaidNarrationDisabledError,
        match="disabled",
    ):
        narration_providers.ElevenLabsNarrationProvider(
            api_key="test-key",
            voice_id="voice-test",
            model="model-test",
            base_url="https://elevenlabs.test/v1",
            timeout_seconds=60,
            paid_calls_enabled=False,
        )

    post.assert_not_called()


@pytest.mark.parametrize(
    ("api_key", "voice_id", "message"),
    [
        (None, "voice-test", "API key"),
        ("test-key", None, "voice ID"),
    ],
)
def test_elevenlabs_provider_requires_credentials(
    api_key: str | None,
    voice_id: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        narration_providers.ElevenLabsNarrationProvider(
            api_key=api_key,
            voice_id=voice_id,
            model="model-test",
            base_url="https://elevenlabs.test/v1",
            timeout_seconds=60,
            paid_calls_enabled=True,
        )


def test_elevenlabs_provider_returns_mp3_bytes_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock(content=b"ID3audio")
    response.headers = {
        "content-type": "audio/mpeg",
        "character-cost": "23",
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(narration_providers, "_post", post)
    provider = narration_providers.ElevenLabsNarrationProvider(
        api_key="test-key",
        voice_id="voice-test",
        model="model-test",
        base_url="https://elevenlabs.test/v1/",
        timeout_seconds=60,
        paid_calls_enabled=True,
    )

    result = provider.generate(
        narration_providers.NarrationProviderRequest(
            text="Bonsoir, Camille.",
            language="fr",
        )
    )

    assert result.audio_bytes == b"ID3audio"
    assert result.content_type == "audio/mpeg"
    assert result.provider == "elevenlabs"
    assert result.model == "model-test"
    assert result.usage == (Usage("character", 23),)
    response.raise_for_status.assert_called_once_with()
    call = post.call_args
    assert call.args == (
        "https://elevenlabs.test/v1/text-to-speech/voice-test",
    )
    assert call.kwargs["headers"] == {
        "xi-api-key": "test-key",
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    assert call.kwargs["json"] == {
        "text": "Bonsoir, Camille.",
        "model_id": "model-test",
        "language_code": "fr",
    }
    assert call.kwargs["params"] == {
        "output_format": "mp3_44100_128",
    }
    assert call.kwargs["timeout"] == 60


def test_elevenlabs_provider_rejects_non_audio_response_with_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock(content=b'{"detail":"temporary failure"}')
    response.headers = {
        "content-type": "application/json",
        "character-cost": "25",
    }
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(return_value=response),
    )
    provider = narration_providers.ElevenLabsNarrationProvider(
        api_key="test-key",
        voice_id="voice-test",
        model="model-test",
        base_url="https://elevenlabs.test/v1",
        timeout_seconds=60,
        paid_calls_enabled=True,
    )

    with pytest.raises(
        narration_providers.InvalidNarrationProviderResponse
    ) as captured:
        provider.generate(
            narration_providers.NarrationProviderRequest(
                text="Good night, Camille.",
                language="en",
            )
        )

    assert captured.value.provider == "elevenlabs"
    assert captured.value.model == "model-test"
    assert captured.value.usage == (Usage("character", 25),)


@pytest.mark.parametrize("character_cost", [None, "", "not-a-number", "-1"])
def test_elevenlabs_provider_marks_unusable_cost_header_unknown(
    monkeypatch: pytest.MonkeyPatch,
    character_cost: str | None,
) -> None:
    response = MagicMock(content=b"ID3audio")
    response.headers = {"content-type": "audio/mpeg"}
    if character_cost is not None:
        response.headers["character-cost"] = character_cost
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(return_value=response),
    )
    provider = narration_providers.ElevenLabsNarrationProvider(
        api_key="test-key",
        voice_id="voice-test",
        model="model-test",
        base_url="https://elevenlabs.test/v1",
        timeout_seconds=60,
        paid_calls_enabled=True,
    )

    result = provider.generate(
        narration_providers.NarrationProviderRequest(
            text="Good night, Camille.",
            language="en",
        )
    )

    assert result.usage is None


def test_test_harness_blocks_unmocked_paid_tts_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_post = MagicMock()
    monkeypatch.setattr(narration_providers.httpx, "post", http_post)
    provider = narration_providers.ElevenLabsNarrationProvider(
        api_key="would-be-real-key",
        voice_id="would-be-real-voice",
        model="model-test",
        base_url="https://paid-provider.invalid/v1",
        timeout_seconds=60,
        paid_calls_enabled=True,
    )

    with pytest.raises(
        AssertionError,
        match="paid TTS provider access is forbidden in tests",
    ):
        provider.generate(
            narration_providers.NarrationProviderRequest(
                text="Good night, Camille.",
                language="en",
            )
        )

    http_post.assert_not_called()


def test_elevenlabs_provider_rejects_blank_text_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock()
    monkeypatch.setattr(narration_providers, "_post", post)
    provider = narration_providers.ElevenLabsNarrationProvider(
        api_key="test-key",
        voice_id="voice-test",
        model="model-test",
        base_url="https://elevenlabs.test/v1",
        timeout_seconds=60,
        paid_calls_enabled=True,
    )

    with pytest.raises(ValueError, match="text cannot be empty"):
        provider.generate(
            narration_providers.NarrationProviderRequest(
                text="   ",
                language="en",
            )
        )

    post.assert_not_called()


def test_elevenlabs_provider_sanitizes_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(
            side_effect=httpx.ConnectError(
                "private provider URL and request details"
            )
        ),
    )
    provider = narration_providers.ElevenLabsNarrationProvider(
        api_key="test-key",
        voice_id="voice-test",
        model="model-test",
        base_url="https://elevenlabs.test/v1",
        timeout_seconds=60,
        paid_calls_enabled=True,
    )

    with pytest.raises(
        narration_providers.NarrationProviderRequestError
    ) as captured:
        provider.generate(
            narration_providers.NarrationProviderRequest(
                text="Good night, Camille.",
                language="en",
            )
        )

    assert captured.value.provider == "elevenlabs"
    assert captured.value.model == "model-test"
    assert captured.value.usage is None
    assert captured.value.transient is True
    assert captured.value.provider_code is None
    assert str(captured.value) == "Narration provider request failed."
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "ConnectError" not in rendered_error
    assert "private provider" not in rendered_error


def test_elevenlabs_provider_rejects_empty_audio_with_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock(content=b"")
    response.headers = {
        "content-type": "audio/mpeg",
        "character-cost": "31",
    }
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(return_value=response),
    )
    provider = narration_providers.ElevenLabsNarrationProvider(
        api_key="test-key",
        voice_id="voice-test",
        model="model-test",
        base_url="https://elevenlabs.test/v1",
        timeout_seconds=60,
        paid_calls_enabled=True,
    )

    with pytest.raises(
        narration_providers.InvalidNarrationProviderResponse
    ) as captured:
        provider.generate(
            narration_providers.NarrationProviderRequest(
                text="Good night, Camille.",
                language="en",
            )
        )

    assert captured.value.provider == "elevenlabs"
    assert captured.value.model == "model-test"
    assert captured.value.usage == (Usage("character", 31),)
    assert str(captured.value) == (
        "Narration provider returned an invalid response."
    )
