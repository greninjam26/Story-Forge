from hashlib import sha256
from io import BytesIO
from math import pi, sin
from struct import pack
from typing import Protocol
from wave import open as open_wave

from app.config import settings
from app.schemas import StoryLanguage
from app.services.cost_tracking import (
    CostRecorder,
    NOOP_COST_RECORDER,
    Usage,
)


class NarrationProvider(Protocol):
    def generate(
        self,
        *,
        text: str,
        language: StoryLanguage,
    ) -> str: ...


class StubNarrationProvider:
    def generate(
        self,
        *,
        text: str,
        language: StoryLanguage,
    ) -> str:
        token = sha256(f"{language}\0{text}".encode()).hexdigest()[:16]
        api_base_url = settings.api_base_url.rstrip("/")
        return (
            f"{api_base_url}/media/placeholders/narration/"
            f"{language}/{token}.wav"
        )


_PROVIDERS: dict[str, NarrationProvider] = {
    "stub": StubNarrationProvider(),
}


def generate_placeholder_wav(token: str) -> bytes:
    sample_rate = 8_000
    sample_count = sample_rate // 2
    frequency = 220 + (int(token[:2], 16) % 8) * 20
    frames = bytearray()
    for sample_index in range(sample_count):
        fade = min(
            1.0,
            sample_index / 200,
            (sample_count - sample_index - 1) / 200,
        )
        sample = int(
            2_000
            * fade
            * sin(2 * pi * frequency * sample_index / sample_rate)
        )
        frames.extend(pack("<h", sample))

    output = BytesIO()
    with open_wave(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return output.getvalue()


def generate_narration(
    *,
    text: str,
    language: StoryLanguage,
    recorder: CostRecorder = NOOP_COST_RECORDER,
) -> str:
    provider_name = settings.tts_provider.strip().lower()
    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"Unsupported narration provider: {provider_name}")

    audio_url = provider.generate(text=text, language=language)
    recorder.record_call(
        stage="tts",
        provider=provider_name,
        model=None,
        attempt=1,
        outcome="succeeded",
        usage=(Usage("character", len(text)),),
    )
    return audio_url
