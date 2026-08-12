import re
from functools import lru_cache
from uuid import uuid4

from app.config import settings


LOCAL_SCHEME = "local://"
R2_SCHEME = "r2://"
ASSET_CATEGORIES = frozenset({"references", "illustrations", "narration"})
ASSET_FILENAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]+$")
ASSET_SUFFIX_PATTERN = re.compile(r"^\.[a-z0-9]+$")
LOCAL_NARRATION_FILENAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.mp3$")


def _validate_asset_key(key: str) -> str:
    parts = key.split("/")
    if (
        len(parts) != 2
        or parts[0] not in ASSET_CATEGORIES
        or ASSET_FILENAME_PATTERN.fullmatch(parts[1]) is None
    ):
        raise ValueError("Asset key has an invalid asset path.")
    return key


def _reference_parts(reference: str) -> tuple[str, str]:
    scheme = next(
        (
            candidate
            for candidate in (LOCAL_SCHEME, R2_SCHEME)
            if reference.startswith(candidate)
        ),
        None,
    )
    if scheme is None:
        raise ValueError("Reference is an invalid storage reference.")
    try:
        key = _validate_asset_key(reference.removeprefix(scheme))
    except ValueError:
        raise ValueError(
            "Reference is an invalid storage reference."
        ) from None
    return scheme, key


def _local_narration_filename(reference: str) -> str | None:
    prefix = f"{settings.api_base_url.rstrip('/')}/media/narration/"
    if not reference.startswith(prefix):
        return None
    filename = reference.removeprefix(prefix)
    if LOCAL_NARRATION_FILENAME_PATTERN.fullmatch(filename) is None:
        return None
    return filename


def _r2_bucket() -> str:
    if not settings.r2_bucket:
        raise RuntimeError("R2 storage provider is not configured.")
    return settings.r2_bucket


@lru_cache(maxsize=1)
def _r2_client():
    if not all(
        (
            settings.r2_account_id,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
            settings.r2_bucket,
        )
    ):
        raise RuntimeError("R2 storage provider is not configured.")

    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=(
            f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
        ),
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


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
    provider = settings.storage_provider.strip().lower()
    if provider == "r2":
        _r2_client().put_object(
            Bucket=_r2_bucket(),
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"{R2_SCHEME}{key}"
    if provider != "local":
        raise ValueError(f"Unsupported storage provider: {provider}")
    path = settings.asset_cache_dir / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"{LOCAL_SCHEME}{key}"


def get_object(reference: str) -> bytes:
    narration_filename = _local_narration_filename(reference)
    if narration_filename is not None:
        return (settings.narration_cache_dir / narration_filename).read_bytes()
    scheme, key = _reference_parts(reference)
    if scheme == R2_SCHEME:
        response = _r2_client().get_object(
            Bucket=_r2_bucket(),
            Key=key,
        )
        return response["Body"].read()
    return (settings.asset_cache_dir / key).read_bytes()


def resolve_url(reference: str) -> str:
    if _local_narration_filename(reference) is not None:
        return reference
    scheme, key = _reference_parts(reference)
    if scheme == LOCAL_SCHEME:
        return reference
    return _r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _r2_bucket(), "Key": key},
        ExpiresIn=settings.r2_presign_ttl_seconds,
    )


def is_managed_reference(reference: str | None) -> bool:
    if not reference:
        return False
    if _local_narration_filename(reference) is not None:
        return True
    try:
        _reference_parts(reference)
    except ValueError:
        return False
    return True


def delete_object(reference: str) -> None:
    narration_filename = _local_narration_filename(reference)
    if narration_filename is not None:
        (settings.narration_cache_dir / narration_filename).unlink(
            missing_ok=True
        )
        return
    scheme, key = _reference_parts(reference)
    if scheme == R2_SCHEME:
        _r2_client().delete_object(
            Bucket=_r2_bucket(),
            Key=key,
        )
        return
    (settings.asset_cache_dir / key).unlink(missing_ok=True)
