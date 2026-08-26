from io import BytesIO

import pytest
from PIL import Image

from app.config import settings
from app.services import illustration, storage
from app.services.cloudflare_ai import (
    CloudflareAIPermanentError,
    CloudflareAITransientError,
)
from app.services.cost_tracking import Usage


def _image_bytes(
    *,
    size: tuple[int, int] = (64, 48),
    image_format: str = "PNG",
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "#7d91d1").save(output, format=image_format)
    return output.getvalue()


class FakeCloudflareAIClient:
    def __init__(self, results: list[bytes | Exception] | None = None) -> None:
        self.results = list(results or [_image_bytes()])
        self.calls: list[tuple[str, bytes]] = []

    def __enter__(self) -> "FakeCloudflareAIClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def generate(self, prompt: str, input_image: bytes) -> bytes:
        self.calls.append((prompt, input_image))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class RecordingCostRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_call(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def cloudflare_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_gen_provider", "cloudflare")
    monkeypatch.setitem(
        settings.__dict__, "cloudflare_ai_account_id", "account-123"
    )
    monkeypatch.setitem(
        settings.__dict__, "cloudflare_ai_api_token", "token-123"
    )
    monkeypatch.setitem(
        settings.__dict__,
        "cloudflare_ai_model",
        "@cf/black-forest-labs/flux-2-klein-4b",
    )


def _wire_cloudflare(
    monkeypatch: pytest.MonkeyPatch,
    fake_client: FakeCloudflareAIClient,
) -> None:
    monkeypatch.setattr(
        illustration,
        "_cloudflare_client",
        lambda: fake_client,
        raising=False,
    )
    monkeypatch.setattr(
        storage,
        "get_object",
        lambda _reference: _image_bytes(size=(900, 600)),
    )
    monkeypatch.setattr(
        storage,
        "put_object",
        lambda _data, _key, _content_type: (
            "local://illustrations/page.webp"
        ),
    )


def test_cloudflare_uses_resized_reference_style_storage_and_cost(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeCloudflareAIClient()
    recorder = RecordingCostRecorder()
    stored: dict[str, object] = {}
    original_reference = _image_bytes(size=(900, 600))
    get_calls: list[str] = []
    monkeypatch.setattr(
        illustration,
        "_cloudflare_client",
        lambda: fake_client,
        raising=False,
    )

    def get_object(reference: str) -> bytes:
        get_calls.append(reference)
        return original_reference

    def put_object(data: bytes, key: str, content_type: str) -> str:
        stored.update(data=data, key=key, content_type=content_type)
        return "local://illustrations/page.webp"

    monkeypatch.setattr(storage, "get_object", get_object)
    monkeypatch.setattr(storage, "put_object", put_object)

    reference = illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=2,
        page_text="Camille discovers a moonlit garden.",
        reference_photo_ref="local://references/child.webp",
        recorder=recorder,
    )

    assert reference == "local://illustrations/page.webp"
    assert get_calls == ["local://references/child.webp"]
    prompt, provider_reference = fake_client.calls[0]
    assert "warm hand-painted children's picture-book" in prompt
    assert "preserve recognizable facial structure" in prompt
    assert "Page 2" in prompt
    assert "Camille discovers a moonlit garden." in prompt
    assert provider_reference != original_reference
    with Image.open(BytesIO(provider_reference)) as image:
        assert image.format == "WEBP"
        assert image.width <= 511
        assert image.height <= 511
    assert str(stored["key"]).startswith("illustrations/")
    assert str(stored["key"]).endswith(".webp")
    assert stored["content_type"] == "image/webp"
    with Image.open(BytesIO(stored["data"])) as image:
        assert image.format == "WEBP"
    assert recorder.calls == [
        {
            "stage": "illustration",
            "provider": "cloudflare",
            "model": "@cf/black-forest-labs/flux-2-klein-4b",
            "attempt": 1,
            "outcome": "succeeded",
            "usage": (Usage("image", 1),),
            "page_number": 2,
        }
    ]


def test_cloudflare_retries_transient_failure(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    fake_client = FakeCloudflareAIClient(
        [
            CloudflareAITransientError("private detail"),
            _image_bytes(),
        ]
    )
    recorder = RecordingCostRecorder()
    _wire_cloudflare(monkeypatch, fake_client)

    result = illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=1,
        page_text="Camille follows the starlight.",
        reference_photo_ref="local://references/child.webp",
        recorder=recorder,
    )

    assert result == "local://illustrations/page.webp"
    assert len(fake_client.calls) == 2
    assert recorder.calls[0]["attempt"] == 1
    assert recorder.calls[0]["outcome"] == "provider_failure"
    assert recorder.calls[1]["attempt"] == 2
    assert recorder.calls[1]["outcome"] == "succeeded"


def test_cloudflare_stops_after_transient_failures(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    fake_client = FakeCloudflareAIClient(
        [
            CloudflareAITransientError("first private detail"),
            CloudflareAITransientError("second private detail"),
            CloudflareAITransientError("third private detail"),
        ]
    )
    _wire_cloudflare(monkeypatch, fake_client)

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match="temporarily unavailable",
    ) as captured:
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=1,
            page_text="Camille follows the starlight.",
            reference_photo_ref="local://references/child.webp",
        )

    assert "private" not in str(captured.value)
    assert len(fake_client.calls) == 3


def test_cloudflare_does_not_retry_permanent_failure(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeCloudflareAIClient(
        [CloudflareAIPermanentError("private detail")]
    )
    _wire_cloudflare(monkeypatch, fake_client)

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match="could not be processed",
    ) as captured:
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=1,
            page_text="Camille follows the starlight.",
            reference_photo_ref="local://references/child.webp",
        )

    assert "private" not in str(captured.value)
    assert len(fake_client.calls) == 1


def test_cloudflare_rejects_invalid_generated_image_without_retrying(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeCloudflareAIClient([b"not-an-image"])
    recorder = RecordingCostRecorder()
    _wire_cloudflare(monkeypatch, fake_client)

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match="returned an invalid image",
    ):
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=1,
            page_text="Camille follows the starlight.",
            reference_photo_ref="local://references/child.webp",
            recorder=recorder,
        )

    assert len(fake_client.calls) == 1
    assert recorder.calls[0]["outcome"] == "invalid_response"


def test_cloudflare_requires_reference_before_creating_client(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = False

    def create_client() -> FakeCloudflareAIClient:
        nonlocal created
        created = True
        return FakeCloudflareAIClient()

    monkeypatch.setattr(
        illustration,
        "_cloudflare_client",
        create_client,
        raising=False,
    )

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match="reference photo",
    ):
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=1,
            page_text="Camille follows the starlight.",
        )

    assert created is False
