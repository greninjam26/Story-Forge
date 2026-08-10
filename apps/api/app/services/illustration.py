from decimal import Decimal
from typing import Protocol

from app.config import settings
from app.services import storage
from app.services.cost_tracking import (
    CostRecorder,
    NOOP_COST_RECORDER,
    Usage,
    record_cost_call,
)
from app.services.flux import (
    FluxClient,
    FluxModerationError,
    FluxPermanentError,
    FluxTransientError,
)
from app.services.image_files import InvalidImageError, normalize_webp


MICROCREDITS_PER_CREDIT = Decimal("1000000")

STYLE_LOCK_PREFIX = """Create a warm hand-painted children's picture-book illustration with a soft watercolor texture, gentle lighting, rounded shapes, and age-appropriate imagery. Treat the child shown in the input reference image as the main character and preserve recognizable facial structure, skin tone, hair color, hairstyle, and other stable features across the book while rendering the child as an illustrated character. Keep the same character design and watercolor treatment on every page. Use a landscape 4:3 composition. Include no written text, letters, captions, logos, or watermarks. Do not make the result photorealistic."""


class IllustrationGenerationError(RuntimeError):
    def __init__(self, code: str, parent_message: str) -> None:
        super().__init__(parent_message)
        self.code = code
        self.parent_message = parent_message


class IllustrationProvider(Protocol):
    def generate(
        self,
        *,
        avatar_seed: str,
        page_number: int,
        page_text: str,
    ) -> str: ...


class StubIllustrationProvider:
    def generate(
        self,
        *,
        avatar_seed: str,
        page_number: int,
        page_text: str,
    ) -> str:
        return (
            "https://picsum.photos/seed/"
            f"{avatar_seed}-{page_number}/640/480"
        )


_PROVIDERS: dict[str, IllustrationProvider] = {
    "stub": StubIllustrationProvider(),
}


def _flux_client() -> FluxClient:
    if not settings.image_gen_api_key:
        raise IllustrationGenerationError(
            "illustration_provider_not_configured",
            "The illustration provider is not configured.",
        )
    return FluxClient(
        api_key=settings.image_gen_api_key,
        base_url=settings.image_gen_base_url,
        model=settings.image_gen_model,
        request_timeout=settings.image_gen_request_timeout_seconds,
        poll_timeout=settings.image_gen_poll_timeout_seconds,
        poll_interval=settings.image_gen_poll_interval_seconds,
    )


def _flux_usage(
    cost_credits: Decimal | None,
) -> tuple[Usage, ...] | None:
    if cost_credits is None:
        return None
    quantity = cost_credits * MICROCREDITS_PER_CREDIT
    if quantity != quantity.to_integral_value():
        return None
    return (Usage("micro_credit", int(quantity)),)


def _flux_prompt(page_number: int, page_text: str) -> str:
    return f"{STYLE_LOCK_PREFIX}\n\nPage {page_number} scene: {page_text}"


def _record_flux_attempt(
    recorder: CostRecorder,
    *,
    attempt: int,
    outcome: str,
    usage: tuple[Usage, ...] | None,
    page_number: int,
) -> None:
    record_cost_call(
        recorder,
        stage="illustration",
        provider="flux",
        model=settings.image_gen_model,
        attempt=attempt,
        outcome=outcome,
        usage=usage,
        page_number=page_number,
    )


def _provider_error(
    error: FluxPermanentError,
) -> IllustrationGenerationError:
    if isinstance(error, FluxModerationError):
        return IllustrationGenerationError(
            "illustration_moderated",
            (
                "The illustration could not be generated because of "
                "provider safety checks."
            ),
        )
    return IllustrationGenerationError(
        "illustration_request_invalid",
        (
            "The reference photo or illustration request could not be "
            "processed."
        ),
    )


def _generate_flux(
    *,
    page_number: int,
    page_text: str,
    reference_photo_ref: str | None,
    recorder: CostRecorder,
) -> str:
    if not reference_photo_ref:
        raise IllustrationGenerationError(
            "reference_photo_required",
            "Add a reference photo before generating illustrations.",
        )
    try:
        reference_bytes = storage.get_object(reference_photo_ref)
    except Exception as exc:
        raise IllustrationGenerationError(
            "reference_photo_unreadable",
            "The reference photo could not be read.",
        ) from exc

    with _flux_client() as client:
        for attempt in (1, 2):
            usage: tuple[Usage, ...] | None = None
            try:
                submission = client.submit(
                    _flux_prompt(page_number, page_text),
                    reference_bytes,
                )
                usage = _flux_usage(submission.cost_credits)
                result_url = client.wait_for_result(submission)
                raw_image = client.download(result_url)
            except FluxTransientError as exc:
                _record_flux_attempt(
                    recorder,
                    attempt=attempt,
                    outcome="provider_failure",
                    usage=usage,
                    page_number=page_number,
                )
                if attempt == 1:
                    continue
                raise IllustrationGenerationError(
                    "illustration_unavailable",
                    (
                        "The illustration service is temporarily "
                        "unavailable. Please try again later."
                    ),
                ) from exc
            except FluxPermanentError as exc:
                _record_flux_attempt(
                    recorder,
                    attempt=attempt,
                    outcome="provider_failure",
                    usage=usage,
                    page_number=page_number,
                )
                raise _provider_error(exc) from exc

            try:
                normalized = normalize_webp(raw_image)
            except InvalidImageError as exc:
                _record_flux_attempt(
                    recorder,
                    attempt=attempt,
                    outcome="invalid_response",
                    usage=usage,
                    page_number=page_number,
                )
                raise IllustrationGenerationError(
                    "illustration_invalid_image",
                    "The illustration service returned an invalid image.",
                ) from exc

            try:
                image_reference = storage.put_object(
                    normalized,
                    storage.new_key("illustrations", ".webp"),
                    "image/webp",
                )
            except Exception as exc:
                _record_flux_attempt(
                    recorder,
                    attempt=attempt,
                    outcome="storage_failure",
                    usage=usage,
                    page_number=page_number,
                )
                raise IllustrationGenerationError(
                    "illustration_storage_failed",
                    "The generated illustration could not be stored.",
                ) from exc

            _record_flux_attempt(
                recorder,
                attempt=attempt,
                outcome="succeeded",
                usage=usage,
                page_number=page_number,
            )
            return image_reference

    raise AssertionError("illustration retry loop did not terminate")


def generate_illustration(
    *,
    avatar_seed: str,
    page_number: int,
    page_text: str,
    reference_photo_ref: str | None = None,
    recorder: CostRecorder = NOOP_COST_RECORDER,
) -> str:
    provider_name = settings.image_gen_provider.strip().lower()
    if provider_name == "flux":
        return _generate_flux(
            page_number=page_number,
            page_text=page_text,
            reference_photo_ref=reference_photo_ref,
            recorder=recorder,
        )
    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(
            f"Unsupported illustration provider: {provider_name}"
        )

    try:
        image_url = provider.generate(
            avatar_seed=avatar_seed,
            page_number=page_number,
            page_text=page_text,
        )
    except Exception:
        record_cost_call(
            recorder,
            stage="illustration",
            provider=provider_name,
            model=None,
            attempt=1,
            outcome="provider_failure",
            usage=None,
            page_number=page_number,
        )
        raise
    if not isinstance(image_url, str) or not image_url.strip():
        record_cost_call(
            recorder,
            stage="illustration",
            provider=provider_name,
            model=None,
            attempt=1,
            outcome="invalid_response",
            usage=(Usage("image", 1),),
            page_number=page_number,
        )
        raise ValueError("Illustration provider returned an invalid result.")
    record_cost_call(
        recorder,
        stage="illustration",
        provider=provider_name,
        model=None,
        attempt=1,
        outcome="succeeded",
        usage=(Usage("image", 1),),
        page_number=page_number,
    )
    return image_url
