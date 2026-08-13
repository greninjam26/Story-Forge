import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.config import settings


API_ROOT = Path(__file__).resolve().parents[2]
CORE_SCHEMA_REVISION = "0f7d9a25c2bb"
AGE_RANGE_REVISION = "d3a7c4b91f20"
COST_LEDGER_REVISION = "a62f4d9e8b13"
MODERATION_PREVIOUS_REVISION = "b7d4e6f8a901"
POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")


def _assert_disposable_postgres_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    database_name = (parsed.path or "").lstrip("/")
    is_psycopg = parsed.scheme == "postgresql+psycopg"
    is_local = (parsed.hostname or "").lower() in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    is_throwaway = database_name.endswith("_test")
    has_query_parameters = bool(parsed.query)

    if not (
        is_psycopg
        and is_local
        and is_throwaway
        and not has_query_parameters
    ):
        raise ValueError(
            "POSTGRES_TEST_URL must point to a local throwaway database "
            "whose name ends in '_test', use the postgresql+psycopg "
            "scheme, and contain no query parameters."
        )


def _reset_postgres(database_url: str) -> None:
    _assert_disposable_postgres_url(database_url)
    expected_database = urlparse(database_url).path.lstrip("/")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connected_database = connection.scalar(
                text("SELECT current_database()")
            )
            if connected_database != expected_database:
                raise RuntimeError(
                    "Refusing to reset an unexpected PostgreSQL database: "
                    f"expected {expected_database!r}, connected to "
                    f"{connected_database!r}."
                )
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user:password@db.example.com/storyforge_test",
        "postgresql+psycopg://user:password@localhost/storyforge",
        (
            "postgresql+psycopg://user:password@localhost/storyforge_test"
            "?host=db.example.com"
        ),
        (
            "postgresql+psycopg://user:password@localhost/storyforge_test"
            "?dbname=production"
        ),
        (
            "postgresql+psycopg://user:password@localhost/storyforge_test"
            "?service=production"
        ),
    ],
)
def test_postgres_migration_guard_rejects_unsafe_database(
    database_url: str,
) -> None:
    with pytest.raises(ValueError, match="local throwaway database"):
        _assert_disposable_postgres_url(database_url)


@pytest.fixture(params=("sqlite", "postgres"))
def migration_database_url(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> str:
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'migrations.sqlite'}"

    if not POSTGRES_TEST_URL:
        pytest.skip("POSTGRES_TEST_URL is not configured")

    _reset_postgres(POSTGRES_TEST_URL)
    return POSTGRES_TEST_URL


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


def test_upgrade_head_builds_a_writable_schema(
    migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _alembic_config(migration_database_url, monkeypatch)

    command.upgrade(config, "head")

    engine = create_engine(migration_database_url)
    try:
        assert {
            "parents",
            "children",
            "stories",
            "story_pages",
            "generation_runs",
            "generation_cost_events",
            "pending_asset_deletions",
            "moderation_records",
        } <= set(inspect(engine).get_table_names())

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO parents (id, email)
                    VALUES (
                        '00000000-0000-0000-0000-000000000001',
                        'migration@example.com'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO children (id, parent_id, name, age)
                    VALUES (
                        '00000000-0000-0000-0000-000000000002',
                        '00000000-0000-0000-0000-000000000001',
                        'Camille',
                        7
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO stories (
                        id,
                        child_id,
                        event_text,
                        language
                    )
                    VALUES (
                        '00000000-0000-0000-0000-000000000003',
                        '00000000-0000-0000-0000-000000000002',
                        'Camille helped make dinner.',
                        'en'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO generation_runs (id, story_id)
                    VALUES (
                        '00000000-0000-0000-0000-000000000004',
                        '00000000-0000-0000-0000-000000000003'
                    )
                    """
                )
            )
            connection.execute(
                text(
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
                        cost_known
                    )
                    VALUES (
                        '00000000-0000-0000-0000-000000000005',
                        '00000000-0000-0000-0000-000000000004',
                        '00000000-0000-0000-0000-000000000006',
                        'story',
                        'stub',
                        1,
                        'succeeded',
                        'request',
                        false
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE stories
                    SET status = 'rejected',
                        failure_reason = 'safety_generated_page_1_blocked',
                        safety_reason = 'violence'
                    WHERE id = '00000000-0000-0000-0000-000000000003'
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO moderation_records (
                        id,
                        story_id,
                        provider,
                        model,
                        provider_request_id,
                        flagged_item_kind,
                        flagged_page_number,
                        flagged_text,
                        categories,
                        category_scores,
                        review_status
                    )
                    VALUES (
                        '00000000-0000-0000-0000-000000000007',
                        '00000000-0000-0000-0000-000000000003',
                        'openai',
                        'omni-moderation-test',
                        'req_test',
                        'page',
                        1,
                        'Only this generated page is retained.',
                        '["violence"]',
                        '{"violence": 0.93}',
                        'pending'
                    )
                    """
                )
            )

            assert connection.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM generation_cost_events
                    """
                )
            ) == 1
            assert connection.execute(
                text(
                    """
                    SELECT flagged_item_kind, flagged_page_number
                    FROM moderation_records
                    WHERE id = '00000000-0000-0000-0000-000000000007'
                    """
                )
            ).one() == ("page", 1)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("flagged_item_kind", "chapter"),
        ("review_status", "ignored"),
    ],
)
def test_moderation_audit_constraints_reject_invalid_states(
    migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
    invalid_value: str,
) -> None:
    config = _alembic_config(migration_database_url, monkeypatch)
    command.upgrade(config, "head")
    engine = create_engine(migration_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO parents (id, email) VALUES "
                "('00000000-0000-0000-0000-000000000011', "
                "'audit@example.com')"
            ))
            connection.execute(text(
                "INSERT INTO children (id, parent_id, name, age) VALUES "
                "('00000000-0000-0000-0000-000000000012', "
                "'00000000-0000-0000-0000-000000000011', 'Camille', 7)"
            ))
            connection.execute(text(
                "INSERT INTO stories "
                "(id, child_id, event_text, language, status) VALUES "
                "('00000000-0000-0000-0000-000000000013', "
                "'00000000-0000-0000-0000-000000000012', "
                "'Camille helped make dinner.', 'en', 'rejected')"
            ))

        values = {
            "flagged_item_kind": "page",
            "review_status": "pending",
        }
        values[column] = invalid_value
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO moderation_records (
                        id, story_id, provider, flagged_item_kind,
                        flagged_page_number, flagged_text, categories,
                        category_scores, review_status
                    )
                    VALUES (
                        :id,
                        '00000000-0000-0000-0000-000000000013',
                        'keyword', :item_kind, 1, 'retained page',
                        '["violence"]', '{}', :review_status
                    )
                    """
                ),
                {
                    "id": (
                        "00000000-0000-0000-0000-000000000021"
                        if column == "flagged_item_kind"
                        else "00000000-0000-0000-0000-000000000022"
                    ),
                    "item_kind": values["flagged_item_kind"],
                    "review_status": values["review_status"],
                },
            )
    finally:
        engine.dispose()


def test_moderation_migration_backfills_only_legacy_safety_rejections(
    migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _alembic_config(migration_database_url, monkeypatch)
    command.upgrade(config, MODERATION_PREVIOUS_REVISION)
    engine = create_engine(migration_database_url)
    story_ids = {
        "input": "00000000-0000-0000-0000-000000000031",
        "title": "00000000-0000-0000-0000-000000000032",
        "page": "00000000-0000-0000-0000-000000000033",
        "parent": "00000000-0000-0000-0000-000000000034",
        "near_miss": "00000000-0000-0000-0000-000000000035",
    }
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO parents (id, email) VALUES "
                "('00000000-0000-0000-0000-000000000029', "
                "'legacy-safety@example.com')"
            ))
            connection.execute(text(
                "INSERT INTO children (id, parent_id, name, age) VALUES "
                "('00000000-0000-0000-0000-000000000030', "
                "'00000000-0000-0000-0000-000000000029', 'Camille', 7)"
            ))
            connection.execute(
                text(
                    """
                    INSERT INTO stories (
                        id, child_id, event_text, language, status,
                        failure_reason
                    )
                    VALUES
                        (:input, :child, 'event', 'en', 'rejected',
                         'safety_content_blocked'),
                        (:title, :child, 'event', 'en', 'rejected',
                         'safety_generated_title_blocked'),
                        (:page, :child, 'event', 'en', 'rejected',
                         'safety_generated_page_2_blocked'),
                        (:parent, :child, 'event', 'en', 'rejected', NULL),
                        (:near_miss, :child, 'event', 'en', 'rejected',
                         'safetyXgeneratedXpageX2Xblocked')
                    """
                ),
                {
                    **story_ids,
                    "child": "00000000-0000-0000-0000-000000000030",
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(migration_database_url)
    try:
        with engine.begin() as connection:
            reasons = dict(connection.execute(text(
                "SELECT id, safety_reason FROM stories ORDER BY id"
            )).all())
            audit_count = connection.scalar(text(
                "SELECT COUNT(*) FROM moderation_records"
            ))
        assert reasons == {
            story_ids["input"]: "unsafe_content",
            story_ids["title"]: "unsafe_content",
            story_ids["page"]: "unsafe_content",
            story_ids["parent"]: None,
            story_ids["near_miss"]: None,
        }
        assert audit_count == 0
    finally:
        engine.dispose()


def test_migrations_match_models(
    migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _alembic_config(migration_database_url, monkeypatch)
    command.upgrade(config, "head")

    command.check(config)


def test_downgrade_returns_to_an_empty_schema(
    migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _alembic_config(migration_database_url, monkeypatch)
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    engine = create_engine(migration_database_url)
    try:
        remaining_tables = set(inspect(engine).get_table_names()) - {
            "alembic_version"
        }
        assert remaining_tables == set()
    finally:
        engine.dispose()


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
