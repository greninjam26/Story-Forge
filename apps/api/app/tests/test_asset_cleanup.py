import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import main as main_module
from app.main import app
from app.models import (
    Child,
    Parent,
    PendingAssetDeletion,
    Story,
    StoryPage,
)
from app.services import asset_cleanup, storage


def test_queue_references_keeps_unique_managed_assets(
    db_session_factory: sessionmaker[Session],
) -> None:
    local_reference = (
        "local://illustrations/"
        "0123456789abcdef0123456789abcdef.webp"
    )
    r2_reference = (
        "r2://narration/"
        "abcdef0123456789abcdef0123456789.mp3"
    )

    with db_session_factory() as db:
        queued = asset_cleanup.queue_references(
            db,
            [
                local_reference,
                r2_reference,
                local_reference,
                "https://picsum.photos/stub",
                None,
            ],
        )
        db.commit()

        references = set(
            db.scalars(select(PendingAssetDeletion.reference))
        )

    assert len(queued) == 2
    assert references == {local_reference, r2_reference}


def test_queue_child_assets_includes_reference_and_story_pages(
    db_session_factory: sessionmaker[Session],
) -> None:
    references = [
        "r2://references/0123456789abcdef0123456789abcdef.webp",
        "r2://illustrations/abcdef0123456789abcdef0123456789.webp",
        "local://narration/11111111111111111111111111111111.mp3",
    ]
    child = Child(
        parent=Parent(email="parent@example.com"),
        name="Camille",
        age=7,
        reference_photo_ref=references[0],
        stories=[
            Story(
                event_text="Camille found a shell.",
                language="en",
                pages=[
                    StoryPage(
                        page_number=1,
                        text="A shell by the water.",
                        image_url=references[1],
                        audio_url=references[2],
                    )
                ],
            )
        ],
    )

    with db_session_factory() as db:
        queued = asset_cleanup.queue_child_assets(db, child)
        db.commit()

        saved_references = set(
            db.scalars(select(PendingAssetDeletion.reference))
        )

    assert len(queued) == 3
    assert saved_references == set(references)


def test_process_pending_deletions_removes_successful_job(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = (
        "r2://illustrations/"
        "0123456789abcdef0123456789abcdef.webp"
    )
    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", deleted.append)

    with db_session_factory() as db:
        db.add(PendingAssetDeletion(reference=reference))
        db.commit()

        result = asset_cleanup.process_pending_deletions(db)

        assert result.deleted == 1
        assert result.failed == 0
        assert list(db.scalars(select(PendingAssetDeletion))) == []

    assert deleted == [reference]


def test_failed_deletion_is_scheduled_with_exponential_backoff(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def fail_deletion(_reference: str) -> None:
        raise RuntimeError("secret provider detail")

    monkeypatch.setattr(storage, "delete_object", fail_deletion)

    with db_session_factory() as db:
        pending = PendingAssetDeletion(
            reference=(
                "r2://illustrations/"
                "0123456789abcdef0123456789abcdef.webp"
            )
        )
        db.add(pending)
        db.commit()

        result = asset_cleanup.process_pending_deletions(db, now=now)

        assert result.deleted == 0
        assert result.failed == 1
        assert pending.attempts == 1
        assert pending.last_error == "RuntimeError"
        assert pending.last_attempt_at == now
        assert pending.next_attempt_at == now + timedelta(minutes=1)
        assert pending.terminal_at is None


def test_repeated_failure_becomes_terminal(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def fail_deletion(_reference: str) -> None:
        raise RuntimeError("R2 unavailable")

    monkeypatch.setattr(storage, "delete_object", fail_deletion)

    with db_session_factory() as db:
        pending = PendingAssetDeletion(
            reference=(
                "r2://illustrations/"
                "0123456789abcdef0123456789abcdef.webp"
            ),
            attempts=11,
        )
        db.add(pending)
        db.commit()

        result = asset_cleanup.process_pending_deletions(db, now=now)

        assert result.failed == 1
        assert pending.attempts == 12
        assert pending.last_attempt_at == now
        assert pending.next_attempt_at is None
        assert pending.terminal_at == now


def test_processor_skips_future_and_terminal_jobs(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    attempted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", attempted.append)

    with db_session_factory() as db:
        db.add_all(
            [
                PendingAssetDeletion(
                    reference=(
                        "r2://illustrations/"
                        "0123456789abcdef0123456789abcdef.webp"
                    ),
                    next_attempt_at=now + timedelta(minutes=1),
                ),
                PendingAssetDeletion(
                    reference=(
                        "r2://illustrations/"
                        "abcdef0123456789abcdef0123456789.webp"
                    ),
                    terminal_at=now - timedelta(minutes=1),
                ),
            ]
        )
        db.commit()

        result = asset_cleanup.process_pending_deletions(db, now=now)

        assert result.deleted == 0
        assert result.failed == 0
        assert db.scalar(
            select(func.count()).select_from(PendingAssetDeletion)
        ) == 2

    assert attempted == []


def test_try_process_pending_deletions_does_not_break_user_operation(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_processing(_db: Session) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        asset_cleanup,
        "process_pending_deletions",
        fail_processing,
    )

    with db_session_factory() as db:
        result = asset_cleanup.try_process_pending_deletions(db)

    assert result is None


def test_api_worker_processes_pending_deletion_on_startup(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = (
        "r2://illustrations/"
        "0123456789abcdef0123456789abcdef.webp"
    )
    with db_session_factory() as db:
        db.add(PendingAssetDeletion(reference=reference))
        db.commit()

    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", deleted.append)
    monkeypatch.setattr(
        app.state,
        "asset_cleanup_session_factory",
        db_session_factory,
        raising=False,
    )
    monkeypatch.setattr(
        main_module.settings,
        "asset_cleanup_worker_enabled",
        True,
    )
    monkeypatch.setattr(
        main_module.settings,
        "asset_cleanup_worker_interval_seconds",
        0.01,
    )

    with TestClient(app):
        deadline = time.monotonic() + 0.5
        while not deleted and time.monotonic() < deadline:
            time.sleep(0.01)

    assert deleted == [reference]
    with db_session_factory() as db:
        assert db.scalar(
            select(func.count()).select_from(PendingAssetDeletion)
        ) == 0


def test_api_worker_processes_deletions_periodically(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = (
        "r2://illustrations/"
        "abcdef0123456789abcdef0123456789.webp"
    )
    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", deleted.append)
    monkeypatch.setattr(
        app.state,
        "asset_cleanup_session_factory",
        db_session_factory,
        raising=False,
    )
    monkeypatch.setattr(
        main_module.settings,
        "asset_cleanup_worker_enabled",
        True,
    )
    monkeypatch.setattr(
        main_module.settings,
        "asset_cleanup_worker_interval_seconds",
        0.01,
    )

    with TestClient(app):
        with db_session_factory() as db:
            db.add(PendingAssetDeletion(reference=reference))
            db.commit()

        deadline = time.monotonic() + 0.5
        while not deleted and time.monotonic() < deadline:
            time.sleep(0.01)

    assert deleted == [reference]
    with db_session_factory() as db:
        assert db.scalar(
            select(func.count()).select_from(PendingAssetDeletion)
        ) == 0
