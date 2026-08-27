"""Cloudflare Workers AI MeloTTS provider boundary."""

from __future__ import annotations

import base64
import binascii
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx

from app.services.cost_tracking import Usage
from app.services.narration_providers import (
    InvalidNarrationProviderResponse,
    NarrationProviderRequest,
    NarrationProviderRequestError,
    NarrationProviderResponse,
)


def _post(
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, str],
    timeout: float,
    follow_redirects: bool,
) -> httpx.Response:
    """Keep hosted Cloudflare TTS HTTP behind one testable boundary."""
    return httpx.post(
        url,
        headers=headers,
        json=json,
        timeout=timeout,
        follow_redirects=follow_redirects,
    )


def _media_type(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    return content_type.partition(";")[0].strip().lower()


def _neuron_usage(response: httpx.Response) -> tuple[Usage, ...] | None:
    raw_neurons = response.headers.get("cf-ai-neurons")
    if not isinstance(raw_neurons, str):
        return None
    try:
        neurons = Decimal(raw_neurons.strip())
    except InvalidOperation:
        return None
    if not neurons.is_finite() or neurons < 0:
        return None
    millineurons = neurons * Decimal("1000")
    if millineurons != millineurons.to_integral_value():
        return None
    return (Usage("millineuron", int(millineurons)),)


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


class CloudflareNarrationProvider:
    def __init__(
        self,
        *,
        account_id: str | None,
        api_token: str | None,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        if account_id is None or not account_id.strip():
            raise ValueError("Cloudflare account ID is required.")
        if api_token is None or not api_token.strip():
            raise ValueError("Cloudflare API token is required.")
        if not base_url.strip():
            raise ValueError("Cloudflare base URL is required.")
        if not model.strip():
            raise ValueError("Cloudflare TTS model is required.")
        if timeout_seconds <= 0:
            raise ValueError("Cloudflare TTS timeout must be positive.")

        self._account_id = account_id.strip()
        self._api_token = api_token.strip()
        self._base_url = base_url.rstrip("/")
        self.model = model.strip()
        self._timeout_seconds = timeout_seconds

    def _endpoint(self) -> str:
        account_id = quote(self._account_id, safe="")
        model = quote(self.model, safe="/@-_.")
        return f"{self._base_url}/accounts/{account_id}/ai/run/{model}"

    def _raise_for_status(
        self,
        response: httpx.Response,
        usage: tuple[Usage, ...] | None,
    ) -> None:
        status = response.status_code
        if status < 300:
            return
        provider_code = _provider_error_code(response)
        transient = (
            status == 408
            or status >= 500
            or (status == 429 and provider_code != 3036)
        )
        raise NarrationProviderRequestError(
            provider="cloudflare",
            model=self.model,
            usage=usage,
            transient=transient,
            provider_code=provider_code,
        ) from None

    def generate(
        self,
        request: NarrationProviderRequest,
    ) -> NarrationProviderResponse:
        if not request.text.strip():
            raise ValueError("Narration text cannot be empty.")

        try:
            response = _post(
                self._endpoint(),
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": request.text,
                    "lang": request.language,
                },
                timeout=self._timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TransportError:
            raise NarrationProviderRequestError(
                provider="cloudflare",
                model=self.model,
                usage=None,
                transient=True,
            ) from None

        usage = _neuron_usage(response)
        self._raise_for_status(response, usage)
        if _media_type(response) != "application/json":
            raise InvalidNarrationProviderResponse(
                provider="cloudflare",
                model=self.model,
                usage=usage,
            )
        try:
            payload = response.json()
        except ValueError:
            raise InvalidNarrationProviderResponse(
                provider="cloudflare",
                model=self.model,
                usage=usage,
            ) from None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise InvalidNarrationProviderResponse(
                provider="cloudflare",
                model=self.model,
                usage=usage,
            )
        result = payload.get("result")
        encoded_audio = (
            result.get("audio") if isinstance(result, dict) else None
        )
        if not isinstance(encoded_audio, str) or not encoded_audio:
            raise InvalidNarrationProviderResponse(
                provider="cloudflare",
                model=self.model,
                usage=usage,
            )
        try:
            audio_bytes = base64.b64decode(encoded_audio, validate=True)
        except (ValueError, binascii.Error):
            raise InvalidNarrationProviderResponse(
                provider="cloudflare",
                model=self.model,
                usage=usage,
            ) from None
        if not _looks_like_mp3(audio_bytes):
            raise InvalidNarrationProviderResponse(
                provider="cloudflare",
                model=self.model,
                usage=usage,
            )
        return NarrationProviderResponse(
            audio_bytes=audio_bytes,
            content_type="audio/mpeg",
            provider="cloudflare",
            model=self.model,
            usage=usage,
        )
