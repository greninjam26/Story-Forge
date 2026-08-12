"""Small, injectable client for OpenAI's generated-text moderation API."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from app.config import settings

MODERATIONS_URL = "https://api.openai.com/v1/moderations"


class ModerationProviderError(RuntimeError):
    """A sanitized moderation configuration, transport, or protocol failure."""


@dataclass(frozen=True)
class ModerationResult:
    flagged: bool
    categories: dict[str, bool]
    category_scores: dict[str, float]


@dataclass(frozen=True)
class ModerationResponse:
    request_id: str
    model: str
    results: tuple[ModerationResult, ...]


def _new_http_client(timeout: float) -> httpx.Client:
    """Production seam replaced with a fake transport in automated tests."""
    return httpx.Client(timeout=timeout, follow_redirects=False)


def _malformed() -> ModerationProviderError:
    return ModerationProviderError(
        "moderation service returned a malformed response"
    )


def _result(value: object) -> ModerationResult:
    if not isinstance(value, dict):
        raise _malformed()

    flagged = value.get("flagged")
    categories = value.get("categories")
    category_scores = value.get("category_scores")
    if (
        type(flagged) is not bool
        or not isinstance(categories, dict)
        or not isinstance(category_scores, dict)
        or set(categories) != set(category_scores)
        or any(not isinstance(name, str) for name in categories)
        or any(
            type(category) is not bool
            for category in categories.values()
        )
    ):
        raise _malformed()

    scores: dict[str, float] = {}
    for name, score in category_scores.items():
        if type(score) not in {int, float}:
            raise _malformed()
        normalized = float(score)
        if not math.isfinite(normalized) or not 0 <= normalized <= 1:
            raise _malformed()
        scores[name] = normalized

    return ModerationResult(
        flagged=flagged,
        categories=categories.copy(),
        category_scores=scores,
    )


def moderate(inputs: Sequence[str]) -> ModerationResponse:
    """Return validated provider metadata and one result per input."""
    submitted = list(inputs)
    if not submitted:
        raise ModerationProviderError("invalid moderation request")

    api_key = settings.openai_api_key
    if not api_key or not api_key.strip():
        raise ModerationProviderError(
            "moderation service is not configured"
        )

    response: httpx.Response | None = None
    try:
        with _new_http_client(
            settings.openai_moderation_timeout_seconds
        ) as client:
            response = client.post(
                MODERATIONS_URL,
                headers={
                    "authorization": f"Bearer {api_key}",
                    "accept": "application/json",
                },
                json={
                    "model": settings.openai_moderation_model,
                    "input": submitted,
                },
            )
    except httpx.TransportError:
        pass

    # Raise outside the except block so the private request and its child text
    # are not retained as exception context by logging or monitoring tools.
    if response is None:
        raise ModerationProviderError("moderation service is unavailable")

    if response.status_code >= 300:
        raise ModerationProviderError("moderation service is unavailable")

    malformed_json = False
    try:
        payload = response.json()
    except ValueError:
        malformed_json = True
        payload = None
    # JSON decoding errors retain the private response document as context.
    if malformed_json:
        raise _malformed()
    if not isinstance(payload, dict):
        raise _malformed()

    request_id = response.headers.get("x-request-id")
    model = payload.get("model")
    results = payload.get("results")
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or not isinstance(model, str)
        or not model.strip()
        or not isinstance(results, list)
        or len(results) != len(submitted)
    ):
        raise _malformed()

    return ModerationResponse(
        request_id=request_id,
        model=model,
        results=tuple(_result(result) for result in results),
    )
