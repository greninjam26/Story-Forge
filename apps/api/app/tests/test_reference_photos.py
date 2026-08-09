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
from app.services import storage


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


def test_storage_failure_preserves_previous_reference(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    previous_reference = (
        "local://references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp"
    )
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = previous_reference
        db.commit()

    def fail_storage(*_args: object, **_kwargs: object) -> str:
        raise OSError("storage unavailable")

    monkeypatch.setattr(storage, "put_object", fail_storage)

    response = client.put(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo",
        files={"photo": ("child.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 503
    with db_session_factory() as db:
        assert db.get(
            Child,
            UUID(child["id"]),
        ).reference_photo_ref == previous_reference


def test_database_failure_removes_new_file_and_preserves_previous_photo(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = previous_reference
        db.commit()

    original_commit = Session.commit

    def fail_reference_update(db: Session) -> None:
        if any(
            isinstance(row, Child)
            and row.reference_photo_ref != previous_reference
            for row in db.dirty
        ):
            raise RuntimeError("database unavailable")
        original_commit(db)

    monkeypatch.setattr(Session, "commit", fail_reference_update)

    response = client.put(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo",
        files={"photo": ("child.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 503
    with db_session_factory() as db:
        assert db.get(
            Child,
            UUID(child["id"]),
        ).reference_photo_ref == previous_reference
    assert storage.get_object(previous_reference) == b"previous-photo"
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [
        tmp_path / previous_reference.removeprefix("local://")
    ]


def test_successful_replacement_removes_previous_photo(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    previous_path = tmp_path / previous_reference.removeprefix("local://")
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = previous_reference
        db.commit()

    response = client.put(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo",
        files={"photo": ("child.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 204
    with db_session_factory() as db:
        new_reference = db.get(
            Child,
            UUID(child["id"]),
        ).reference_photo_ref
    assert new_reference != previous_reference
    assert not previous_path.exists()
    with Image.open(tmp_path / new_reference.removeprefix("local://")) as stored:
        assert stored.format == "WEBP"


def test_previous_photo_cleanup_failure_does_not_hide_success(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = previous_reference
        db.commit()

    def fail_cleanup(reference: str) -> None:
        assert reference == previous_reference
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(storage, "delete_object", fail_cleanup)

    response = client.put(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo",
        files={"photo": ("child.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 204
    with db_session_factory() as db:
        new_reference = db.get(
            Child,
            UUID(child["id"]),
        ).reference_photo_ref
    assert new_reference != previous_reference
    assert storage.get_object(new_reference)


def test_delete_reference_photo_clears_reference_and_removes_file(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    reference = storage.put_object(
        b"private-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    path = tmp_path / reference.removeprefix("local://")
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = reference
        db.commit()

    response = client.delete(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo"
    )

    assert response.status_code == 204
    assert response.content == b""
    with db_session_factory() as db:
        assert db.get(Child, UUID(child["id"])).reference_photo_ref is None
    assert not path.exists()


def test_delete_reference_photo_database_failure_preserves_photo(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    reference = storage.put_object(
        b"private-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    path = tmp_path / reference.removeprefix("local://")
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = reference
        db.commit()

    original_commit = Session.commit

    def fail_reference_removal(db: Session) -> None:
        if any(
            isinstance(row, Child) and row.reference_photo_ref is None
            for row in db.dirty
        ):
            raise RuntimeError("database unavailable")
        original_commit(db)

    monkeypatch.setattr(Session, "commit", fail_reference_removal)

    response = client.delete(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo"
    )

    assert response.status_code == 503
    with db_session_factory() as db:
        assert db.get(
            Child,
            UUID(child["id"]),
        ).reference_photo_ref == reference
    assert path.read_bytes() == b"private-photo"


def test_delete_reference_photo_cleanup_failure_does_not_hide_success(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    reference = storage.put_object(
        b"private-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    path = tmp_path / reference.removeprefix("local://")
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = reference
        db.commit()

    def fail_cleanup(stored_reference: str) -> None:
        assert stored_reference == reference
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(storage, "delete_object", fail_cleanup)

    response = client.delete(
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo"
    )

    assert response.status_code == 204
    with db_session_factory() as db:
        assert db.get(Child, UUID(child["id"])).reference_photo_ref is None
    assert path.read_bytes() == b"private-photo"


def test_delete_reference_photo_is_idempotent(
    client: TestClient,
) -> None:
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    url = (
        f"/parents/{parent['id']}/children/{child['id']}/reference-photo"
    )

    first_response = client.delete(url)
    second_response = client.delete(url)

    assert first_response.status_code == 204
    assert second_response.status_code == 204


def test_delete_reference_photo_is_scoped_to_parent(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    owner = _create_parent(client, "owner@example.com")
    other_parent = _create_parent(client, "other@example.com")
    child = _create_child(client, owner["id"])
    reference = storage.put_object(
        b"private-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    path = tmp_path / reference.removeprefix("local://")
    with db_session_factory() as db:
        row = db.get(Child, UUID(child["id"]))
        row.reference_photo_ref = reference
        db.commit()

    response = client.delete(
        f"/parents/{other_parent['id']}/children/{child['id']}/reference-photo"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}
    with db_session_factory() as db:
        assert db.get(
            Child,
            UUID(child["id"]),
        ).reference_photo_ref == reference
    assert path.read_bytes() == b"private-photo"
