import re
from uuid import uuid4

from app.config import settings


NARRATION_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def store_narration_mp3(audio_bytes: bytes) -> str:
    if not audio_bytes:
        raise ValueError("Narration audio cannot be empty.")

    token = uuid4().hex
    settings.narration_cache_dir.mkdir(parents=True, exist_ok=True)
    path = settings.narration_cache_dir / f"{token}.mp3"
    path.write_bytes(audio_bytes)
    return (
        f"{settings.api_base_url.rstrip('/')}"
        f"/media/narration/{token}.mp3"
    )


def read_narration_mp3(token: str) -> bytes:
    if NARRATION_TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError("Narration token is invalid.")
    return (settings.narration_cache_dir / f"{token}.mp3").read_bytes()
