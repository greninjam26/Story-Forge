import importlib
from io import BytesIO
from types import ModuleType

import pytest
from PIL import Image


def _image_files_module() -> ModuleType:
    return importlib.import_module("app.services.image_files")


def _image_bytes(
    image_format: str = "PNG",
    size: tuple[int, int] = (80, 60),
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "#5b7cfa").save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_normalize_webp_returns_metadata_free_webp(image_format: str) -> None:
    image_files = _image_files_module()

    normalized = image_files.normalize_webp(_image_bytes(image_format))

    with Image.open(BytesIO(normalized)) as result:
        assert result.format == "WEBP"
        assert result.size == (80, 60)
        assert result.getexif() == {}


def test_normalize_webp_rejects_corrupt_bytes() -> None:
    image_files = _image_files_module()

    with pytest.raises(
        image_files.InvalidImageError,
        match="valid JPEG, PNG, or WebP",
    ):
        image_files.normalize_webp(b"not an image")


def test_normalize_webp_rejects_unsupported_image_format() -> None:
    image_files = _image_files_module()

    with pytest.raises(
        image_files.InvalidImageError,
        match="valid JPEG, PNG, or WebP",
    ):
        image_files.normalize_webp(_image_bytes("BMP"))


def test_normalize_webp_rejects_animation() -> None:
    image_files = _image_files_module()
    output = BytesIO()
    frames = [
        Image.new("RGB", (16, 16), "red"),
        Image.new("RGB", (16, 16), "blue"),
    ]
    frames[0].save(
        output,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=100,
    )

    with pytest.raises(image_files.InvalidImageError, match="animated"):
        image_files.normalize_webp(output.getvalue())


def test_normalize_webp_constrains_large_dimensions() -> None:
    image_files = _image_files_module()

    normalized = image_files.normalize_webp(
        _image_bytes(size=(160, 80)),
        max_dimension=64,
    )

    with Image.open(BytesIO(normalized)) as result:
        assert result.size == (64, 32)


def test_normalize_webp_rejects_excessive_source_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_files = _image_files_module()
    monkeypatch.setattr(image_files, "MAX_SOURCE_PIXELS", 1_000)

    with pytest.raises(
        image_files.InvalidImageError,
        match="dimensions are too large",
    ):
        image_files.normalize_webp(_image_bytes(size=(80, 60)))


def test_normalize_webp_handles_pillow_decompression_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_files = _image_files_module()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000)

    with pytest.raises(
        image_files.InvalidImageError,
        match="dimensions are too large",
    ):
        image_files.normalize_webp(_image_bytes(size=(80, 60)))


def test_normalize_webp_applies_exif_orientation() -> None:
    image_files = _image_files_module()
    output = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), "#5b7cfa").save(
        output,
        format="JPEG",
        exif=exif,
    )

    normalized = image_files.normalize_webp(output.getvalue())

    with Image.open(BytesIO(normalized)) as result:
        assert result.size == (20, 40)
        assert result.getexif() == {}


@pytest.mark.parametrize("max_dimension", [0, -1])
def test_normalize_webp_rejects_non_positive_max_dimension(
    max_dimension: int,
) -> None:
    image_files = _image_files_module()

    with pytest.raises(ValueError, match="max_dimension must be positive"):
        image_files.normalize_webp(
            _image_bytes(),
            max_dimension=max_dimension,
        )
