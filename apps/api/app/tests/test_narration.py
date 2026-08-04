from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import settings
from app.services import narration, narration_providers, narration_storage
from app.services.cost_tracking import Usage


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_call(self, **call: object) -> None:
        self.calls.append(call)


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


def test_generate_narration_uses_elevenlabs_and_stores_mp3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    response = MagicMock(content=b"ID3audio")
    monkeypatch.setattr(
        narration_providers.httpx,
        "post",
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
            "usage": (Usage("character", 11),),
            "page_number": None,
        }
    ]


def test_generate_narration_records_elevenlabs_transport_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        narration_providers.httpx,
        "post",
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
    monkeypatch.setattr(
        narration_providers.httpx,
        "post",
        MagicMock(return_value=MagicMock(content=b"")),
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
    assert recorder.calls[0]["usage"] == (Usage("character", 11),)


def test_generate_narration_does_not_record_a_disabled_paid_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_elevenlabs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "paid_tts_enabled", False)
    post = MagicMock()
    monkeypatch.setattr(narration_providers.httpx, "post", post)
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
    monkeypatch.setattr(
        narration_providers.httpx,
        "post",
        MagicMock(return_value=MagicMock(content=b"ID3audio")),
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
    assert recorder.calls[0]["usage"] == (Usage("character", 11),)
