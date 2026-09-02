import logging
from decimal import Decimal
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from app.config import settings
from app.services import storage
from app.services.cloudflare_ai import (
    CloudflareAIClient,
    CloudflareAIPermanentError,
    CloudflareAITransientError,
)
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
from app.services.image_files import (
    InvalidImageError,
    normalize_png,
    normalize_webp,
)
from app.services.retry import retry_transient


logger = logging.getLogger(__name__)

MICROCREDITS_PER_CREDIT = Decimal("1000000")

STYLE_LOCK_PREFIX = """Create a warm hand-painted children's picture-book illustration with a soft watercolor texture, gentle lighting, rounded shapes, and age-appropriate imagery. Treat the child shown in the input reference image as the main character and preserve recognizable facial structure, skin tone, hair color, hairstyle, and other stable features across the book while rendering the child as an illustrated character. Keep the same character design and watercolor treatment on every page. Use a landscape 4:3 composition. Include no written text, letters, captions, logos, or watermarks. Do not make the result photorealistic."""

CLOUDFLARE_STYLE_LOCK_PREFIX = """Create a warm hand-painted children's picture-book illustration with soft watercolor texture, gentle lighting, rounded shapes, and age-appropriate imagery. Use image 0 only as a loose visual reference for the main illustrated character's hair, hairstyle, and color palette. Render a stylized fictional character rather than reproducing or identifying the real person. Use a landscape 4:3 composition. Include no written text, captions, logos, or watermarks. Keep the result non-photorealistic."""

CLOUDFLARE_TEXT_ONLY_PREFIX = """Create a warm hand-painted children's picture-book illustration with soft watercolor texture, gentle lighting, rounded shapes, and age-appropriate imagery. There is no reference photo, so portray an invented fictional child rather than attempting to infer or reproduce a real person's appearance. Preserve the supplied character design exactly across the book. Use a landscape 4:3 composition. Include no written text, captions, logos, or watermarks. Keep the result non-photorealistic."""

_FICTIONAL_HAIR = (
    "short dark curls",
    "soft chestnut waves",
    "neat black braids",
    "a fluffy dark-brown crop",
    "tied-back auburn hair",
)
_FICTIONAL_OUTFITS = (
    "a teal sweater, navy trousers, and yellow sneakers",
    "a blue cardigan, tan trousers, and red sneakers",
    "a plum hoodie, gray trousers, and green sneakers",
    "a forest-green sweater, denim trousers, and orange sneakers",
    "a warm-orange cardigan, navy trousers, and blue sneakers",
)


class IllustrationGenerationError(RuntimeError):
    def __init__(
        self,
        code: str,
        parent_message: str,
        *,
        created_reference: str | None = None,
    ) -> None:
        super().__init__(parent_message)
        self.code = code
        self.parent_message = parent_message
        self.created_reference = created_reference


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
        token = sha256(
            f"{avatar_seed}\0{page_number}".encode()
        ).hexdigest()[:16]
        return (
            f"{settings.api_base_url.rstrip('/')}"
            f"/media/placeholders/illustrations/{token}.svg"
        )


def generate_placeholder_svg(token: str) -> bytes:
    primary = token[:6]
    accent = token[6:12]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 640 480">'
        f'<rect width="640" height="480" fill="#{primary}"/>'
        f'<circle cx="320" cy="240" r="150" fill="#{accent}"/>'
        '<circle cx="260" cy="210" r="24" fill="#fff" opacity=".7"/>'
        '</svg>'
    ).encode()


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


def _cloudflare_client() -> CloudflareAIClient:
    if (
        not settings.cloudflare_ai_account_id
        or not settings.cloudflare_ai_api_token
    ):
        raise IllustrationGenerationError(
            "illustration_provider_not_configured",
            "The illustration provider is not configured.",
        )
    return CloudflareAIClient(
        account_id=settings.cloudflare_ai_account_id,
        api_token=settings.cloudflare_ai_api_token,
        base_url=settings.cloudflare_ai_base_url,
        model=settings.cloudflare_ai_model,
        timeout=settings.cloudflare_ai_timeout_seconds,
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


def _fictional_character_design(avatar_seed: str) -> str:
    digest = sha256(avatar_seed.encode()).digest()
    hair = _FICTIONAL_HAIR[digest[0] % len(_FICTIONAL_HAIR)]
    outfit = _FICTIONAL_OUTFITS[digest[1] % len(_FICTIONAL_OUTFITS)]
    return f"a young child with {hair}, wearing {outfit}"


def _cloudflare_seed(avatar_seed: str) -> int:
    seed = int.from_bytes(sha256(avatar_seed.encode()).digest()[:4], "big")
    return seed or 1


def _cloudflare_prompt(
    page_number: int,
    page_text: str,
    *,
    avatar_seed: str,
    has_reference: bool,
) -> str:
    if has_reference:
        prefix = CLOUDFLARE_STYLE_LOCK_PREFIX
        character_design = ""
    else:
        prefix = CLOUDFLARE_TEXT_ONLY_PREFIX
        character_design = (
            "\nCharacter design: "
            f"{_fictional_character_design(avatar_seed)}."
        )
    return (
        f"{prefix}{character_design}\n\n"
        f"Page {page_number} scene: {page_text}"
    )


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


def _record_accepted_flux_attempt(
    recorder: CostRecorder,
    *,
    attempt: int,
    usage: tuple[Usage, ...] | None,
    page_number: int,
) -> UUID | None:
    if getattr(type(recorder), "record_accepted_call", None) is None:
        return None
    return recorder.record_accepted_call(
        stage="illustration",
        provider="flux",
        model=settings.image_gen_model,
        attempt=attempt,
        usage=usage,
        page_number=page_number,
    )


def _finish_flux_attempt(
    recorder: CostRecorder,
    *,
    call_id: UUID | None,
    attempt: int,
    outcome: str,
    usage: tuple[Usage, ...] | None,
    page_number: int,
) -> None:
    if call_id is not None:
        recorder.update_call_outcome(call_id, outcome)
        return
    _record_flux_attempt(
        recorder,
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

        def _attempt(attempt: int) -> str:
            usage: tuple[Usage, ...] | None = None
            call_id: UUID | None = None
            try:
                submission = client.submit(
                    _flux_prompt(page_number, page_text),
                    reference_bytes,
                )
                usage = _flux_usage(submission.cost_credits)
                call_id = _record_accepted_flux_attempt(
                    recorder,
                    attempt=attempt,
                    usage=usage,
                    page_number=page_number,
                )
                result_url = client.wait_for_result(submission)
                raw_image = client.download(result_url)
            except FluxTransientError as exc:
                _finish_flux_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="provider_failure",
                    usage=usage,
                    page_number=page_number,
                )
                raise
            except FluxPermanentError as exc:
                _finish_flux_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="provider_failure",
                    usage=usage,
                    page_number=page_number,
                )
                raise _provider_error(exc) from exc

            try:
                normalized = normalize_webp(raw_image)
            except InvalidImageError as exc:
                _finish_flux_attempt(
                    recorder,
                    call_id=call_id,
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
                _finish_flux_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="storage_failure",
                    usage=usage,
                    page_number=page_number,
                )
                raise IllustrationGenerationError(
                    "illustration_storage_failed",
                    "The generated illustration could not be stored.",
                ) from exc

            try:
                _finish_flux_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="succeeded",
                    usage=usage,
                    page_number=page_number,
                )
            except Exception as exc:
                raise IllustrationGenerationError(
                    "illustration_cost_tracking_failed",
                    "The generated illustration could not be finalized.",
                    created_reference=image_reference,
                ) from exc
            return image_reference

        try:
            return retry_transient(
                _attempt,
                is_transient=lambda e: isinstance(e, FluxTransientError),
            )
        except FluxTransientError as exc:
            raise IllustrationGenerationError(
                "illustration_unavailable",
                (
                    "The illustration service is temporarily "
                    "unavailable. Please try again later."
                ),
            ) from exc


def _record_cloudflare_attempt(
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
        provider="cloudflare",
        model=settings.cloudflare_ai_model,
        attempt=attempt,
        outcome=outcome,
        usage=usage,
        page_number=page_number,
    )


def _record_accepted_cloudflare_attempt(
    recorder: CostRecorder,
    *,
    attempt: int,
    page_number: int,
) -> UUID | None:
    if getattr(type(recorder), "record_accepted_call", None) is None:
        return None
    return recorder.record_accepted_call(
        stage="illustration",
        provider="cloudflare",
        model=settings.cloudflare_ai_model,
        attempt=attempt,
        usage=(Usage("image", 1),),
        page_number=page_number,
    )


def _finish_cloudflare_attempt(
    recorder: CostRecorder,
    *,
    call_id: UUID | None,
    attempt: int,
    outcome: str,
    usage: tuple[Usage, ...] | None,
    page_number: int,
) -> None:
    if call_id is not None:
        recorder.update_call_outcome(call_id, outcome)
        return
    _record_cloudflare_attempt(
        recorder,
        attempt=attempt,
        outcome=outcome,
        usage=usage,
        page_number=page_number,
    )


def _generate_cloudflare(
    *,
    avatar_seed: str,
    page_number: int,
    page_text: str,
    reference_photo_ref: str | None,
    recorder: CostRecorder,
) -> str:
    provider_reference: bytes | None = None
    if reference_photo_ref:
        try:
            reference_bytes = storage.get_object(reference_photo_ref)
            provider_reference = normalize_png(
                reference_bytes,
                max_dimension=511,
            )
        except Exception as exc:
            raise IllustrationGenerationError(
                "reference_photo_unreadable",
                "The reference photo could not be read.",
            ) from exc

    prompt = _cloudflare_prompt(
        page_number,
        page_text,
        avatar_seed=avatar_seed,
        has_reference=provider_reference is not None,
    )
    seed = (
        None
        if provider_reference is not None
        else _cloudflare_seed(avatar_seed)
    )

    with _cloudflare_client() as client:

        def _attempt(attempt: int) -> str:
            usage: tuple[Usage, ...] | None = None
            call_id: UUID | None = None
            try:
                raw_image = client.generate(
                    prompt,
                    provider_reference,
                    seed=seed,
                )
                usage = (Usage("image", 1),)
                call_id = _record_accepted_cloudflare_attempt(
                    recorder,
                    attempt=attempt,
                    page_number=page_number,
                )
            except CloudflareAITransientError:
                _finish_cloudflare_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="provider_failure",
                    usage=usage,
                    page_number=page_number,
                )
                raise
            except CloudflareAIPermanentError as exc:
                provider_code = (
                    exc.provider_code
                    if exc.provider_code is not None
                    else "unknown"
                )
                logger.warning(
                    "Cloudflare illustration rejected with code %s "
                    "on page %s (attempt %s).",
                    provider_code,
                    page_number,
                    attempt,
                )
                _finish_cloudflare_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="provider_failure",
                    usage=usage,
                    page_number=page_number,
                )
                if exc.is_output_safety_rejection:
                    raise
                raise IllustrationGenerationError(
                    "illustration_request_invalid",
                    (
                        "The reference photo or illustration request "
                        "could not be processed."
                    ),
                ) from exc

            try:
                normalized = normalize_webp(raw_image)
            except InvalidImageError as exc:
                _finish_cloudflare_attempt(
                    recorder,
                    call_id=call_id,
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
                _finish_cloudflare_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="storage_failure",
                    usage=usage,
                    page_number=page_number,
                )
                raise IllustrationGenerationError(
                    "illustration_storage_failed",
                    "The generated illustration could not be stored.",
                ) from exc

            try:
                _finish_cloudflare_attempt(
                    recorder,
                    call_id=call_id,
                    attempt=attempt,
                    outcome="succeeded",
                    usage=usage,
                    page_number=page_number,
                )
            except Exception as exc:
                raise IllustrationGenerationError(
                    "illustration_cost_tracking_failed",
                    "The generated illustration could not be finalized.",
                    created_reference=image_reference,
                ) from exc
            return image_reference

        try:
            return retry_transient(
                _attempt,
                is_transient=lambda error: (
                    isinstance(error, CloudflareAITransientError)
                    or (
                        isinstance(error, CloudflareAIPermanentError)
                        and error.is_output_safety_rejection
                    )
                ),
            )
        except CloudflareAIPermanentError as exc:
            raise IllustrationGenerationError(
                "illustration_safety_rejected",
                (
                    "The illustration service could not produce an image "
                    "that passed its safety checks. Please try again."
                ),
            ) from exc
        except CloudflareAITransientError as exc:
            raise IllustrationGenerationError(
                "illustration_unavailable",
                (
                    "The illustration service is temporarily "
                    "unavailable. Please try again later."
                ),
            ) from exc


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
    if provider_name == "cloudflare":
        return _generate_cloudflare(
            avatar_seed=avatar_seed,
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
