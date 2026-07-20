from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Story


def _create_child(
    client: TestClient,
    *,
    language: str = "en",
    interests: str = "origami",
) -> dict[str, Any]:
    parent_response = client.post(
        "/parents",
        json={"email": "parent@example.com"},
    )
    assert parent_response.status_code == 201

    parent_id = parent_response.json()["id"]
    child_response = client.post(
        f"/parents/{parent_id}/children",
        json={
            "name": "Camille",
            "age": 7,
            "interests": interests,
            "language": language,
        },
    )
    assert child_response.status_code == 201
    return child_response.json()


def test_create_story_persists_generated_story_and_pages(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "  Camille helped make dinner.  ",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] is not None
    assert body["child_id"] == child["id"]
    assert body["title"] == "Camille and the Gentle Star"
    assert body["language"] == "en"
    assert body["status"] == "pending_review"
    assert body["failure_reason"] is None
    assert body["approved_at"] is None
    assert len(body["pages"]) == 10
    assert [page["page_number"] for page in body["pages"]] == list(
        range(1, 11)
    )
    assert all(page["id"] is not None for page in body["pages"])
    assert all(page["text"] for page in body["pages"])
    assert any("origami" in page["text"] for page in body["pages"])

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille helped make dinner."
        assert [page.page_number for page in stored_story.pages] == list(
            range(1, 11)
        )


def test_create_story_uses_child_story_language(client: TestClient) -> None:
    child = _create_child(client, language="fr")

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille a aidé à préparer le dîner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["language"] == "fr"
    assert body["title"] == "Camille et la douce étoile"
    assert len(body["pages"]) == 10
    assert any("dîner" in page["text"] for page in body["pages"])


def test_create_story_requires_existing_child(client: TestClient) -> None:
    response = client.post(
        "/stories",
        json={
            "child_id": str(uuid4()),
            "event_text": "A good day.",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}


@pytest.mark.parametrize(
    "payload",
    [
        {"child_id": "not-a-uuid", "event_text": "A good day."},
        {"child_id": str(uuid4()), "event_text": ""},
        {"child_id": str(uuid4()), "event_text": " " * 3},
        {"child_id": str(uuid4()), "event_text": "a" * 2001},
    ],
)
def test_create_story_rejects_invalid_input(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    response = client.post("/stories", json=payload)

    assert response.status_code == 422
