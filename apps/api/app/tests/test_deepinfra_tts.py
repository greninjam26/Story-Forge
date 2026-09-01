import base64
import traceback
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import deepinfra_tts, narration_providers
from app.services.cost_tracking import Usage


MODEL = "hexgrad/Kokoro-82M"
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00audio"


def _response(
    *,
    status_code: int = 200,
    payload: object | None = None,
    content: bytes = b"{}",
) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.headers = {"content-type": "application/json"}
    response.content = content
    response.json.return_value = (
        {
            "audio": base64.b64encode(MP3_BYTES).decode("ascii"),
            "input_character_length": 11,
            "output_format": "mp3",
            "words": [],
            "request_id": "request-private",
            "inference_status": {
                "status": "succeeded",
                "runtime_ms": 12,
                "cost": 0.00000682,
                "tokens_generated": 0,
                "tokens_input": 0,
                "output_length": len(MP3_BYTES),
            },
        }
        if payload is None
        else payload
    )
    return response


def _provider(
    *,
    api_token: str | None = "secret-token",
    paid_calls_enabled: bool = True,
) -> deepinfra_tts.DeepInfraNarrationProvider:
    return deepinfra_tts.DeepInfraNarrationProvider(
        api_token=api_token,
        base_url="https://api.deepinfra.test/v1/",
        model=MODEL,
        en_voice="af_heart",
        fr_voice="ff_siwis",
        speed=0.9,
        timeout_seconds=60,
        paid_calls_enabled=paid_calls_enabled,
    )


@pytest.mark.parametrize(
    ("language", "voice", "text", "character_count"),
    [
        ("en", "af_heart", "Good night.", 11),
        ("fr", "ff_siwis", "Bonne nuit.", 11),
    ],
)
def test_generate_requests_and_decodes_kokoro_mp3(
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    voice: str,
    text: str,
    character_count: int,
) -> None:
    post = MagicMock(return_value=_response())
    monkeypatch.setattr(deepinfra_tts, "_post", post)

    result = _provider().generate(
        narration_providers.NarrationProviderRequest(
            text=text,
            language=language,  # type: ignore[arg-type]
        )
    )

    assert result.audio_bytes == MP3_BYTES
    assert result.content_type == "audio/mpeg"
    assert result.provider == "deepinfra"
    assert result.model == MODEL
    assert result.usage == (Usage("character", character_count),)
    call = post.call_args
    assert call.args == (
        "https://api.deepinfra.test/v1/inference/hexgrad/Kokoro-82M",
    )
    assert call.kwargs["headers"] == {
        "Authorization": "Bearer secret-token",
        "Content-Type": "application/json",
    }
    assert call.kwargs["json"] == {
        "text": text,
        "output_format": "mp3",
        "preset_voice": [voice],
        "speed": 0.9,
        "stream": False,
        "return_timestamps": False,
    }
    assert call.kwargs["timeout"] == 60
    assert call.kwargs["follow_redirects"] is False


def test_generate_accepts_audio_data_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _response().json.return_value
    payload["audio"] = (
        "data:audio/mpeg;base64,"
        + base64.b64encode(MP3_BYTES).decode("ascii")
    )
    monkeypatch.setattr(
        deepinfra_tts,
        "_post",
        MagicMock(return_value=_response(payload=payload)),
    )

    result = _provider().generate(
        narration_providers.NarrationProviderRequest(
            text="Good night.",
            language="en",
        )
    )

    assert result.audio_bytes == MP3_BYTES


@pytest.mark.parametrize("provider_usage", [-1, 0, True, "11"])
def test_generate_uses_request_length_when_provider_usage_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    provider_usage: object,
) -> None:
    payload = _response().json.return_value
    payload["input_character_length"] = provider_usage
    monkeypatch.setattr(
        deepinfra_tts,
        "_post",
        MagicMock(return_value=_response(payload=payload)),
    )

    result = _provider().generate(
        narration_providers.NarrationProviderRequest(
            text="Good night.",
            language="en",
        )
    )

    assert result.usage == (Usage("character", 11),)


@pytest.mark.parametrize(
    ("api_token", "base_url", "model", "en_voice", "fr_voice"),
    [
        (None, "https://api.test", MODEL, "af_heart", "ff_siwis"),
        (" ", "https://api.test", MODEL, "af_heart", "ff_siwis"),
        ("token", " ", MODEL, "af_heart", "ff_siwis"),
        ("token", "https://api.test", " ", "af_heart", "ff_siwis"),
        ("token", "https://api.test", MODEL, " ", "ff_siwis"),
        ("token", "https://api.test", MODEL, "af_heart", " "),
    ],
)
def test_provider_rejects_missing_configuration(
    api_token: str | None,
    base_url: str,
    model: str,
    en_voice: str,
    fr_voice: str,
) -> None:
    with pytest.raises(ValueError, match="required"):
        deepinfra_tts.DeepInfraNarrationProvider(
            api_token=api_token,
            base_url=base_url,
            model=model,
            en_voice=en_voice,
            fr_voice=fr_voice,
            speed=1,
            timeout_seconds=60,
            paid_calls_enabled=True,
        )


def test_provider_rejects_blank_text_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock()
    monkeypatch.setattr(deepinfra_tts, "_post", post)

    with pytest.raises(ValueError, match="text cannot be empty"):
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="   ",
                language="en",
            )
        )

    post.assert_not_called()


def test_test_harness_blocks_unmocked_deepinfra_tts_http() -> None:
    with pytest.raises(
        AssertionError,
        match="paid TTS provider access is forbidden in tests",
    ):
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="Good night.",
                language="en",
            )
        )


@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503])
def test_generate_classifies_retryable_http_statuses(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        deepinfra_tts,
        "_post",
        MagicMock(return_value=_response(status_code=status_code)),
    )

    with pytest.raises(
        narration_providers.NarrationProviderRequestError
    ) as captured:
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="Good night.",
                language="en",
            )
        )

    assert captured.value.transient is True
    assert captured.value.provider == "deepinfra"


@pytest.mark.parametrize("status_code", [301, 400, 401, 403, 404, 422])
def test_generate_classifies_permanent_http_statuses(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        deepinfra_tts,
        "_post",
        MagicMock(return_value=_response(status_code=status_code)),
    )

    with pytest.raises(
        narration_providers.NarrationProviderRequestError
    ) as captured:
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="Good night.",
                language="en",
            )
        )

    assert captured.value.transient is False


def test_generate_preserves_safe_numeric_provider_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deepinfra_tts,
        "_post",
        MagicMock(
            return_value=_response(
                status_code=400,
                payload={
                    "errors": [
                        {"code": 3001, "message": "private provider text"}
                    ]
                },
            )
        ),
    )

    with pytest.raises(
        narration_providers.NarrationProviderRequestError
    ) as captured:
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="private narration",
                language="en",
            )
        )

    assert captured.value.provider_code == 3001
    rendered = "".join(traceback.format_exception(captured.value))
    assert "private provider text" not in rendered
    assert "private narration" not in rendered


def test_generate_classifies_transport_error_without_private_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deepinfra_tts,
        "_post",
        MagicMock(
            side_effect=httpx.ConnectError(
                "secret-token private narration private URL"
            )
        ),
    )

    with pytest.raises(
        narration_providers.NarrationProviderRequestError
    ) as captured:
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="private narration",
                language="en",
            )
        )

    assert captured.value.transient is True
    rendered = "".join(traceback.format_exception(captured.value))
    assert "secret-token" not in rendered
    assert "private narration" not in rendered
    assert "private URL" not in rendered
    assert "ConnectError" not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"audio": ""},
        {"audio": "not base64"},
        {"audio": base64.b64encode(b"not an mp3").decode("ascii")},
        {"audio": "data:text/plain;base64,SGVsbG8="},
    ],
)
def test_generate_rejects_invalid_success_audio(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(
        deepinfra_tts,
        "_post",
        MagicMock(return_value=_response(payload=payload)),
    )

    with pytest.raises(
        narration_providers.InvalidNarrationProviderResponse
    ):
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="Good night.",
                language="en",
            )
        )


def test_generate_rejects_malformed_or_oversized_success_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = _response()
    malformed.json.side_effect = ValueError("private response")
    oversized = _response(
        content=b"x" * (deepinfra_tts.MAX_RESPONSE_BYTES + 1)
    )

    for response in (malformed, oversized):
        monkeypatch.setattr(
            deepinfra_tts,
            "_post",
            MagicMock(return_value=response),
        )
        with pytest.raises(
            narration_providers.InvalidNarrationProviderResponse
        ) as captured:
            _provider().generate(
                narration_providers.NarrationProviderRequest(
                    text="Good night.",
                    language="en",
                )
            )
        assert captured.value.__context__ is None
