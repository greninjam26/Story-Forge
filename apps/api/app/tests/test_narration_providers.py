import traceback
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import narration_providers
from app.services.cost_tracking import Usage


def test_elevenlabs_provider_requires_explicit_paid_call_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock()
    monkeypatch.setattr(narration_providers.httpx, "post", post)

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
    post = MagicMock(return_value=response)
    monkeypatch.setattr(narration_providers.httpx, "post", post)
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
    assert result.usage == (Usage("character", 17),)
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
    }
    assert call.kwargs["params"] == {
        "output_format": "mp3_44100_128",
    }
    assert call.kwargs["timeout"] == 60


def test_elevenlabs_provider_rejects_blank_text_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock()
    monkeypatch.setattr(narration_providers.httpx, "post", post)
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
        narration_providers.httpx,
        "post",
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
    assert str(captured.value) == "Narration provider request failed."
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "ConnectError" not in rendered_error
    assert "private provider" not in rendered_error


def test_elevenlabs_provider_rejects_empty_audio_with_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock(content=b"")
    monkeypatch.setattr(
        narration_providers.httpx,
        "post",
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
    assert captured.value.usage == (Usage("character", 20),)
    assert str(captured.value) == (
        "Narration provider returned an invalid response."
    )
