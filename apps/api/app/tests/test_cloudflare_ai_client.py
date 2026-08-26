import base64

import httpx
import pytest

from app.services.cloudflare_ai import (
    CloudflareAIClient,
    CloudflareAIPermanentError,
    CloudflareAITransientError,
)


def _client(handler: httpx.MockTransport) -> CloudflareAIClient:
    return CloudflareAIClient(
        account_id="account-123",
        api_token="secret-token",
        base_url="https://api.test/client/v4",
        model="@cf/black-forest-labs/flux-2-klein-4b",
        http_client=httpx.Client(transport=handler),
    )


def test_generate_sends_authenticated_multipart_request_and_decodes_image(
) -> None:
    seen: dict[str, object] = {}
    generated = b"generated-image"

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type")
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "result": {
                    "image": base64.b64encode(generated).decode("ascii")
                },
                "success": True,
                "errors": [],
                "messages": [],
            },
        )

    result = _client(httpx.MockTransport(handler)).generate(
        "watercolor garden",
        b"reference-webp",
    )

    assert result == generated
    assert seen["url"] == (
        "https://api.test/client/v4/accounts/account-123/ai/run/"
        "@cf/black-forest-labs/flux-2-klein-4b"
    )
    assert seen["authorization"] == "Bearer secret-token"
    assert str(seen["content_type"]).startswith("multipart/form-data;")
    body = bytes(seen["body"])
    assert b'name="prompt"' in body
    assert b"watercolor garden" in body
    assert b'name="input_image_0"' in body
    assert b'filename="reference.webp"' in body
    assert b"reference-webp" in body
    assert b'name="width"' in body and b"1024" in body
    assert b'name="height"' in body and b"768" in body


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_generate_classifies_retryable_statuses_as_transient(
    status_code: int,
) -> None:
    client = _client(
        httpx.MockTransport(
            lambda _request: httpx.Response(status_code, text="private")
        )
    )

    with pytest.raises(
        CloudflareAITransientError,
        match="temporarily unavailable",
    ) as captured:
        client.generate("private prompt", b"private reference")

    assert "private" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "secret-token" not in str(captured.value)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_generate_classifies_rejected_statuses_as_permanent(
    status_code: int,
) -> None:
    client = _client(
        httpx.MockTransport(
            lambda _request: httpx.Response(status_code, text="private")
        )
    )

    with pytest.raises(
        CloudflareAIPermanentError,
        match="request was rejected",
    ) as captured:
        client.generate("private prompt", b"private reference")

    assert "private" not in str(captured.value)
    assert "secret-token" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_generate_classifies_transport_errors_as_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private network detail", request=request)

    with pytest.raises(
        CloudflareAITransientError,
        match="temporarily unavailable",
    ) as captured:
        _client(httpx.MockTransport(handler)).generate(
            "private prompt",
            b"private reference",
        )

    assert "private" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(
            200,
            json={
                "result": {},
                "success": True,
                "errors": [],
                "messages": [],
            },
        ),
        httpx.Response(
            200,
            json={
                "result": {"image": "%%%"},
                "success": True,
                "errors": [],
                "messages": [],
            },
        ),
        httpx.Response(
            200,
            json={
                "result": None,
                "success": False,
                "errors": [{"message": "private provider detail"}],
                "messages": [],
            },
        ),
    ],
)
def test_generate_rejects_malformed_or_unsuccessful_responses(
    response: httpx.Response,
) -> None:
    client = _client(httpx.MockTransport(lambda _request: response))

    with pytest.raises(
        CloudflareAIPermanentError,
        match="malformed response|request was rejected",
    ) as captured:
        client.generate("private prompt", b"private reference")

    assert "private" not in str(captured.value)
    assert "secret-token" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
