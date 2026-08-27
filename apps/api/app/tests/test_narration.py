from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import settings
from app.services import (
    cloudflare_tts,
    narration,
    narration_providers,
    narration_storage,
)
from app.services.cost_tracking import Usage


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_call(self, **call: object) -> None:
        self.calls.append(call)


class FakeHostedNarrationProvider:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[
            narration_providers.NarrationProviderRequest
        ] = []

    def generate(
        self,
        request: narration_providers.NarrationProviderRequest,
    ) -> narration_providers.NarrationProviderResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(
            outcome,
            narration_providers.NarrationProviderResponse,
        )
        return outcome


def _hosted_response() -> narration_providers.NarrationProviderResponse:
    return narration_providers.NarrationProviderResponse(
        audio_bytes=b"ID3audio",
        content_type="audio/mpeg",
        provider="cloudflare",
        model="@cf/myshell-ai/melotts",
        usage=(Usage("millineuron", 700),),
    )


def test_hosted_narration_retries_only_transient_request_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    provider = FakeHostedNarrationProvider(
        [
            narration_providers.NarrationProviderRequestError(
                provider="cloudflare",
                model="@cf/myshell-ai/melotts",
                usage=None,
                transient=True,
            ),
            narration_providers.NarrationProviderRequestError(
                provider="cloudflare",
                model="@cf/myshell-ai/melotts",
                usage=None,
                transient=True,
            ),
            _hosted_response(),
        ]
    )
    recorder = Recorder()
    request = narration_providers.NarrationProviderRequest(
        text="Good night.",
        language="en",
    )

    audio_url = narration._generate_hosted_narration(
        provider=provider,
        request=request,
        recorder=recorder,
    )

    assert audio_url.endswith(".mp3")
    assert len(provider.requests) == 3
    assert [call["attempt"] for call in recorder.calls] == [1, 2, 3]
    assert [call["outcome"] for call in recorder.calls] == [
        "provider_failure",
        "provider_failure",
        "succeeded",
    ]


def test_hosted_narration_does_not_retry_permanent_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    provider = FakeHostedNarrationProvider(
        [
            narration_providers.NarrationProviderRequestError(
                provider="cloudflare",
                model="@cf/myshell-ai/melotts",
                usage=(Usage("millineuron", 700),),
                transient=False,
                provider_code=3036,
            )
        ]
    )
    recorder = Recorder()

    with pytest.raises(narration_providers.NarrationProviderRequestError):
        narration._generate_hosted_narration(
            provider=provider,
            request=narration_providers.NarrationProviderRequest(
                text="Good night.",
                language="en",
            ),
            recorder=recorder,
        )

    assert len(provider.requests) == 1
    assert recorder.calls[0]["outcome"] == "provider_failure"
    assert recorder.calls[0]["usage"] == (Usage("millineuron", 700),)


def test_hosted_narration_records_invalid_response_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    provider = FakeHostedNarrationProvider(
        [
            narration_providers.InvalidNarrationProviderResponse(
                provider="cloudflare",
                model="@cf/myshell-ai/melotts",
                usage=None,
            )
        ]
    )
    recorder = Recorder()

    with pytest.raises(
        narration_providers.InvalidNarrationProviderResponse
    ):
        narration._generate_hosted_narration(
            provider=provider,
            request=narration_providers.NarrationProviderRequest(
                text="Good night.",
                language="en",
            ),
            recorder=recorder,
        )

    assert len(provider.requests) == 1
    assert recorder.calls[0]["outcome"] == "invalid_response"


def _configure_elevenlabs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "tts_provider", "elevenlabs")
    monkeypatch.setattr(settings, "paid_tts_enabled", True)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice-test")
    monkeypatch.setattr(settings, "elevenlabs_model_id", "model-test")
    monkeypatch.setattr(
        settings,
        "elevenlabs_base_url",
        "https://elevenlabs.test/v1",
    )
    monkeypatch.setattr(settings, "elevenlabs_request_timeout_seconds", 60)
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)


def _configure_cloudflare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "tts_provider", "cloudflare")
    monkeypatch.setattr(settings, "cloudflare_ai_account_id", "account-id")
    monkeypatch.setattr(settings, "cloudflare_ai_api_token", "token")
    monkeypatch.setattr(
        settings,
        "cloudflare_ai_base_url",
        "https://api.cloudflare.test/client/v4",
    )
    monkeypatch.setattr(settings, "cloudflare_tts_model", "model-test")
    monkeypatch.setattr(settings, "cloudflare_tts_timeout_seconds", 60)
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)


def test_generate_narration_uses_cloudflare_and_stores_mp3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cloudflare(monkeypatch, tmp_path)
    generate = MagicMock(return_value=_hosted_response())
    monkeypatch.setattr(
        cloudflare_tts.CloudflareNarrationProvider,
        "generate",
        generate,
    )
    recorder = Recorder()

    audio_url = narration.generate_narration(
        text="Good night.",
        language="en",
        recorder=recorder,
    )

    assert audio_url.endswith(".mp3")
    token = audio_url.rsplit("/", 1)[-1].removesuffix(".mp3")
    assert narration_storage.read_narration_mp3(token) == b"ID3audio"
    request = generate.call_args.args[0]
    assert request.text == "Good night."
    assert request.language == "en"
    assert recorder.calls[0]["provider"] == "cloudflare"
    assert recorder.calls[0]["outcome"] == "succeeded"
    assert recorder.calls[0]["usage"] == (Usage("millineuron", 700),)


def test_generate_narration_uses_elevenlabs_and_stores_mp3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    response = MagicMock(content=b"ID3audio")
    response.headers = {
        "content-type": "audio/mpeg",
        "character-cost": "13",
    }
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(return_value=response),
    )
    recorder = Recorder()

    audio_url = narration.generate_narration(
        text="Good night.",
        language="en",
        recorder=recorder,
    )

    assert "/media/narration/" in audio_url
    assert audio_url.endswith(".mp3")
    token = audio_url.rsplit("/", 1)[-1].removesuffix(".mp3")
    assert narration_storage.read_narration_mp3(token) == b"ID3audio"
    assert recorder.calls == [
        {
            "stage": "tts",
            "provider": "elevenlabs",
            "model": "model-test",
            "attempt": 1,
            "outcome": "succeeded",
            "usage": (Usage("character", 13),),
            "page_number": None,
        }
    ]


def test_generate_narration_records_elevenlabs_transport_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(side_effect=httpx.ConnectError("provider unavailable")),
    )
    recorder = Recorder()

    with pytest.raises(narration_providers.NarrationProviderRequestError):
        narration.generate_narration(
            text="Good night.",
            language="en",
            recorder=recorder,
        )

    assert recorder.calls[0]["provider"] == "elevenlabs"
    assert recorder.calls[0]["model"] == "model-test"
    assert recorder.calls[0]["outcome"] == "provider_failure"
    assert recorder.calls[0]["usage"] is None


def test_generate_narration_records_empty_elevenlabs_audio_as_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    response = MagicMock(content=b"")
    response.headers = {
        "content-type": "audio/mpeg",
        "character-cost": "12",
    }
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(return_value=response),
    )
    recorder = Recorder()

    with pytest.raises(
        narration_providers.InvalidNarrationProviderResponse
    ):
        narration.generate_narration(
            text="Good night.",
            language="en",
            recorder=recorder,
        )

    assert recorder.calls[0]["outcome"] == "invalid_response"
    assert recorder.calls[0]["usage"] == (Usage("character", 12),)


def test_generate_narration_does_not_record_a_disabled_paid_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "paid_tts_enabled", False)
    post = MagicMock()
    monkeypatch.setattr(narration_providers, "_post", post)
    recorder = Recorder()

    with pytest.raises(narration_providers.PaidNarrationDisabledError):
        narration.generate_narration(
            text="Good night.",
            language="en",
            recorder=recorder,
        )

    post.assert_not_called()
    assert recorder.calls == []


def test_generate_narration_keeps_provider_cost_when_storage_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    response = MagicMock(content=b"ID3audio")
    response.headers = {
        "content-type": "audio/mpeg",
        "character-cost": "15",
    }
    monkeypatch.setattr(
        narration_providers,
        "_post",
        MagicMock(return_value=response),
    )
    monkeypatch.setattr(
        narration_storage,
        "store_narration_mp3",
        MagicMock(side_effect=OSError("disk unavailable")),
    )
    recorder = Recorder()

    with pytest.raises(OSError, match="disk unavailable"):
        narration.generate_narration(
            text="Good night.",
            language="en",
            recorder=recorder,
        )

    assert recorder.calls[0]["outcome"] == "succeeded"
    assert recorder.calls[0]["usage"] == (Usage("character", 15),)
