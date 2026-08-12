import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import narration_storage, storage


def test_store_narration_mp3_persists_bytes_behind_an_opaque_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)
    monkeypatch.setattr(settings, "api_base_url", "https://api.example.test/")

    url = narration_storage.store_narration_mp3(b"ID3audio")

    match = re.fullmatch(
        r"https://api\.example\.test/media/narration/([0-9a-f]{32})\.mp3",
        url,
    )
    assert match is not None
    token = match.group(1)
    assert (tmp_path / f"{token}.mp3").read_bytes() == b"ID3audio"
    assert narration_storage.read_narration_mp3(token) == b"ID3audio"


def test_store_narration_mp3_uses_unique_opaque_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)

    first = narration_storage.store_narration_mp3(b"ID3audio")
    second = narration_storage.store_narration_mp3(b"ID3audio")

    assert second != first
    assert len(list(tmp_path.glob("*.mp3"))) == 2


def test_store_narration_mp3_uses_r2_storage_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    monkeypatch.setattr(settings, "storage_provider", "r2")
    monkeypatch.setattr(settings, "r2_bucket", "story-forge-test")
    monkeypatch.setattr(storage, "_r2_client", lambda: client)

    reference = narration_storage.store_narration_mp3(b"ID3audio")

    assert re.fullmatch(
        r"r2://narration/[0-9a-f]{32}\.mp3",
        reference,
    )
    key = reference.removeprefix("r2://")
    client.put_object.assert_called_once_with(
        Bucket="story-forge-test",
        Key=key,
        Body=b"ID3audio",
        ContentType="audio/mpeg",
    )


def test_narration_storage_rejects_empty_audio_and_invalid_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)

    with pytest.raises(ValueError, match="cannot be empty"):
        narration_storage.store_narration_mp3(b"")
    with pytest.raises(ValueError, match="invalid"):
        narration_storage.read_narration_mp3("../private")


def test_generated_narration_endpoint_serves_cached_mp3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)
    url = narration_storage.store_narration_mp3(b"ID3audio")

    response = client.get(url)

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == (
        "private, max-age=31536000, immutable"
    )
    assert response.content == b"ID3audio"


def test_generated_narration_endpoint_returns_404_for_missing_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setattr(settings, "narration_cache_dir", tmp_path)

    response = client.get(f"/media/narration/{'0' * 32}.mp3")

    assert response.status_code == 404
