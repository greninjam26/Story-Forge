import base64
import json
from decimal import Decimal

import httpx
import pytest

from app.services import flux
from app.services.flux import (
    FluxClient,
    FluxModerationError,
    FluxPermanentError,
    FluxSubmission,
    FluxTransientError,
)


def test_paid_image_provider_access_is_forbidden_in_tests() -> None:
    with pytest.raises(
        AssertionError,
        match="paid image provider access is forbidden in tests",
    ):
        FluxClient(
            api_key="would-be-real-key",
            base_url="https://api.bfl.ai/v1",
            model="flux-2-klein-9b",
        )


def test_submit_sends_reference_image_and_returns_provider_cost() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-key")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "job-1",
                "polling_url": (
                    "https://api.test/v1/get_result?id=job-1"
                ),
                "cost": "1.5",
            },
        )

    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    submission = client.submit("watercolor scene", b"reference")

    assert submission.id == "job-1"
    assert submission.polling_url == (
        "https://api.test/v1/get_result?id=job-1"
    )
    assert submission.cost_credits == Decimal("1.5")
    assert seen["url"] == "https://api.test/v1/flux-2-klein-9b"
    assert seen["api_key"] == "test-key"
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["prompt"] == "watercolor scene"
    assert payload["width"] == 1024
    assert payload["height"] == 768
    assert payload["output_format"] == "webp"
    assert base64.b64decode(payload["input_image"]) == b"reference"


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_submit_classifies_retryable_failures_as_transient(
    status_code: int,
) -> None:
    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(status_code)
            )
        ),
    )

    with pytest.raises(FluxTransientError, match="temporarily unavailable"):
        client.submit("scene", b"reference")


@pytest.mark.parametrize("status_code", [400, 401, 403, 422])
def test_submit_classifies_rejected_requests_as_permanent(
    status_code: int,
) -> None:
    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(status_code)
            )
        ),
    )

    with pytest.raises(FluxPermanentError, match="request was rejected"):
        client.submit("scene", b"reference")


@pytest.mark.parametrize("cost", ["NaN", "Infinity", "-1"])
def test_submit_rejects_invalid_provider_cost(cost: str) -> None:
    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={
                        "id": "job-1",
                        "polling_url": (
                            "https://api.test/v1/get_result?id=job-1"
                        ),
                        "cost": cost,
                    },
                )
            )
        ),
    )

    with pytest.raises(FluxPermanentError, match="malformed response"):
        client.submit("scene", b"reference")


def test_wait_for_result_polls_until_ready() -> None:
    statuses = iter(
        [
            {"status": "Pending"},
            {
                "status": "Ready",
                "result": {"sample": "https://cdn.test/result.webp"},
            },
        ]
    )
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-key"] == "test-key"
        return httpx.Response(200, json=next(statuses))

    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )
    submission = FluxSubmission(
        id="job-1",
        polling_url="https://api.test/v1/get_result?id=job-1",
        cost_credits=Decimal("1.5"),
    )

    result_url = client.wait_for_result(submission)

    assert result_url == "https://cdn.test/result.webp"
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    "provider_status",
    ["Request Moderated", "Content Moderated"],
)
def test_wait_for_result_classifies_moderation(
    provider_status: str,
) -> None:
    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"status": provider_status},
                )
            )
        ),
    )
    submission = FluxSubmission(
        id="job-1",
        polling_url="https://api.test/v1/get_result?id=job-1",
        cost_credits=None,
    )

    with pytest.raises(FluxModerationError, match="safety checks"):
        client.wait_for_result(submission)


def test_wait_for_result_times_out_without_real_sleep() -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"status": "Pending"},
                )
            )
        ),
        poll_timeout=1,
        sleep=sleep,
        monotonic=lambda: now[0],
    )
    submission = FluxSubmission(
        id="job-1",
        polling_url="https://api.test/v1/get_result?id=job-1",
        cost_credits=None,
    )

    with pytest.raises(FluxTransientError, match="timed out"):
        client.wait_for_result(submission)


def test_wait_for_result_rejects_untrusted_polling_origin() -> None:
    requested: list[httpx.Request] = []
    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requested.append(request)
                or httpx.Response(200)
            )
        ),
    )
    submission = FluxSubmission(
        id="job-1",
        polling_url="https://attacker.test/steal-key",
        cost_credits=None,
    )

    with pytest.raises(FluxPermanentError, match="invalid polling URL"):
        client.wait_for_result(submission)

    assert requested == []


def test_download_accepts_trusted_host_without_sending_api_key() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, content=b"webp")

    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        trusted_result_host_suffixes=("cdn.test",),
    )

    data = client.download(
        "https://temporary.cdn.test/result.webp?signature=test"
    )

    assert data == b"webp"
    assert "x-key" not in seen_headers


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.test/result.webp",
        "https://user:secret@cdn.test/result.webp",
        "https://attacker.test/result.webp",
        "https://cdn.test:8443/result.webp",
    ],
)
def test_download_rejects_untrusted_result_url(url: str) -> None:
    requested: list[httpx.Request] = []
    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requested.append(request)
                or httpx.Response(200)
            )
        ),
        trusted_result_host_suffixes=("cdn.test",),
    )

    with pytest.raises(FluxPermanentError, match="invalid result URL"):
        client.download(url)

    assert requested == []


@pytest.mark.parametrize("headers", [{"content-length": "5"}, {}])
def test_download_rejects_result_larger_than_byte_limit(
    headers: dict[str, str],
) -> None:
    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers=headers,
                    content=b"12345",
                )
            )
        ),
        trusted_result_host_suffixes=("cdn.test",),
        max_download_bytes=4,
    )

    with pytest.raises(FluxPermanentError, match="too large"):
        client.download("https://cdn.test/result.webp")


def test_transport_failure_is_sanitized_as_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(
            "secret provider detail",
            request=request,
        )

    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(FluxTransientError, match="temporarily unavailable"):
        client.submit("scene", b"reference")


def test_submit_rejects_redirect_without_forwarding_api_key() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("x-key")))
        if request.url.host == "api.test":
            return httpx.Response(
                307,
                headers={"location": "https://attacker.test/steal-key"},
            )
        return httpx.Response(200, json={})

    client = FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ),
    )

    with pytest.raises(FluxPermanentError, match="unsafe redirect"):
        client.submit("scene", b"reference")

    assert seen == [
        ("https://api.test/v1/flux-2-klein-9b", "test-key"),
    ]


def test_context_manager_closes_owned_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200)
        )
    )
    monkeypatch.setattr(
        flux,
        "_new_http_client",
        lambda _timeout: owned_client,
        raising=False,
    )

    with FluxClient(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="flux-2-klein-9b",
        request_timeout=12,
    ):
        pass

    assert owned_client.is_closed
