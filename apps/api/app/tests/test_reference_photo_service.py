import re
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Child, Parent
from app.services import reference_photos, storage


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 60), "#5b7cfa").save(output, format="PNG")
    return output.getvalue()


def _add_child_with_reference(
    db: Session,
    reference: str,
) -> Child:
    parent = Parent(email="parent@example.com")
    child = Child(
        parent=parent,
        name="Camille",
        age=7,
        language="en",
        reference_photo_ref=reference,
    )
    db.add(child)
    db.commit()
    return child


def test_replace_reference_photo_persists_normalized_replacement(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    previous_path = tmp_path / previous_reference.removeprefix("local://")

    with db_session_factory() as db:
        child = _add_child_with_reference(db, previous_reference)
        child_id = child.id

        reference_photos.replace_reference_photo(db, child, _image_bytes())

        new_reference = child.reference_photo_ref

    assert re.fullmatch(
        r"local://references/[0-9a-f]{32}\.webp",
        new_reference,
    )
    assert new_reference != previous_reference
    assert not previous_path.exists()
    new_path = tmp_path / new_reference.removeprefix("local://")
    with Image.open(new_path) as stored:
        assert stored.format == "WEBP"
        assert stored.size == (80, 60)
        assert stored.getexif() == {}
    with db_session_factory() as db:
        assert db.get(Child, child_id).reference_photo_ref == new_reference


def test_replace_reference_photo_preserves_reference_when_storage_fails(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )

    def fail_storage(*_args: object, **_kwargs: object) -> str:
        raise OSError("storage unavailable")

    monkeypatch.setattr(storage, "put_object", fail_storage)

    with db_session_factory() as db:
        child = _add_child_with_reference(db, previous_reference)

        with pytest.raises(
            reference_photos.ReferencePhotoStorageError
        ) as exc_info:
            reference_photos.replace_reference_photo(
                db,
                child,
                _image_bytes(),
            )

        assert isinstance(exc_info.value.__cause__, OSError)
        assert child.reference_photo_ref == previous_reference


def test_replace_reference_photo_rolls_back_and_removes_new_file(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    previous_path = tmp_path / previous_reference.removeprefix("local://")
    original_commit = Session.commit

    with db_session_factory() as db:
        child = _add_child_with_reference(db, previous_reference)

        def fail_replacement(session: Session) -> None:
            if child.reference_photo_ref != previous_reference:
                raise RuntimeError("database unavailable")
            original_commit(session)

        monkeypatch.setattr(Session, "commit", fail_replacement)

        with pytest.raises(
            reference_photos.ReferencePhotoPersistenceError
        ) as exc_info:
            reference_photos.replace_reference_photo(
                db,
                child,
                _image_bytes(),
            )

        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert child.reference_photo_ref == previous_reference
    assert previous_path.read_bytes() == b"previous-photo"
    assert list(tmp_path.rglob("*.webp")) == [previous_path]


def test_replace_reference_photo_does_not_fail_when_old_cleanup_fails(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    previous_path = tmp_path / previous_reference.removeprefix("local://")

    def fail_cleanup(stored_reference: str) -> None:
        assert stored_reference == previous_reference
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(storage, "delete_object", fail_cleanup)

    with db_session_factory() as db:
        child = _add_child_with_reference(db, previous_reference)
        child_id = child.id

        reference_photos.replace_reference_photo(db, child, _image_bytes())

        new_reference = child.reference_photo_ref

    assert previous_path.read_bytes() == b"previous-photo"
    assert storage.get_object(new_reference)
    with db_session_factory() as db:
        assert db.get(Child, child_id).reference_photo_ref == new_reference


def test_replace_reference_photo_preserves_database_error_when_cleanup_fails(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    previous_reference = storage.put_object(
        b"previous-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    original_commit = Session.commit

    with db_session_factory() as db:
        child = _add_child_with_reference(db, previous_reference)

        def fail_replacement(session: Session) -> None:
            if child.reference_photo_ref != previous_reference:
                raise RuntimeError("database unavailable")
            original_commit(session)

        def fail_cleanup(_stored_reference: str) -> None:
            raise OSError("cleanup unavailable")

        monkeypatch.setattr(Session, "commit", fail_replacement)
        monkeypatch.setattr(storage, "delete_object", fail_cleanup)

        with pytest.raises(
            reference_photos.ReferencePhotoPersistenceError
        ) as exc_info:
            reference_photos.replace_reference_photo(
                db,
                child,
                _image_bytes(),
            )

        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert child.reference_photo_ref == previous_reference
    assert len(list(tmp_path.rglob("*.webp"))) == 2


def test_remove_reference_photo_clears_database_and_deletes_file(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    reference = storage.put_object(
        b"private-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    path = tmp_path / reference.removeprefix("local://")

    with db_session_factory() as db:
        child = _add_child_with_reference(db, reference)
        child_id = child.id

        reference_photos.remove_reference_photo(db, child)

    with db_session_factory() as db:
        assert db.get(Child, child_id).reference_photo_ref is None
    assert not path.exists()


def test_remove_reference_photo_rolls_back_when_database_commit_fails(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    reference = storage.put_object(
        b"private-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    path = tmp_path / reference.removeprefix("local://")
    original_commit = Session.commit

    with db_session_factory() as db:
        child = _add_child_with_reference(db, reference)

        def fail_reference_removal(session: Session) -> None:
            if child.reference_photo_ref is None:
                raise RuntimeError("database unavailable")
            original_commit(session)

        monkeypatch.setattr(Session, "commit", fail_reference_removal)

        with pytest.raises(
            reference_photos.ReferencePhotoPersistenceError
        ) as exc_info:
            reference_photos.remove_reference_photo(db, child)

        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert child.reference_photo_ref == reference
    assert path.read_bytes() == b"private-photo"


def test_remove_reference_photo_does_not_fail_when_file_cleanup_fails(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "asset_cache_dir", tmp_path)
    reference = storage.put_object(
        b"private-photo",
        "references/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
        "image/webp",
    )
    path = tmp_path / reference.removeprefix("local://")

    def fail_cleanup(stored_reference: str) -> None:
        assert stored_reference == reference
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(storage, "delete_object", fail_cleanup)

    with db_session_factory() as db:
        child = _add_child_with_reference(db, reference)
        child_id = child.id

        reference_photos.remove_reference_photo(db, child)

    with db_session_factory() as db:
        assert db.get(Child, child_id).reference_photo_ref is None
    assert path.read_bytes() == b"private-photo"
