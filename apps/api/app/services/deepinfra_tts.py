"""DeepInfra Kokoro narration provider boundary."""

from __future__ import annotations

import base64
import binascii
from urllib.parse import quote

import httpx

from app.services.cost_tracking import Usage
from app.services.narration_providers import (
    InvalidNarrationProviderResponse,
    NarrationProviderRequest,
    NarrationProviderRequestError,
    NarrationProviderResponse,
    PaidNarrationDisabledError,
)


MAX_RESPONSE_BYTES = 20 * 1024 * 1024


def _post(
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, object],
    timeout: float,
    follow_redirects: bool,
) -> httpx.Response:
    """Keep hosted DeepInfra TTS HTTP behind one testable boundary."""
    return httpx.post(
        url,
        headers=headers,
        json=json,
        timeout=timeout,
        follow_redirects=follow_redirects,
    )


def _looks_like_mp3(audio: bytes) -> bool:
    if len(audio) >= 10 and audio.startswith(b"ID3"):
        return True
    if len(audio) < 4 or audio[0] != 0xFF or audio[1] & 0xE0 != 0xE0:
        return False
    version_bits = audio[1] & 0x18
    layer_bits = audio[1] & 0x06
    bitrate_index = audio[2] >> 4
    return (
        version_bits != 0x08
        and layer_bits != 0
        and bitrate_index not in {0, 0x0F}
    )


def _provider_error_code(response: httpx.Response) -> int | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first_error = errors[0]
    if not isinstance(first_error, dict):
        return None
    code = first_error.get("code")
    if not isinstance(code, int) or isinstance(code, bool):
        return None
    return code


def _decode_audio(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    encoded = value.strip()
    if encoded.startswith("data:"):
        header, separator, encoded = encoded.partition(",")
        if (
            not separator
            or header.lower()
            not in {"data:audio/mpeg;base64", "data:audio/mp3;base64"}
        ):
            return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _response_payload(response: httpx.Response) -> dict[str, object] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


class DeepInfraNarrationProvider:
    def __init__(
        self,
        *,
        api_token: str | None,
        base_url: str,
        model: str,
        en_voice: str,
        fr_voice: str,
        speed: float,
        timeout_seconds: float,
        paid_calls_enabled: bool,
    ) -> None:
        if not paid_calls_enabled:
            raise PaidNarrationDisabledError(
                "Paid narration calls are disabled."
            )
        if api_token is None or not api_token.strip():
            raise ValueError("DeepInfra API token is required.")
        if not base_url.strip():
            raise ValueError("DeepInfra base URL is required.")
        if not model.strip():
            raise ValueError("DeepInfra TTS model is required.")
        if not en_voice.strip():
            raise ValueError("DeepInfra English voice is required.")
        if not fr_voice.strip():
            raise ValueError("DeepInfra French voice is required.")
        if not 0.25 <= speed <= 4:
            raise ValueError("DeepInfra TTS speed is out of range.")
        if timeout_seconds <= 0:
            raise ValueError("DeepInfra TTS timeout must be positive.")

        self._api_token = api_token.strip()
        self._base_url = base_url.rstrip("/")
        self.model = model.strip()
        self._voices = {
            "en": en_voice.strip(),
            "fr": fr_voice.strip(),
        }
        self._speed = speed
        self._timeout_seconds = timeout_seconds

    def _endpoint(self) -> str:
        model = quote(self.model, safe="/@-_.")
        return f"{self._base_url}/inference/{model}"

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 300:
            return
        raise NarrationProviderRequestError(
            provider="deepinfra",
            model=self.model,
            usage=None,
            transient=status in {408, 429} or status >= 500,
            provider_code=_provider_error_code(response),
        ) from None

    def generate(
        self,
        request: NarrationProviderRequest,
    ) -> NarrationProviderResponse:
        if not request.text.strip():
            raise ValueError("Narration text cannot be empty.")
        voice = self._voices.get(request.language)
        if voice is None:
            raise ValueError("Unsupported narration language.")

        try:
            response = _post(
                self._endpoint(),
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "text": request.text,
                    "output_format": "mp3",
                    "preset_voice": [voice],
                    "speed": self._speed,
                    "stream": False,
                    "return_timestamps": False,
                },
                timeout=self._timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TransportError:
            raise NarrationProviderRequestError(
                provider="deepinfra",
                model=self.model,
                usage=None,
                transient=True,
            ) from None

        self._raise_for_status(response)
        fallback_characters = len(request.text)
        usage = (Usage("character", fallback_characters),)
        payload = (
            None
            if len(response.content) > MAX_RESPONSE_BYTES
            else _response_payload(response)
        )
        if payload is not None:
            raw_characters = payload.get("input_character_length")
            if (
                isinstance(raw_characters, int)
                and not isinstance(raw_characters, bool)
                and raw_characters > 0
            ):
                usage = (Usage("character", raw_characters),)
            audio_bytes = _decode_audio(payload.get("audio"))
        else:
            audio_bytes = None
        if audio_bytes is None or not _looks_like_mp3(audio_bytes):
            raise InvalidNarrationProviderResponse(
                provider="deepinfra",
                model=self.model,
                usage=usage,
            ) from None

        return NarrationProviderResponse(
            audio_bytes=audio_bytes,
            content_type="audio/mpeg",
            provider="deepinfra",
            model=self.model,
            usage=usage,
        )
