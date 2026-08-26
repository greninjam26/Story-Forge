"""Validation and normalization for private images."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

SUPPORTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
MAX_SOURCE_PIXELS = 25_000_000


class InvalidImageError(ValueError):
    """Raised when image bytes cannot be safely normalized."""


def _normalized_rgb(data: bytes, *, max_dimension: int) -> Image.Image:
    if max_dimension < 1:
        raise ValueError("max_dimension must be positive")

    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in SUPPORTED_FORMATS:
                raise InvalidImageError(
                    "image must be a valid JPEG, PNG, or WebP image"
                )
            if getattr(source, "is_animated", False):
                raise InvalidImageError("animated images are not supported")
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise InvalidImageError("image dimensions are too large")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail(
                (max_dimension, max_dimension),
                Image.Resampling.LANCZOS,
            )
            return image
    except InvalidImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise InvalidImageError("image dimensions are too large") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError(
            "image must be a valid JPEG, PNG, or WebP image"
        ) from exc


def normalize_webp(data: bytes, max_dimension: int = 2048) -> bytes:
    """Decode image bytes and return metadata-free WebP bytes."""
    image = _normalized_rgb(data, max_dimension=max_dimension)
    output = BytesIO()
    try:
        image.save(output, format="WEBP", quality=90, method=6)
    except (OSError, ValueError) as exc:
        raise InvalidImageError(
            "image must be a valid JPEG, PNG, or WebP image"
        ) from exc
    return output.getvalue()


def normalize_png(data: bytes, max_dimension: int = 511) -> bytes:
    """Decode image bytes and return metadata-free PNG bytes."""
    image = _normalized_rgb(data, max_dimension=max_dimension)
    output = BytesIO()
    try:
        image.save(output, format="PNG", optimize=True)
    except (OSError, ValueError) as exc:
        raise InvalidImageError(
            "image must be a valid JPEG, PNG, or WebP image"
        ) from exc
    return output.getvalue()
