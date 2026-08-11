import re
from uuid import uuid4

from app.config import settings


LOCAL_SCHEME = "local://"
ASSET_CATEGORIES = frozenset({"references", "illustrations", "narration"})
ASSET_FILENAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]+$")
ASSET_SUFFIX_PATTERN = re.compile(r"^\.[a-z0-9]+$")


def _validate_asset_key(key: str) -> str:
    parts = key.split("/")
    if (
        len(parts) != 2
        or parts[0] not in ASSET_CATEGORIES
        or ASSET_FILENAME_PATTERN.fullmatch(parts[1]) is None
    ):
        raise ValueError("Asset key has an invalid asset path.")
    return key


def _key_from_reference(reference: str) -> str:
    if not reference.startswith(LOCAL_SCHEME):
        raise ValueError("Reference is an invalid storage reference.")
    try:
        return _validate_asset_key(reference.removeprefix(LOCAL_SCHEME))
    except ValueError:
        raise ValueError(
            "Reference is an invalid storage reference."
        ) from None


def new_key(category: str, suffix: str) -> str:
    if category not in ASSET_CATEGORIES:
        raise ValueError("Category is an invalid asset category.")
    if ASSET_SUFFIX_PATTERN.fullmatch(suffix) is None:
        raise ValueError("Suffix is an invalid asset suffix.")
    return f"{category}/{uuid4().hex}{suffix}"


def put_object(data: bytes, key: str, content_type: str) -> str:
    if not data:
        raise ValueError("Asset data cannot be empty.")
    if not content_type.strip():
        raise ValueError("Asset content type cannot be empty.")
    key = _validate_asset_key(key)
    path = settings.asset_cache_dir / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"{LOCAL_SCHEME}{key}"


def get_object(reference: str) -> bytes:
    key = _key_from_reference(reference)
    return (settings.asset_cache_dir / key).read_bytes()


def is_managed_reference(reference: str | None) -> bool:
    if not reference:
        return False
    try:
        _key_from_reference(reference)
    except ValueError:
        return False
    return True


def delete_object(reference: str) -> None:
    key = _key_from_reference(reference)
    (settings.asset_cache_dir / key).unlink(missing_ok=True)
