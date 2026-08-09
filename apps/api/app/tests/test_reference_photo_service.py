from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Child, Parent
from app.services import reference_photos, storage


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
