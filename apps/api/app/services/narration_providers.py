from dataclasses import dataclass

import httpx

from app.schemas import StoryLanguage
from app.services.cost_tracking import Usage


def _post(
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, str],
    params: dict[str, str],
    timeout: float,
) -> httpx.Response:
    """Keep paid narration HTTP behind one testable boundary."""
    return httpx.post(
        url,
        headers=headers,
        json=json,
        params=params,
        timeout=timeout,
    )


def _character_usage(
    response: httpx.Response,
) -> tuple[Usage, ...] | None:
    raw_cost = response.headers.get("character-cost")
    if not isinstance(raw_cost, str):
        return None
    try:
        character_cost = int(raw_cost.strip())
    except ValueError:
        return None
    if character_cost < 0:
        return None
    return (Usage("character", character_cost),)


@dataclass(frozen=True, slots=True)
class NarrationProviderRequest:
    text: str
    language: StoryLanguage


@dataclass(frozen=True, slots=True)
class NarrationProviderResponse:
    audio_bytes: bytes
    content_type: str
    provider: str
    model: str | None
    usage: tuple[Usage, ...] | None


class PaidNarrationDisabledError(RuntimeError):
    pass


class NarrationProviderError(Exception):
    def __init__(
        self,
        *,
        message: str,
        provider: str,
        model: str | None,
        usage: tuple[Usage, ...] | None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.usage = usage


class NarrationProviderRequestError(NarrationProviderError):
    def __init__(self, *, model: str | None) -> None:
        super().__init__(
            message="Narration provider request failed.",
            provider="elevenlabs",
            model=model,
            usage=None,
        )


class InvalidNarrationProviderResponse(NarrationProviderError):
    def __init__(
        self,
        *,
        model: str | None,
        usage: tuple[Usage, ...] | None,
    ) -> None:
        super().__init__(
            message="Narration provider returned an invalid response.",
            provider="elevenlabs",
            model=model,
            usage=usage,
        )


class ElevenLabsNarrationProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        voice_id: str | None,
        model: str,
        base_url: str,
        timeout_seconds: float,
        paid_calls_enabled: bool,
    ) -> None:
        if not paid_calls_enabled:
            raise PaidNarrationDisabledError(
                "Paid narration calls are disabled."
            )
        if api_key is None or not api_key.strip():
            raise ValueError("ElevenLabs API key is required.")
        if voice_id is None or not voice_id.strip():
            raise ValueError("ElevenLabs voice ID is required.")

        self._api_key = api_key.strip()
        self._voice_id = voice_id.strip()
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def generate(
        self,
        request: NarrationProviderRequest,
    ) -> NarrationProviderResponse:
        if not request.text.strip():
            raise ValueError("Narration text cannot be empty.")

        try:
            response = _post(
                f"{self._base_url}/text-to-speech/{self._voice_id}",
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": request.text,
                    "model_id": self.model,
                    "language_code": request.language,
                },
                params={"output_format": "mp3_44100_128"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise NarrationProviderRequestError(model=self.model) from None
        usage = _character_usage(response)
        content_type = response.headers.get("content-type", "")
        media_type = content_type.partition(";")[0].strip().lower()
        if not response.content or media_type != "audio/mpeg":
            raise InvalidNarrationProviderResponse(
                model=self.model,
                usage=usage,
            )
        return NarrationProviderResponse(
            audio_bytes=response.content,
            content_type="audio/mpeg",
            provider="elevenlabs",
            model=self.model,
            usage=usage,
        )
