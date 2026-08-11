from decimal import Decimal
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image

from app.config import settings
from app.services import illustration, storage
from app.services.cost_tracking import Usage
from app.services.flux import (
    FluxModerationError,
    FluxPermanentError,
    FluxSubmission,
    FluxTransientError,
)


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 48), "#7d91d1").save(output, format="PNG")
    return output.getvalue()


class FakeFluxClient:
    def __init__(
        self,
        *,
        submit_results: list[FluxSubmission | Exception] | None = None,
        wait_results: list[str | Exception] | None = None,
        download_result: bytes | Exception | None = None,
    ) -> None:
        self.submit_results = list(
            submit_results
            or [
                FluxSubmission(
                    id="job-1",
                    polling_url=(
                        "https://api.test/v1/get_result?id=job-1"
                    ),
                    cost_credits=Decimal("1.5"),
                )
            ]
        )
        self.wait_results = list(
            wait_results or ["https://cdn.test/result.webp"]
        )
        self.download_result = download_result or _image_bytes()
        self.submit_calls: list[tuple[str, bytes]] = []
        self.wait_calls: list[FluxSubmission] = []
        self.download_calls: list[str] = []

    def __enter__(self) -> "FakeFluxClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def submit(self, prompt: str, input_image: bytes) -> FluxSubmission:
        self.submit_calls.append((prompt, input_image))
        result = self.submit_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def wait_for_result(self, submission: FluxSubmission) -> str:
        self.wait_calls.append(submission)
        result = self.wait_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def download(self, url: str) -> bytes:
        self.download_calls.append(url)
        if isinstance(self.download_result, Exception):
            raise self.download_result
        return self.download_result


class RecordingCostRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_call(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def flux_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_gen_provider", "flux")
    monkeypatch.setattr(settings, "image_gen_api_key", "test-key")
    monkeypatch.setattr(settings, "image_gen_model", "flux-2-klein-9b")


def _wire_flux(
    monkeypatch: pytest.MonkeyPatch,
    fake_client: FakeFluxClient,
) -> None:
    monkeypatch.setattr(illustration, "_flux_client", lambda: fake_client)
    monkeypatch.setattr(
        storage,
        "get_object",
        lambda _reference: b"private-reference",
    )
    monkeypatch.setattr(
        storage,
        "put_object",
        lambda _data, _key, _content_type: (
            "local://illustrations/page.webp"
        ),
    )


def test_flux_illustration_uses_reference_style_storage_and_cost(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient()
    recorder = RecordingCostRecorder()
    stored: dict[str, object] = {}
    monkeypatch.setattr(
        illustration,
        "_flux_client",
        lambda: fake_client,
        raising=False,
    )
    monkeypatch.setattr(
        storage,
        "get_object",
        lambda _reference: b"private-reference",
    )

    def store(data: bytes, key: str, content_type: str) -> str:
        stored.update(data=data, key=key, content_type=content_type)
        return "local://illustrations/page.webp"

    monkeypatch.setattr(storage, "put_object", store)

    reference = illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=2,
        page_text="Camille discovers a moonlit garden.",
        reference_photo_ref="local://references/child.webp",
        recorder=recorder,
    )

    assert reference == "local://illustrations/page.webp"
    prompt, reference_bytes = fake_client.submit_calls[0]
    assert reference_bytes == b"private-reference"
    assert "warm hand-painted children's picture-book" in prompt
    assert "preserve recognizable facial structure" in prompt
    assert "no written text" in prompt
    assert "Page 2" in prompt
    assert "Camille discovers a moonlit garden." in prompt
    assert str(stored["key"]).startswith("illustrations/")
    assert str(stored["key"]).endswith(".webp")
    assert stored["content_type"] == "image/webp"
    assert isinstance(stored["data"], bytes)
    with Image.open(BytesIO(stored["data"])) as image:
        assert image.format == "WEBP"
    assert recorder.calls == [
        {
            "stage": "illustration",
            "provider": "flux",
            "model": "flux-2-klein-9b",
            "attempt": 1,
            "outcome": "succeeded",
            "usage": (Usage("micro_credit", 1_500_000),),
            "page_number": 2,
        }
    ]


def test_flux_records_accepted_cost_before_polling(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient()
    _wire_flux(monkeypatch, fake_client)
    calls: list[tuple[object, ...]] = []
    call_id = UUID("11111111-1111-1111-1111-111111111111")

    class DurableRecorder:
        def record_accepted_call(self, **kwargs: object) -> UUID:
            calls.append(("accepted", kwargs))
            return call_id

        def update_call_outcome(
            self,
            call_id: UUID,
            outcome: str,
        ) -> None:
            calls.append(("outcome", call_id, outcome))

        def record_call(self, **kwargs: object) -> None:
            calls.append(("legacy", kwargs))

    original_wait = fake_client.wait_for_result

    def observe_poll(submission: FluxSubmission) -> str:
        assert calls[0][0] == "accepted"
        return original_wait(submission)

    fake_client.wait_for_result = observe_poll

    illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=1,
        page_text="Camille follows the starlight.",
        reference_photo_ref="local://references/child.webp",
        recorder=DurableRecorder(),
    )

    assert calls[0][1]["usage"] == (
        Usage("micro_credit", 1_500_000),
    )
    assert calls[1] == ("outcome", call_id, "succeeded")
    assert all(call[0] != "legacy" for call in calls)


def test_flux_exposes_stored_reference_when_cost_update_fails(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient()
    _wire_flux(monkeypatch, fake_client)
    call_id = UUID("11111111-1111-1111-1111-111111111111")

    class FailingRecorder:
        def record_accepted_call(self, **_kwargs: object) -> UUID:
            return call_id

        def update_call_outcome(
            self,
            _call_id: UUID,
            _outcome: str,
        ) -> None:
            raise RuntimeError("database unavailable")

        def record_call(self, **_kwargs: object) -> None:
            raise AssertionError("accepted calls use durable recording")

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match="could not be finalized",
    ) as captured:
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=3,
            page_text="Camille follows the starlight.",
            reference_photo_ref="local://references/child.webp",
            recorder=FailingRecorder(),
        )

    assert captured.value.created_reference == (
        "local://illustrations/page.webp"
    )


def test_flux_retries_one_transient_provider_failure(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient(
        submit_results=[
            FluxTransientError("secret provider detail"),
            FluxSubmission(
                id="job-2",
                polling_url="https://api.test/v1/get_result?id=job-2",
                cost_credits=Decimal("1.5"),
            ),
        ]
    )
    recorder = RecordingCostRecorder()
    _wire_flux(monkeypatch, fake_client)

    reference = illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=1,
        page_text="Camille follows the starlight.",
        reference_photo_ref="local://references/child.webp",
        recorder=recorder,
    )

    assert reference == "local://illustrations/page.webp"
    assert len(fake_client.submit_calls) == 2
    assert recorder.calls[0]["attempt"] == 1
    assert recorder.calls[0]["outcome"] == "provider_failure"
    assert recorder.calls[0]["usage"] is None
    assert recorder.calls[1]["attempt"] == 2
    assert recorder.calls[1]["outcome"] == "succeeded"


def test_flux_retry_preserves_cost_from_accepted_failed_job(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient(
        submit_results=[
            FluxSubmission(
                id="job-1",
                polling_url="https://api.test/v1/get_result?id=job-1",
                cost_credits=Decimal("1.5"),
            ),
            FluxSubmission(
                id="job-2",
                polling_url="https://api.test/v1/get_result?id=job-2",
                cost_credits=Decimal("1.5"),
            ),
        ],
        wait_results=[
            FluxTransientError("secret polling failure"),
            "https://cdn.test/result.webp",
        ],
    )
    recorder = RecordingCostRecorder()
    _wire_flux(monkeypatch, fake_client)

    illustration.generate_illustration(
        avatar_seed="child-id",
        page_number=1,
        page_text="Camille follows the starlight.",
        reference_photo_ref="local://references/child.webp",
        recorder=recorder,
    )

    assert recorder.calls[0]["outcome"] == "provider_failure"
    assert recorder.calls[0]["usage"] == (
        Usage("micro_credit", 1_500_000),
    )
    assert recorder.calls[1]["outcome"] == "succeeded"


def test_flux_stops_after_two_transient_failures(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient(
        submit_results=[
            FluxTransientError("first secret"),
            FluxTransientError("second secret"),
        ]
    )
    _wire_flux(monkeypatch, fake_client)

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

    assert "secret" not in str(captured.value)
    assert len(fake_client.submit_calls) == 2


@pytest.mark.parametrize(
    ("provider_error", "parent_message"),
    [
        (FluxPermanentError("secret detail"), "could not be processed"),
        (FluxModerationError("secret detail"), "safety checks"),
    ],
)
def test_flux_does_not_retry_permanent_provider_failures(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    provider_error: FluxPermanentError,
    parent_message: str,
) -> None:
    fake_client = FakeFluxClient(submit_results=[provider_error])
    recorder = RecordingCostRecorder()
    _wire_flux(monkeypatch, fake_client)

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match=parent_message,
    ) as captured:
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=1,
            page_text="Camille follows the starlight.",
            reference_photo_ref="local://references/child.webp",
            recorder=recorder,
        )

    assert "secret" not in str(captured.value)
    assert len(fake_client.submit_calls) == 1
    assert recorder.calls[0]["outcome"] == "provider_failure"


def test_flux_rejects_invalid_generated_image_without_retrying(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient(download_result=b"not-an-image")
    recorder = RecordingCostRecorder()
    _wire_flux(monkeypatch, fake_client)

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

    assert len(fake_client.submit_calls) == 1
    assert recorder.calls == [
        {
            "stage": "illustration",
            "provider": "flux",
            "model": "flux-2-klein-9b",
            "attempt": 1,
            "outcome": "invalid_response",
            "usage": (Usage("micro_credit", 1_500_000),),
            "page_number": 1,
        }
    ]


def test_flux_storage_failure_is_sanitized_without_regeneration(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFluxClient()
    recorder = RecordingCostRecorder()
    _wire_flux(monkeypatch, fake_client)

    def fail_storage(
        _data: bytes,
        _key: str,
        _content_type: str,
    ) -> str:
        raise RuntimeError("secret storage detail")

    monkeypatch.setattr(storage, "put_object", fail_storage)

    with pytest.raises(
        illustration.IllustrationGenerationError,
        match="could not be stored",
    ) as captured:
        illustration.generate_illustration(
            avatar_seed="child-id",
            page_number=1,
            page_text="Camille follows the starlight.",
            reference_photo_ref="local://references/child.webp",
            recorder=recorder,
        )

    assert "secret" not in str(captured.value)
    assert len(fake_client.submit_calls) == 1
    assert recorder.calls[0]["outcome"] == "storage_failure"


def test_flux_requires_reference_photo_before_creating_client(
    flux_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = False

    def create_client() -> FakeFluxClient:
        nonlocal created
        created = True
        return FakeFluxClient()

    monkeypatch.setattr(illustration, "_flux_client", create_client)

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
