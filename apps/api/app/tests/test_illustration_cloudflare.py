import logging
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
        self.calls: list[tuple[str, bytes | None, int | None]] = []

    def __enter__(self) -> "FakeCloudflareAIClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def generate(
        self,
        prompt: str,
        input_image: bytes | None,
        *,
        seed: int | None = None,
    ) -> bytes:
        self.calls.append((prompt, input_image, seed))
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


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_cloudflare_uses_png_reference_style_storage_and_cost(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    image_format: str,
) -> None:
    fake_client = FakeCloudflareAIClient()
    recorder = RecordingCostRecorder()
    stored: dict[str, object] = {}
    original_reference = _image_bytes(
        size=(900, 600),
        image_format=image_format,
    )
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
    prompt, provider_reference, seed = fake_client.calls[0]
    assert "warm hand-painted children's picture-book" in prompt
    assert "loose visual reference" in prompt
    assert "stylized fictional character" in prompt
    assert "rather than reproducing or identifying the real person" in prompt
    assert "preserve recognizable facial structure" not in prompt
    assert "Page 2" in prompt
    assert "Camille discovers a moonlit garden." in prompt
    assert seed is None
    assert provider_reference != original_reference
    with Image.open(BytesIO(provider_reference)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
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


def test_cloudflare_retries_output_safety_rejection(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    fake_client = FakeCloudflareAIClient(
        [
            CloudflareAIPermanentError(
                "private first rejection",
                provider_code=3030,
            ),
            CloudflareAIPermanentError(
                "private second rejection",
                provider_code=3030,
            ),
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
    assert len(fake_client.calls) == 3
    assert [call["outcome"] for call in recorder.calls] == [
        "provider_failure",
        "provider_failure",
        "succeeded",
    ]
    assert "code 3030 on page 1 (attempt 1)" in caplog.text
    assert "code 3030 on page 1 (attempt 2)" in caplog.text


def test_cloudflare_stops_after_output_safety_rejections(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    fake_client = FakeCloudflareAIClient(
        [
            CloudflareAIPermanentError(
                "private rejection",
                provider_code=3030,
            )
            for _attempt in range(3)
        ]
    )
    _wire_cloudflare(monkeypatch, fake_client)

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match="safety checks",
    ) as captured:
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=1,
            page_text="Camille follows the starlight.",
            reference_photo_ref="local://references/child.webp",
        )

    assert "private" not in str(captured.value)
    assert len(fake_client.calls) == 3


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


def test_cloudflare_logs_only_provider_code_and_page_for_rejection(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_client = FakeCloudflareAIClient(
        [
            CloudflareAIPermanentError(
                "private provider detail",
                provider_code=3030,
            )
            for _attempt in range(3)
        ]
    )
    _wire_cloudflare(monkeypatch, fake_client)
    private_page_text = "private child story scene"

    with caplog.at_level(logging.WARNING, logger=illustration.__name__):
        with pytest.raises(illustration.IllustrationGenerationError):
            illustration.generate_illustration(
                avatar_seed="child-id",
                page_number=2,
                page_text=private_page_text,
                reference_photo_ref="local://references/child.webp",
            )

    assert "Cloudflare illustration rejected with code 3030 on page 2" in (
        caplog.text
    )
    assert "private provider detail" not in caplog.text
    assert private_page_text not in caplog.text


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


def test_cloudflare_without_reference_uses_stable_fictional_character(
    cloudflare_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeCloudflareAIClient(
        [_image_bytes(), _image_bytes()]
    )
    _wire_cloudflare(monkeypatch, fake_client)

    first = illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=1,
        page_text="Camille follows the starlight.",
    )
    second = illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=2,
        page_text="Camille reaches a moonlit garden.",
    )

    assert first == "local://illustrations/page.webp"
    assert second == "local://illustrations/page.webp"
    first_prompt, first_reference, first_seed = fake_client.calls[0]
    second_prompt, second_reference, second_seed = fake_client.calls[1]
    assert first_reference is None
    assert second_reference is None
    assert first_seed == second_seed
    assert first_seed is not None
    assert "invented fictional child" in first_prompt
    assert "input reference image" not in first_prompt
    assert "image 0" not in first_prompt
    first_design = next(
        line for line in first_prompt.splitlines()
        if line.startswith("Character design:")
    )
    second_design = next(
        line for line in second_prompt.splitlines()
        if line.startswith("Character design:")
    )
    assert first_design == second_design
