import importlib
import re
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

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
        "references/alice.webp",
        "references/0123.webp",
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


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (
            "local://illustrations/"
            "0123456789abcdef0123456789abcdef.webp",
            True,
        ),
        ("https://picsum.photos/example", False),
        ("local://illustrations/../image.webp", False),
        (None, False),
    ],
)
def test_managed_reference_detection(
    reference: str | None,
    expected: bool,
) -> None:
    storage = _storage_module()

    assert storage.is_managed_reference(reference) is expected


def test_r2_put_object_uploads_and_returns_stable_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage_module()
    client = MagicMock()
    monkeypatch.setattr(settings, "storage_provider", "r2")
    monkeypatch.setattr(settings, "r2_bucket", "story-forge-test")
    monkeypatch.setattr(storage, "_r2_client", lambda: client)
    key = "illustrations/0123456789abcdef0123456789abcdef.webp"

    reference = storage.put_object(b"private-webp", key, "image/webp")

    assert reference == f"r2://{key}"
    client.put_object.assert_called_once_with(
        Bucket="story-forge-test",
        Key=key,
        Body=b"private-webp",
        ContentType="image/webp",
    )


def test_r2_get_object_reads_private_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage_module()
    body = MagicMock()
    body.read.return_value = b"private-webp"
    client = MagicMock()
    client.get_object.return_value = {"Body": body}
    monkeypatch.setattr(settings, "r2_bucket", "story-forge-test")
    monkeypatch.setattr(storage, "_r2_client", lambda: client)
    reference = (
        "r2://illustrations/"
        "0123456789abcdef0123456789abcdef.webp"
    )

    result = storage.get_object(reference)

    assert result == b"private-webp"
    client.get_object.assert_called_once_with(
        Bucket="story-forge-test",
        Key="illustrations/0123456789abcdef0123456789abcdef.webp",
    )


def test_r2_delete_object_removes_private_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage_module()
    client = MagicMock()
    monkeypatch.setattr(settings, "r2_bucket", "story-forge-test")
    monkeypatch.setattr(storage, "_r2_client", lambda: client)
    reference = (
        "r2://illustrations/"
        "0123456789abcdef0123456789abcdef.webp"
    )

    storage.delete_object(reference)

    client.delete_object.assert_called_once_with(
        Bucket="story-forge-test",
        Key="illustrations/0123456789abcdef0123456789abcdef.webp",
    )


def test_r2_managed_reference_uses_the_same_key_validation() -> None:
    storage = _storage_module()

    assert storage.is_managed_reference(
        "r2://references/0123456789abcdef0123456789abcdef.webp"
    )
    assert not storage.is_managed_reference(
        "r2://references/../private.webp"
    )


def test_r2_client_uses_cloudflare_private_s3_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage_module()
    monkeypatch.setattr(settings, "r2_account_id", "account-test")
    monkeypatch.setattr(settings, "r2_access_key_id", "access-test")
    monkeypatch.setattr(settings, "r2_secret_access_key", "secret-test")
    monkeypatch.setattr(settings, "r2_bucket", "story-forge-test")
    storage._r2_client.cache_clear()

    with (
        patch(
            "botocore.config.Config",
            return_value="signature-config",
        ) as config_factory,
        patch("boto3.client", return_value=object()) as boto3_client,
    ):
        client = storage._r2_client()

    assert client is boto3_client.return_value
    config_factory.assert_called_once_with(signature_version="s3v4")
    boto3_client.assert_called_once_with(
        "s3",
        endpoint_url=(
            "https://account-test.r2.cloudflarestorage.com"
        ),
        aws_access_key_id="access-test",
        aws_secret_access_key="secret-test",
        config="signature-config",
        region_name="auto",
    )
    storage._r2_client.cache_clear()


def test_r2_client_requires_complete_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage_module()
    monkeypatch.setattr(settings, "r2_account_id", "account-test")
    monkeypatch.setattr(settings, "r2_access_key_id", None)
    monkeypatch.setattr(settings, "r2_secret_access_key", "secret-test")
    monkeypatch.setattr(settings, "r2_bucket", "story-forge-test")
    storage._r2_client.cache_clear()

    with pytest.raises(RuntimeError, match="not configured"):
        storage._r2_client()
