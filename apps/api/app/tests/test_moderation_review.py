from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, create_db_engine
from app.models import (
    Child,
    ModerationRecord,
    Parent,
    Story,
    StoryStatus,
)


def _review_cli():
    return importlib.import_module("app.moderation_review")


def _record(
    db: Session,
    *,
    suffix: str,
    created_at: datetime,
    review_status: str = "pending",
) -> ModerationRecord:
    parent = Parent(email=f"review-{suffix}@example.com")
    child = Child(
        parent=parent,
        name=f"Child {suffix}",
        age=7,
        interests="stars",
        language="en",
    )
    story = Story(
        child=child,
        event_text=f"PRIVATE EVENT {suffix}",
        title="",
        language="en",
        status=StoryStatus.REJECTED,
        failure_reason="safety_generated_page_2_blocked",
        safety_reason="violence",
    )
    record = ModerationRecord(
        story=story,
        provider="openai",
        model="omni-moderation-test",
        provider_request_id=f"req-{suffix}",
        flagged_item_kind="page",
        flagged_page_number=2,
        flagged_text=f"RETAINED FLAGGED TEXT {suffix}",
        categories=["violence", "new-category"],
        category_scores={"violence": 0.9, "new-category": 0.8},
        review_status=review_status,
        created_at=created_at,
    )
    db.add(record)
    db.commit()
    return record


def test_list_prints_pending_metadata_oldest_first_without_private_text(
    db_session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 8, 13, 12, 0, 0)
    with db_session_factory() as db:
        oldest = _record(db, suffix="old", created_at=now)
        newest = _record(
            db,
            suffix="new",
            created_at=now + timedelta(minutes=1),
        )
        _record(
            db,
            suffix="reviewed",
            created_at=now - timedelta(minutes=1),
            review_status="confirmed",
        )
        expected_ids = [str(oldest.id), str(newest.id)]

    assert _review_cli().main(
        ["list"], session_factory=db_session_factory
    ) == 0

    output = capsys.readouterr().out
    rows = [json.loads(line) for line in output.splitlines()]
    assert [row["id"] for row in rows] == expected_ids
    assert all(row["review_status"] == "pending" for row in rows)
    assert all(row["categories"] == ["violence", "new-category"] for row in rows)
    assert "PRIVATE EVENT" not in output
    assert "RETAINED FLAGGED TEXT" not in output
    assert "category_scores" not in output


def test_show_is_the_only_command_that_prints_flagged_text(
    db_session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with db_session_factory() as db:
        record = _record(
            db,
            suffix="show",
            created_at=datetime(2026, 8, 13, 12, 0, 0),
        )
        record_id = str(record.id)
        story_id = str(record.story_id)

    assert _review_cli().main(
        ["show", record_id], session_factory=db_session_factory
    ) == 0

    row = json.loads(capsys.readouterr().out)
    assert row == {
        "categories": ["violence", "new-category"],
        "created_at": "2026-08-13T12:00:00",
        "flagged_item_kind": "page",
        "flagged_page_number": 2,
        "flagged_text": "RETAINED FLAGGED TEXT show",
        "id": record_id,
        "model": "omni-moderation-test",
        "provider": "openai",
        "provider_request_id": "req-show",
        "review_status": "pending",
        "story_id": story_id,
    }


def test_review_records_one_decision_without_overwriting_it(
    db_session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with db_session_factory() as db:
        record = _record(
            db,
            suffix="decision",
            created_at=datetime(2026, 8, 13, 12, 0, 0),
        )
        record_id = str(record.id)

    assert _review_cli().main(
        ["review", record_id, "--decision", "confirmed"],
        session_factory=db_session_factory,
    ) == 0
    assert json.loads(capsys.readouterr().out) == {
        "id": record_id,
        "review_status": "confirmed",
    }

    with db_session_factory() as db:
        reviewed = db.get(ModerationRecord, record.id)
        assert reviewed is not None
        assert reviewed.review_status == "confirmed"
        assert reviewed.reviewed_at is not None
        reviewed_at = reviewed.reviewed_at

    assert _review_cli().main(
        ["review", record_id, "--decision", "false_positive"],
        session_factory=db_session_factory,
    ) == 1
    assert capsys.readouterr().err == "moderation record already reviewed\n"
    with db_session_factory() as db:
        unchanged = db.get(ModerationRecord, record.id)
        assert unchanged is not None
        assert unchanged.review_status == "confirmed"
        assert unchanged.reviewed_at == reviewed_at


def test_concurrent_reviewers_cannot_overwrite_the_first_decision(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = create_db_engine(
        f"sqlite:///{tmp_path / 'moderation-review.db'}"
    )
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)
    with session_factory() as db:
        record = _record(
            db,
            suffix="concurrent",
            created_at=datetime(2026, 8, 13, 12, 0, 0),
        )
        record_id = record.id

    with session_factory() as first_db, session_factory() as stale_db:
        first_loaded = first_db.get(ModerationRecord, record_id)
        stale_loaded = stale_db.get(ModerationRecord, record_id)
        assert first_loaded is not None
        assert stale_loaded is not None
        assert first_loaded.review_status == "pending"
        assert stale_loaded.review_status == "pending"

        assert _review_cli()._review(
            first_db, record_id, "confirmed"
        ) == 0
        capsys.readouterr()
        assert _review_cli()._review(
            stale_db, record_id, "false_positive"
        ) == 1
        assert capsys.readouterr().err == (
            "moderation record already reviewed\n"
        )

    with session_factory() as db:
        unchanged = db.get(ModerationRecord, record_id)
        assert unchanged is not None
        assert unchanged.review_status == "confirmed"
    engine.dispose()


@pytest.mark.parametrize("command", ["show", "review"])
def test_unknown_record_returns_nonzero(
    db_session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    argv = [command, str(uuid4())]
    if command == "review":
        argv.extend(["--decision", "confirmed"])

    assert _review_cli().main(
        argv, session_factory=db_session_factory
    ) == 1
    assert capsys.readouterr().err == "moderation record not found\n"


def test_review_commit_failure_rolls_back_and_reports_safely(
    db_session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_session_factory() as db:
        record = _record(
            db,
            suffix="commit-failure",
            created_at=datetime(2026, 8, 13, 12, 0, 0),
        )
        record_id = str(record.id)

    monkeypatch.setattr(
        db_session_factory.class_,
        "commit",
        lambda _db: (_ for _ in ()).throw(
            RuntimeError("private database failure")
        ),
    )

    assert _review_cli().main(
        ["review", record_id, "--decision", "confirmed"],
        session_factory=db_session_factory,
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "moderation review update failed\n"
    with db_session_factory() as db:
        unchanged = db.get(ModerationRecord, record.id)
        assert unchanged is not None
        assert unchanged.review_status == "pending"
        assert unchanged.reviewed_at is None


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "--limit", "0"],
        ["list", "--limit", "not-a-number"],
        ["show", "not-a-uuid"],
        ["review", "not-a-uuid", "--decision", "confirmed"],
        ["review", str(uuid4()), "--decision", "maybe"],
    ],
)
def test_invalid_arguments_exit_nonzero_before_opening_database(
    db_session_factory: sessionmaker[Session],
    argv: list[str],
) -> None:
    def fail_if_opened() -> Session:
        raise AssertionError("invalid arguments must not open the database")

    with pytest.raises(SystemExit) as exc_info:
        _review_cli().main(argv, session_factory=fail_if_opened)

    assert exc_info.value.code != 0
