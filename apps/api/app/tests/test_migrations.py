import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from app.config import settings


API_ROOT = Path(__file__).resolve().parents[2]
CORE_SCHEMA_REVISION = "0f7d9a25c2bb"
AGE_RANGE_REVISION = "d3a7c4b91f20"
COST_LEDGER_REVISION = "a62f4d9e8b13"


def _alembic_config(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Config:
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(API_ROOT / "migrations"),
    )
    return config


def _insert_story_family(database_path: Path, *, child_age: int) -> str:
    parent_id = uuid4().hex
    child_id = uuid4().hex
    story_id = uuid4().hex

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO parents (id, email) VALUES (?, ?)",
            (parent_id, "parent@example.com"),
        )
        connection.execute(
            """
            INSERT INTO children (id, parent_id, name, age)
            VALUES (?, ?, ?, ?)
            """,
            (child_id, parent_id, "Camille", child_age),
        )
        connection.execute(
            """
            INSERT INTO stories (id, child_id, event_text, language)
            VALUES (?, ?, ?, ?)
            """,
            (story_id, child_id, "Camille helped make dinner.", "en"),
        )
        connection.execute(
            """
            INSERT INTO story_pages (id, story_id, page_number, text)
            VALUES (?, ?, ?, ?)
            """,
            (uuid4().hex, story_id, 1, "Camille helped with dinner."),
        )
        connection.commit()
    return story_id


def _table_counts(database_path: Path) -> tuple[int, int, int, int]:
    with closing(sqlite3.connect(database_path)) as connection:
        return tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            for table_name in (
                "parents",
                "children",
                "stories",
                "story_pages",
            )
        )


def test_child_age_migration_preserves_related_story_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "storyforge.sqlite"
    config = _alembic_config(
        f"sqlite:///{database_path}",
        monkeypatch,
    )
    command.upgrade(config, CORE_SCHEMA_REVISION)
    _insert_story_family(database_path, child_age=7)

    command.upgrade(config, "head")

    assert _table_counts(database_path) == (1, 1, 1, 1)
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    command.downgrade(config, CORE_SCHEMA_REVISION)

    assert _table_counts(database_path) == (1, 1, 1, 1)


def test_child_age_migration_rejects_legacy_invalid_age_without_data_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "storyforge.sqlite"
    config = _alembic_config(
        f"sqlite:///{database_path}",
        monkeypatch,
    )
    command.upgrade(config, CORE_SCHEMA_REVISION)
    _insert_story_family(database_path, child_age=13)

    with pytest.raises(RuntimeError, match="outside 1 through 12"):
        command.upgrade(config, "head")

    assert _table_counts(database_path) == (1, 1, 1, 1)
    with closing(sqlite3.connect(database_path)) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    assert revision == CORE_SCHEMA_REVISION


def test_cost_ledger_migration_preserves_stories_and_supports_run_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "storyforge.sqlite"
    config = _alembic_config(
        f"sqlite:///{database_path}",
        monkeypatch,
    )
    command.upgrade(config, AGE_RANGE_REVISION)
    story_id = _insert_story_family(database_path, child_age=7)

    command.upgrade(config, "head")

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "generation_runs" in table_names
        assert "generation_cost_events" in table_names

        first_run_id = uuid4().hex
        second_run_id = uuid4().hex
        connection.execute(
            "INSERT INTO generation_runs (id, story_id) VALUES (?, ?)",
            (first_run_id, story_id),
        )
        connection.execute(
            "INSERT INTO generation_runs (id, story_id) VALUES (?, ?)",
            (second_run_id, story_id),
        )
        connection.execute(
            """
            INSERT INTO generation_cost_events (
                id,
                generation_run_id,
                call_id,
                stage,
                provider,
                attempt,
                outcome,
                usage_unit,
                quantity,
                unit_rate_usd,
                cost_usd,
                cost_known
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                first_run_id,
                uuid4().hex,
                "story",
                "stub",
                1,
                "succeeded",
                "request",
                1,
                "0",
                "0",
                1,
            ),
        )
        connection.commit()

        assert connection.execute(
            "SELECT COUNT(*) FROM generation_runs WHERE story_id = ?",
            (story_id,),
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM generation_cost_events"
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert _table_counts(database_path) == (1, 1, 1, 1)

    command.downgrade(config, AGE_RANGE_REVISION)

    assert _table_counts(database_path) == (1, 1, 1, 1)
    with closing(sqlite3.connect(database_path)) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "generation_runs" not in table_names
    assert "generation_cost_events" not in table_names


def test_reference_photo_migration_preserves_existing_story_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "storyforge.sqlite"
    config = _alembic_config(
        f"sqlite:///{database_path}",
        monkeypatch,
    )
    command.upgrade(config, COST_LEDGER_REVISION)
    _insert_story_family(database_path, child_age=7)

    command.upgrade(config, "head")

    assert _table_counts(database_path) == (1, 1, 1, 1)
    with closing(sqlite3.connect(database_path)) as connection:
        child_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(children)")
        }
        assert "reference_photo_ref" in child_columns
        assert connection.execute(
            "SELECT reference_photo_ref FROM children"
        ).fetchone()[0] is None
        connection.execute(
            "UPDATE children SET reference_photo_ref = ?",
            ("reference-photos/opaque-photo.webp",),
        )
        connection.commit()
        assert connection.execute(
            "SELECT reference_photo_ref FROM children"
        ).fetchone()[0] == "reference-photos/opaque-photo.webp"

    command.downgrade(config, COST_LEDGER_REVISION)

    assert _table_counts(database_path) == (1, 1, 1, 1)
    with closing(sqlite3.connect(database_path)) as connection:
        child_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(children)")
        }
        assert "reference_photo_ref" not in child_columns
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
