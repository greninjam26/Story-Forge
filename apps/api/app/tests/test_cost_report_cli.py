from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import GenerationRun, GenerationRunStatus
from scripts.cost_report import main


def test_cost_report_cli_defaults_to_last_100(
    db_session_factory: sessionmaker[Session],
    capsys,
) -> None:
    with db_session_factory() as db:
        db.add(
            GenerationRun(
                status=GenerationRunStatus.SUCCEEDED,
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                completed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                known_cost_usd=Decimal("0.01"),
            )
        )
        db.commit()

    exit_code = main([], session_factory=db_session_factory)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith(
        "Cost report: 1 of requested 100 terminal runs\n"
    )
    assert captured.err == ""


def test_cost_report_cli_rejects_nonpositive_last(
    db_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--last", "0"], session_factory=db_session_factory)

    assert exc_info.value.code == 2


def test_cost_report_cli_returns_failure_when_database_is_unavailable(
    capsys,
) -> None:
    def unavailable_session() -> Session:
        raise RuntimeError("database unavailable")

    exit_code = main([], session_factory=unavailable_session)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "cost report failed: database unavailable\n"
