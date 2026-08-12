import json
import math
from collections.abc import Callable

import httpx
import pytest

from app.config import settings
from app.services import openai_moderation


def _result(
    *,
    flagged: bool = False,
    categories: dict[str, bool] | None = None,
    scores: dict[str, float] | None = None,
) -> dict:
    categories = categories or {"violence": False}
    return {
        "flagged": flagged,
        "categories": categories,
        "category_scores": scores or {
            name: 0.01 for name in categories
        },
    }


def _payload(
    *results: dict,
    model: object = "omni-moderation-latest",
) -> dict:
    return {"model": model, "results": list(results)}


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[float]:
    timeouts: list[float] = []

    def new_http_client(timeout: float) -> httpx.Client:
        timeouts.append(timeout)
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
        )

    monkeypatch.setattr(
        openai_moderation,
        "_new_http_client",
        new_http_client,
    )
    return timeouts


def test_moderate_batches_inputs_and_returns_validated_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")
    monkeypatch.setattr(
        settings,
        "openai_moderation_model",
        "omni-moderation-latest",
    )
    monkeypatch.setattr(
        settings,
        "openai_moderation_timeout_seconds",
        7.5,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == "https://api.openai.com/v1/moderations"
        assert request.headers["authorization"] == (
            "Bearer test-openai-key"
        )
        assert request.headers["accept"] == "application/json"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {
            "model": "omni-moderation-latest",
            "input": ["A Safe Title", "page one", "page two"],
        }
        return httpx.Response(
            200,
            headers={"x-request-id": "req_test_123"},
            json=_payload(
                _result(),
                _result(
                    flagged=True,
                    categories={"violence": True, "sexual": False},
                    scores={"violence": 0.91, "sexual": 0.03},
                ),
                _result(),
            ),
        )

    timeouts = _install_transport(monkeypatch, handler)

    response = openai_moderation.moderate(
        ["A Safe Title", "page one", "page two"]
    )

    assert timeouts == [7.5]
    assert response.model == "omni-moderation-latest"
    assert response.request_id == "req_test_123"
    assert len(response.results) == 3
    assert response.results[1].flagged is True
    assert response.results[1].categories == {
        "violence": True,
        "sexual": False,
    }
    assert response.results[1].category_scores["violence"] == 0.91


def test_moderate_rejects_empty_input_without_constructing_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openai_moderation,
        "_new_http_client",
        lambda _timeout: pytest.fail(
            "empty input must not construct a client"
        ),
    )

    with pytest.raises(
        openai_moderation.ModerationProviderError,
        match="invalid moderation request",
    ):
        openai_moderation.moderate([])


@pytest.mark.parametrize("api_key", [None, "", "  "])
def test_moderate_rejects_missing_key_without_constructing_client(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", api_key)
    monkeypatch.setattr(
        openai_moderation,
        "_new_http_client",
        lambda _timeout: pytest.fail(
            "missing key must not construct a client"
        ),
    )

    with pytest.raises(
        openai_moderation.ModerationProviderError,
        match="moderation service is not configured",
    ):
        openai_moderation.moderate(["title"])


@pytest.mark.parametrize("status_code", [301, 401, 429, 500])
def test_moderate_sanitizes_http_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            text="private provider response containing child text",
        )

    _install_transport(monkeypatch, handler)

    with pytest.raises(
        openai_moderation.ModerationProviderError,
        match="moderation service is unavailable",
    ) as error:
        openai_moderation.moderate(["private input"])

    assert "child text" not in str(error.value)
    assert "private input" not in str(error.value)


@pytest.mark.parametrize(
    "provider_error",
    [
        httpx.ReadTimeout("private timeout detail"),
        httpx.ConnectError("private transport detail"),
    ],
)
def test_moderate_sanitizes_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: httpx.TransportError,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise provider_error

    _install_transport(monkeypatch, handler)

    with pytest.raises(
        openai_moderation.ModerationProviderError,
        match="moderation service is unavailable",
    ) as error:
        openai_moderation.moderate(["private input"])

    assert "private" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_moderate_rejects_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "req_bad_json"},
            content=b"not-json private response",
        )

    _install_transport(monkeypatch, handler)

    with pytest.raises(
        openai_moderation.ModerationProviderError,
        match="malformed response",
    ) as error:
        openai_moderation.moderate(["private input"])

    assert "not-json" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    ("payload", "request_id"),
    [
        (_payload(_result(), model=None), "req_test"),
        (_payload(_result(), model=""), "req_test"),
        (_payload(_result()), None),
        (_payload(_result()), ""),
        ({"model": "omni-moderation-latest"}, "req_test"),
        (_payload(), "req_test"),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
                "category_scores": {"sexual": 0.1},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": 1,
                "categories": {"violence": False},
                "category_scores": {"violence": 0.1},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": 0},
                "category_scores": {"violence": 0.1},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
                "category_scores": {"violence": True},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
                "category_scores": {"violence": "0.1"},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
                "category_scores": {"violence": -0.01},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
                "category_scores": {"violence": 1.01},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
                "category_scores": {"violence": math.nan},
            }),
            "req_test",
        ),
        (
            _payload({
                "flagged": False,
                "categories": {"violence": False},
                "category_scores": {"violence": math.inf},
            }),
            "req_test",
        ),
    ],
)
def test_moderate_rejects_malformed_provider_data(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    request_id: str | None,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        headers = {"x-request-id": request_id} if request_id else {}
        return httpx.Response(
            200,
            headers=headers,
            content=json.dumps(payload).encode(),
        )

    _install_transport(monkeypatch, handler)

    with pytest.raises(
        openai_moderation.ModerationProviderError,
        match="malformed response",
    ):
        openai_moderation.moderate(["title"])


def test_moderate_rejects_result_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "req_wrong_count"},
            json=_payload(_result()),
        )

    _install_transport(monkeypatch, handler)

    with pytest.raises(
        openai_moderation.ModerationProviderError,
        match="malformed response",
    ):
        openai_moderation.moderate(["title", "page one"])


def test_openai_moderation_access_is_forbidden_in_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "would-be-real-key")

    with pytest.raises(
        AssertionError,
        match="OpenAI moderation access is forbidden in tests",
    ):
        openai_moderation.moderate(["safe text"])
