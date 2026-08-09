import re
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Child


MAX_REFERENCE_PHOTO_BYTES = 10 * 1024 * 1024


def _create_parent(
    client: TestClient,
    email: str = "parent@example.com",
) -> dict[str, Any]:
    response = client.post(
        "/parents",
        json={"email": email},
    )
    assert response.status_code == 201
    return response.json()


def _create_child(client: TestClient, parent_id: str) -> dict[str, Any]:
    response = client.post(
        f"/parents/{parent_id}/children",
        json={"name": "Camille", "age": 7},
    )
    assert response.status_code == 201
    return response.json()


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 60), "#5b7cfa").save(output, format="PNG")
    return output.getvalue()


def test_upload_reference_photo_normalizes_stores_and_persists(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])

    response = client.put(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo",
        files={"photo": ("child.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 204
    assert response.content == b""
    with db_session_factory() as db:
        reference = db.get(
            Child,
            UUID(child["id"]),
        ).reference_photo_ref
    assert re.fullmatch(
        r"local://references/[0-9a-f]{32}\.webp",
        reference,
    )
    with Image.open(tmp_path / reference.removeprefix("local://")) as stored:
        assert stored.format == "WEBP"
        assert stored.size == (80, 60)
        assert stored.getexif() == {}


def test_upload_reference_photo_rejects_corrupt_content(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])

    response = client.put(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo",
        files={"photo": ("child.png", b"not an image", "image/png")},
    )

    assert response.status_code == 422
    with db_session_factory() as db:
        assert db.get(Child, UUID(child["id"])).reference_photo_ref is None
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_upload_reference_photo_rejects_oversized_file(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])

    response = client.put(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo",
        files={
            "photo": (
                "child.png",
                b"x" * (MAX_REFERENCE_PHOTO_BYTES + 1),
                "image/png",
            )
        },
    )

    assert response.status_code == 413
    with db_session_factory() as db:
        assert db.get(Child, UUID(child["id"])).reference_photo_ref is None
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_oversized_raw_upload_is_rejected_before_child_lookup(
    client: TestClient,
) -> None:
    response = client.put(
        f"/parents/{uuid4()}/children/{uuid4()}/reference-photo",
        files={
            "photo": (
                "child.png",
                b"x" * (MAX_REFERENCE_PHOTO_BYTES + 128 * 1024),
                "image/png",
            )
        },
    )

    assert response.status_code == 413


def test_upload_reference_photo_is_scoped_to_parent(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    owner = _create_parent(client, "owner@example.com")
    other_parent = _create_parent(client, "other@example.com")
    child = _create_child(client, owner["id"])

    response = client.put(
        f"/parents/{other_parent['id']}/children/{child['id']}/reference-photo",
        files={"photo": ("child.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}
    with db_session_factory() as db:
        assert db.get(Child, UUID(child["id"])).reference_photo_ref is None
    assert not any(path.is_file() for path in tmp_path.rglob("*"))
