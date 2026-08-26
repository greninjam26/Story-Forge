"""Client boundary for Cloudflare Workers AI image generation."""

from __future__ import annotations

import base64
import binascii
from urllib.parse import quote

import httpx


class CloudflareAIError(RuntimeError):
    pass


class CloudflareAITransientError(CloudflareAIError):
    pass


class CloudflareAIPermanentError(CloudflareAIError):
    pass


def _new_http_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=False)


class CloudflareAIClient:
    def __init__(
        self,
        *,
        account_id: str,
        api_token: str,
        base_url: str,
        model: str,
        timeout: float = 120,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._account_id = account_id
        self._api_token = api_token
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = http_client or _new_http_client(timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CloudflareAIClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if 300 <= response.status_code < 400:
            raise CloudflareAIPermanentError(
                "illustration service returned an unsafe redirect"
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise CloudflareAITransientError(
                "illustration service is temporarily unavailable"
            )
        if response.status_code >= 400:
            raise CloudflareAIPermanentError(
                "illustration request was rejected"
            )

    def _endpoint(self) -> str:
        account_id = quote(self._account_id, safe="")
        model = quote(self._model, safe="/@-_.")
        return (
            f"{self._base_url}/accounts/{account_id}/ai/run/{model}"
        )

    def generate(self, prompt: str, input_image: bytes) -> bytes:
        response: httpx.Response | None = None
        try:
            response = self._client.post(
                self._endpoint(),
                headers={
                    "accept": "application/json",
                    "authorization": f"Bearer {self._api_token}",
                },
                data={
                    "prompt": prompt,
                    "width": "1024",
                    "height": "768",
                },
                files={
                    "input_image_0": (
                        "reference.webp",
                        input_image,
                        "image/webp",
                    )
                },
                follow_redirects=False,
            )
        except httpx.TransportError:
            pass
        if response is None:
            raise CloudflareAITransientError(
                "illustration service is temporarily unavailable"
            )
        self._raise_for_status(response)

        payload: object | None = None
        try:
            payload = response.json()
        except ValueError:
            pass
        if not isinstance(payload, dict):
            raise CloudflareAIPermanentError(
                "illustration service returned a malformed response"
            )
        if payload.get("success") is not True:
            raise CloudflareAIPermanentError(
                "illustration request was rejected"
            )
        result = payload.get("result")
        encoded_image = (
            result.get("image") if isinstance(result, dict) else None
        )
        if not isinstance(encoded_image, str) or not encoded_image:
            raise CloudflareAIPermanentError(
                "illustration service returned a malformed response"
            )
        image: bytes | None = None
        try:
            image = base64.b64decode(encoded_image, validate=True)
        except (ValueError, binascii.Error):
            pass
        if not image:
            raise CloudflareAIPermanentError(
                "illustration service returned a malformed response"
            )
        return image
