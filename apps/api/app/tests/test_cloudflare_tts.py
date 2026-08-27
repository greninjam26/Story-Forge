import traceback
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import cloudflare_tts, narration_providers
from app.services.cost_tracking import Usage


MODEL = "@cf/myshell-ai/melotts"
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00audio"


def _response(
    *,
    status_code: int = 200,
    payload: object | None = None,
    content_type: str = "audio/mpeg",
    content: bytes = MP3_BYTES,
    neurons: str | None = "0.70",
) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.headers = {"content-type": content_type}
    response.content = content
    if neurons is not None:
        response.headers["cf-ai-neurons"] = neurons
    response.json.return_value = (
        {"success": False, "errors": []}
        if payload is None
        else payload
    )
    return response


def _provider() -> cloudflare_tts.CloudflareNarrationProvider:
    return cloudflare_tts.CloudflareNarrationProvider(
        account_id="account id",
        api_token="secret-token",
        base_url="https://api.cloudflare.test/client/v4/",
        model=MODEL,
        timeout_seconds=60,
    )


def test_generate_accepts_cloudflare_binary_mp3_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(content_type="audio/mpeg")
    response.content = MP3_BYTES
    post = MagicMock(return_value=response)
    monkeypatch.setattr(cloudflare_tts, "_post", post)

    result = _provider().generate(
        narration_providers.NarrationProviderRequest(
            text="Bonsoir.",
            language="fr",
        )
    )

    assert result.audio_bytes == MP3_BYTES
    assert result.content_type == "audio/mpeg"
    assert result.provider == "cloudflare"
    assert result.model == MODEL
    assert result.usage == (Usage("millineuron", 700),)
    call = post.call_args
    assert call.args == (
        "https://api.cloudflare.test/client/v4/accounts/"
        "account%20id/ai/run/@cf/myshell-ai/melotts",
    )
    assert call.kwargs["headers"] == {
        "Authorization": "Bearer secret-token",
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    assert call.kwargs["json"] == {
        "prompt": "Bonsoir.",
        "lang": "fr",
    }
    assert call.kwargs["timeout"] == 60
    assert call.kwargs["follow_redirects"] is False


def test_generate_passes_english_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock(return_value=_response())
    monkeypatch.setattr(cloudflare_tts, "_post", post)

    _provider().generate(
        narration_providers.NarrationProviderRequest(
            text="Good night.",
            language="en",
        )
    )

    assert post.call_args.kwargs["json"]["lang"] == "en"


@pytest.mark.parametrize("value", [None, "", "invalid", "-0.1", "0.7001"])
def test_generate_marks_unusable_neuron_usage_unknown(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    monkeypatch.setattr(
        cloudflare_tts,
        "_post",
        MagicMock(return_value=_response(neurons=value)),
    )

    result = _provider().generate(
        narration_providers.NarrationProviderRequest(
            text="Good night.",
            language="en",
        )
    )

    assert result.usage is None


@pytest.mark.parametrize("account_id,api_token", [("", "token"), ("id", "")])
def test_provider_rejects_blank_credentials(
    account_id: str,
    api_token: str,
) -> None:
    with pytest.raises(ValueError, match="required"):
        cloudflare_tts.CloudflareNarrationProvider(
            account_id=account_id,
            api_token=api_token,
            base_url="https://api.cloudflare.test/client/v4",
            model=MODEL,
            timeout_seconds=60,
        )


def test_generate_rejects_blank_text_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock()
    monkeypatch.setattr(cloudflare_tts, "_post", post)

    with pytest.raises(ValueError, match="text cannot be empty"):
        _provider().generate(
            narration_providers.NarrationProviderRequest(
                text="   ",
                language="en",
            )
        )

    post.assert_not_called()


def test_test_harness_blocks_unmocked_cloudflare_tts_http() -> None:
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


@pytest.mark.parametrize("status_code", [408, 500, 502, 503])
def test_generate_classifies_retryable_http_statuses(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        cloudflare_tts,
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
    assert captured.value.provider == "cloudflare"


@pytest.mark.parametrize("status_code", [301, 400, 401, 403, 404])
def test_generate_classifies_permanent_http_statuses(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        cloudflare_tts,
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


@pytest.mark.parametrize(
    ("provider_code", "transient"),
    [(3036, False), (3040, True), (None, True)],
)
def test_generate_classifies_cloudflare_rate_limit_codes(
    monkeypatch: pytest.MonkeyPatch,
    provider_code: int | None,
    transient: bool,
) -> None:
    errors = [] if provider_code is None else [{"code": provider_code}]
    response = _response(
        status_code=429,
        payload={"success": False, "errors": errors},
    )
    monkeypatch.setattr(
        cloudflare_tts,
        "_post",
        MagicMock(return_value=response),
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

    assert captured.value.transient is transient
    assert captured.value.provider_code == provider_code


def test_generate_classifies_transport_error_as_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cloudflare_tts,
        "_post",
        MagicMock(side_effect=httpx.ConnectError("private URL")),
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


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("text/plain", MP3_BYTES),
        ("application/json", MP3_BYTES),
        ("audio/mpeg", b""),
        ("audio/mpeg", b"not an mp3"),
    ],
)
def test_generate_rejects_invalid_success_response(
    monkeypatch: pytest.MonkeyPatch,
    content_type: str,
    content: bytes,
) -> None:
    monkeypatch.setattr(
        cloudflare_tts,
        "_post",
        MagicMock(
            return_value=_response(
                content_type=content_type,
                content=content,
            )
        ),
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


def test_generate_handles_malformed_error_json_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(status_code=429, content_type="application/json")
    response.json.side_effect = ValueError("private payload")
    monkeypatch.setattr(
        cloudflare_tts,
        "_post",
        MagicMock(return_value=response),
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
    assert captured.value.provider_code is None
    assert captured.value.__context__ is None


def test_transport_error_does_not_expose_private_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cloudflare_tts,
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

    rendered = "".join(traceback.format_exception(captured.value))
    assert "secret-token" not in rendered
    assert "private narration" not in rendered
    assert "private URL" not in rendered
    assert "ConnectError" not in rendered


def test_http_error_does_not_expose_provider_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(
        status_code=400,
        payload={
            "success": False,
            "errors": [{"code": 3030, "message": "private message"}],
        },
    )
    monkeypatch.setattr(
        cloudflare_tts,
        "_post",
        MagicMock(return_value=response),
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

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.provider_code == 3030
    assert "private message" not in rendered
    assert "private narration" not in rendered
