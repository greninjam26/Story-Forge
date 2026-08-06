import importlib
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.config import settings


def _storage_module() -> ModuleType:
    return importlib.import_module("app.services.storage")


def test_local_private_asset_round_trip_uses_opaque_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    storage = _storage_module()

    key = storage.new_key("references", ".webp")
    reference = storage.put_object(
        b"private-webp",
        key,
        "image/webp",
    )

    assert re.fullmatch(r"references/[0-9a-f]{32}\.webp", key)
    assert reference == f"local://{key}"
    assert storage.get_object(reference) == b"private-webp"
    assert (tmp_path / key).read_bytes() == b"private-webp"


@pytest.mark.parametrize(
    "category",
    ["references", "illustrations", "narration"],
)
def test_new_key_supports_private_asset_categories(category: str) -> None:
    storage = _storage_module()

    key = storage.new_key(category, ".webp")

    assert re.fullmatch(rf"{category}/[0-9a-f]{{32}}\.webp", key)


@pytest.mark.parametrize(
    ("category", "suffix"),
    [
        ("unknown", ".webp"),
        ("references", "webp"),
        ("references", ".tar.gz"),
        ("references", "/photo.webp"),
    ],
)
def test_new_key_rejects_unsupported_categories_and_suffixes(
    category: str,
    suffix: str,
) -> None:
    storage = _storage_module()

    with pytest.raises(ValueError, match="invalid asset"):
        storage.new_key(category, suffix)


@pytest.mark.parametrize(
    "key",
    [
        "unknown/photo.webp",
        "references/../photo.webp",
        "references/nested/photo.webp",
        "references/photo?.webp",
    ],
)
def test_put_object_rejects_untrusted_asset_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    storage = _storage_module()

    with pytest.raises(ValueError, match="invalid asset path"):
        storage.put_object(b"private-webp", key, "image/webp")

    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.com/photo.webp",
        "local://unknown/photo.webp",
        "local://references/../photo.webp",
        "local://references/nested/photo.webp",
    ],
)
def test_storage_rejects_untrusted_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    storage = _storage_module()

    with pytest.raises(ValueError, match="invalid storage reference"):
        storage.get_object(reference)
    with pytest.raises(ValueError, match="invalid storage reference"):
        storage.delete_object(reference)


@pytest.mark.parametrize(
    ("data", "content_type"),
    [(b"", "image/webp"), (b"private-webp", "")],
)
def test_put_object_rejects_incomplete_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    content_type: str,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    storage = _storage_module()

    with pytest.raises(ValueError, match="cannot be empty"):
        storage.put_object(
            data,
            "references/0123456789abcdef0123456789abcdef.webp",
            content_type,
        )


def test_delete_object_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    storage = _storage_module()
    key = "references/0123456789abcdef0123456789abcdef.webp"
    reference = storage.put_object(b"private-webp", key, "image/webp")

    storage.delete_object(reference)
    storage.delete_object(reference)

    assert not (tmp_path / key).exists()
    with pytest.raises(FileNotFoundError):
        storage.get_object(reference)
