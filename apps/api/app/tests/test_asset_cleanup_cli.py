from datetime import datetime, timezone
from importlib import import_module
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import PendingAssetDeletion
from app.services import storage


def _main() -> Any:
    return import_module("scripts.cleanup_assets").main


def test_cleanup_cli_processes_pending_deletions(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with db_session_factory() as db:
        db.add(
            PendingAssetDeletion(
                reference="r2://references/retry.webp"
            )
        )
        db.commit()
    monkeypatch.setattr(storage, "delete_object", lambda _reference: None)

    exit_code = _main()([], session_factory=db_session_factory)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == (
        "deleted: 1; failed: 0; pending: 0; terminal: 0\n"
    )
    assert captured.err == ""


def test_cleanup_cli_returns_failure_while_backlog_remains(
    db_session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    with db_session_factory() as db:
        db.add_all(
            [
                PendingAssetDeletion(
                    reference="r2://references/future.webp",
                    next_attempt_at=datetime(
                        2099, 1, 1, tzinfo=timezone.utc
                    ),
                ),
                PendingAssetDeletion(
                    reference="r2://references/terminal.webp",
                    attempts=12,
                    terminal_at=now,
                ),
            ]
        )
        db.commit()

    exit_code = _main()([], session_factory=db_session_factory)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == (
        "deleted: 0; failed: 0; pending: 1; terminal: 1\n"
    )
    assert captured.err == ""


def test_cleanup_cli_retries_terminal_deletions(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with db_session_factory() as db:
        db.add(
            PendingAssetDeletion(
                reference="r2://references/terminal.webp",
                attempts=12,
                terminal_at=datetime(
                    2026, 8, 11, 12, 0, tzinfo=timezone.utc
                ),
            )
        )
        db.commit()
    monkeypatch.setattr(storage, "delete_object", lambda _reference: None)

    exit_code = _main()(
        ["--retry-terminal"],
        session_factory=db_session_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == (
        "deleted: 1; failed: 0; pending: 0; terminal: 0\n"
    )
    assert captured.err == ""


def test_cleanup_cli_rejects_nonpositive_limit(
    db_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main()(["--limit", "0"], session_factory=db_session_factory)

    assert exc_info.value.code == 2


def test_cleanup_cli_returns_failure_when_database_is_unavailable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable_session() -> Session:
        raise RuntimeError("database unavailable")

    exit_code = _main()([], session_factory=unavailable_session)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "asset cleanup failed: database unavailable\n"
