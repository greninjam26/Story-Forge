from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, create_db_engine
from app.models import Child, Parent, Story
from app.services import story_workflow


def _create_child(client: TestClient) -> dict[str, object]:
    parent_response = client.post(
        "/parents",
        json={"email": "quota-parent@example.com"},
    )
    assert parent_response.status_code == 201
    child_response = client.post(
        f"/parents/{parent_response.json()['id']}/children",
        json={
            "name": "Camille",
            "age": 7,
            "interests": "origami",
            "language": "en",
        },
    )
    assert child_response.status_code == 201
    return child_response.json()


def test_idempotent_replay_is_allowed_after_free_limit_is_reached(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "free_stories_limit", 1)
    child = _create_child(client)
    payload = {
        "child_id": child["id"],
        "event_text": "Camille helped make dinner.",
    }
    headers = {"Idempotency-Key": "one-free-story"}

    first_response = client.post("/stories", headers=headers, json=payload)
    replay_response = client.post("/stories", headers=headers, json=payload)

    assert first_response.status_code == 201
    assert replay_response.status_code == 200
    assert replay_response.json()["id"] == first_response.json()["id"]
    with db_session_factory() as db:
        parent = db.scalar(select(Parent))
        assert parent is not None
        assert parent.free_stories_used == 1


def test_concurrent_requests_cannot_both_take_the_final_free_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "free_stories_limit", 1)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'quota.db'}")
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)
    try:
        with session_factory() as db:
            parent = Parent(email="concurrent-quota@example.com")
            child = Child(
                name="Camille",
                age=7,
                interests="origami",
                language="en",
            )
            parent.children.append(child)
            db.add(parent)
            db.commit()
            child_id = child.id

        ready = Barrier(2)

        def create(index: int) -> str:
            with session_factory() as db:
                ready.wait()
                try:
                    story_workflow.create_story_with_idempotency(
                        db=db,
                        child_id=child_id,
                        event_text=f"Camille's good day {index}.",
                        idempotency_key=f"quota-request-{index}",
                    )
                except story_workflow.FreeStoryLimitReachedError:
                    return "limited"
                except Exception as error:
                    return f"unexpected:{type(error).__name__}"
                return "created"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, range(2)))

        assert sorted(results) == ["created", "limited"]
        with session_factory() as db:
            parent = db.scalar(select(Parent))
            assert parent is not None
            assert parent.free_stories_used == 1
            assert len(db.scalars(select(Story)).all()) == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_failed_creation_releases_reserved_free_slot(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "free_stories_limit", 1)
    monkeypatch.setattr(settings, "story_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    child = _create_child(client)

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped make dinner.",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "story_provider_not_configured"
    }
    with db_session_factory() as db:
        parent = db.scalar(select(Parent))
        assert parent is not None
        assert parent.free_stories_used == 0
        assert db.scalar(select(Story)) is None
