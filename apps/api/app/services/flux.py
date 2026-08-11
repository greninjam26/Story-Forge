"""Client boundary for the Black Forest Labs FLUX image API."""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx


class FluxError(RuntimeError):
    pass


class FluxTransientError(FluxError):
    pass


class FluxPermanentError(FluxError):
    pass


class FluxModerationError(FluxPermanentError):
    pass


@dataclass(frozen=True, slots=True)
class FluxSubmission:
    id: str
    polling_url: str
    cost_credits: Decimal | None


def _new_http_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=False)


class FluxClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        request_timeout: float = 30,
        poll_timeout: float = 60,
        poll_interval: float = 0.5,
        max_download_bytes: int = 20 * 1024 * 1024,
        trusted_result_host_suffixes: tuple[str, ...] = ("bfl.ai",),
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_download_bytes < 1:
            raise ValueError("max_download_bytes must be positive")
        if not trusted_result_host_suffixes:
            raise ValueError(
                "trusted_result_host_suffixes must not be empty"
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._poll_timeout = poll_timeout
        self._poll_interval = poll_interval
        self._max_download_bytes = max_download_bytes
        self._trusted_result_host_suffixes = tuple(
            suffix.lower().lstrip(".")
            for suffix in trusted_result_host_suffixes
        )
        self._client = http_client or _new_http_client(request_timeout)
        self._owns_client = http_client is None
        self._sleep = sleep
        self._monotonic = monotonic

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FluxClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if 300 <= response.status_code < 400:
            raise FluxPermanentError(
                "illustration service returned an unsafe redirect"
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise FluxTransientError(
                "illustration service is temporarily unavailable"
            )
        if response.status_code >= 400:
            raise FluxPermanentError("illustration request was rejected")

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, object]:
        try:
            value = response.json()
        except ValueError as exc:
            raise FluxPermanentError(
                "illustration service returned a malformed response"
            ) from exc
        if not isinstance(value, dict):
            raise FluxPermanentError(
                "illustration service returned a malformed response"
            )
        return value

    def _request(
        self,
        method: str,
        url: str,
        *,
        authenticated: bool,
        **kwargs: object,
    ) -> httpx.Response:
        raw_headers = kwargs.pop("headers", {})
        headers = dict(raw_headers) if isinstance(raw_headers, dict) else {}
        headers["accept"] = "application/json"
        if authenticated:
            headers["x-key"] = self._api_key
        try:
            response = self._client.request(
                method,
                url,
                headers=headers,
                follow_redirects=False,
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise FluxTransientError(
                "illustration service is temporarily unavailable"
            ) from exc
        self._raise_for_status(response)
        return response

    def submit(self, prompt: str, input_image: bytes) -> FluxSubmission:
        response = self._request(
            "POST",
            f"{self._base_url}/{self._model}",
            authenticated=True,
            json={
                "prompt": prompt,
                "input_image": base64.b64encode(input_image).decode("ascii"),
                "width": 1024,
                "height": 768,
                "output_format": "webp",
            },
        )
        payload = self._json_object(response)
        request_id = payload.get("id")
        polling_url = payload.get("polling_url")
        if not isinstance(request_id, str) or not isinstance(polling_url, str):
            raise FluxPermanentError(
                "illustration service returned a malformed response"
            )
        raw_cost = payload.get("cost")
        try:
            cost = Decimal(str(raw_cost)) if raw_cost is not None else None
        except InvalidOperation as exc:
            raise FluxPermanentError(
                "illustration service returned a malformed response"
            ) from exc
        if cost is not None and (not cost.is_finite() or cost < 0):
            raise FluxPermanentError(
                "illustration service returned a malformed response"
            )
        return FluxSubmission(
            id=request_id,
            polling_url=polling_url,
            cost_credits=cost,
        )

    def wait_for_result(self, submission: FluxSubmission) -> str:
        try:
            expected = urlparse(self._base_url)
            actual = urlparse(submission.polling_url)
            expected_origin = (
                expected.scheme,
                expected.hostname,
                expected.port,
            )
            actual_origin = (
                actual.scheme,
                actual.hostname,
                actual.port,
            )
        except (UnicodeError, ValueError):
            raise FluxPermanentError(
                "illustration service returned an invalid polling URL"
            ) from None
        if (
            actual.scheme != "https"
            or actual_origin != expected_origin
            or actual.username is not None
            or actual.password is not None
        ):
            raise FluxPermanentError(
                "illustration service returned an invalid polling URL"
            )

        deadline = self._monotonic() + self._poll_timeout
        while True:
            response = self._request(
                "GET",
                submission.polling_url,
                authenticated=True,
            )
            payload = self._json_object(response)
            status = payload.get("status")
            if status == "Ready":
                result = payload.get("result")
                sample = (
                    result.get("sample")
                    if isinstance(result, dict)
                    else None
                )
                if not isinstance(sample, str):
                    raise FluxPermanentError(
                        "illustration service returned a malformed response"
                    )
                return sample
            if status in {"Request Moderated", "Content Moderated"}:
                raise FluxModerationError(
                    "illustration was rejected by provider safety checks"
                )
            if status in {"Error", "Failed", "Task not found"}:
                raise FluxTransientError(
                    "illustration service is temporarily unavailable"
                )
            if status != "Pending":
                raise FluxPermanentError(
                    "illustration service returned a malformed response"
                )
            if self._monotonic() >= deadline:
                raise FluxTransientError("illustration generation timed out")
            self._sleep(self._poll_interval)

    def download(self, url: str) -> bytes:
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname.lower() if parsed.hostname else None
            port = parsed.port
        except (UnicodeError, ValueError):
            raise FluxPermanentError(
                "illustration service returned an invalid result URL"
            ) from None
        trusted_host = bool(hostname) and any(
            hostname == suffix or hostname.endswith(f".{suffix}")
            for suffix in self._trusted_result_host_suffixes
        )
        if (
            parsed.scheme != "https"
            or not trusted_host
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise FluxPermanentError(
                "illustration service returned an invalid result URL"
            )

        try:
            with self._client.stream(
                "GET",
                url,
                headers={"accept": "image/*"},
                follow_redirects=False,
            ) as response:
                self._raise_for_status(response)
                content_length = response.headers.get("content-length")
                if (
                    content_length is not None
                    and content_length.isdigit()
                    and int(content_length) > self._max_download_bytes
                ):
                    raise FluxPermanentError(
                        "illustration service result was too large"
                    )

                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > self._max_download_bytes:
                        raise FluxPermanentError(
                            "illustration service result was too large"
                        )
                    data.extend(chunk)
        except FluxError:
            raise
        except httpx.TransportError as exc:
            raise FluxTransientError(
                "illustration service is temporarily unavailable"
            ) from exc
        return bytes(data)
