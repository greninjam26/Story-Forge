from datetime import datetime, timezone
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
    email: str = "parent@example.com",
) -> dict[str, Any]:
    parent_response = client.post(
        "/parents",
        json={"email": email},
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


def _create_story(
    client: TestClient,
    child_id: str,
    event_text: str,
) -> dict[str, Any]:
    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": event_text},
    )
    assert response.status_code == 201
    return response.json()


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


def test_list_stories_scopes_to_child_and_orders_newest_first(
    client: TestClient,
) -> None:
    child = _create_child(client, email="first@example.com")
    other_child = _create_child(client, email="other@example.com")
    first_story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )
    second_story = _create_story(
        client,
        child["id"],
        "Camille built a paper crane.",
    )
    _create_story(client, other_child["id"], "Another child's story.")

    response = client.get(f"/stories/by-child/{child['id']}")

    assert response.status_code == 200
    stories = response.json()
    assert [story["id"] for story in stories] == [
        second_story["id"],
        first_story["id"],
    ]
    assert all(story["child_id"] == child["id"] for story in stories)
    assert all(len(story["pages"]) == 10 for story in stories)
    assert all(
        [page["page_number"] for page in story["pages"]]
        == list(range(1, 11))
        for story in stories
    )


def test_list_stories_returns_empty_list_for_existing_child(
    client: TestClient,
) -> None:
    child = _create_child(client)

    response = client.get(f"/stories/by-child/{child['id']}")

    assert response.status_code == 200
    assert response.json() == []


def test_list_stories_uses_id_to_break_created_at_ties(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    first_story = _create_story(client, child["id"], "First event.")
    second_story = _create_story(client, child["id"], "Second event.")
    matching_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with db_session_factory() as db:
        for story_id in (first_story["id"], second_story["id"]):
            story = db.get(Story, UUID(story_id))
            assert story is not None
            story.created_at = matching_created_at
        db.commit()

    response = client.get(f"/stories/by-child/{child['id']}")

    assert response.status_code == 200
    expected_ids = sorted(
        [first_story["id"], second_story["id"]],
        reverse=True,
    )
    assert [story["id"] for story in response.json()] == expected_ids


def test_list_stories_requires_existing_child(client: TestClient) -> None:
    response = client.get(f"/stories/by-child/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}


def test_list_stories_rejects_invalid_child_id(client: TestClient) -> None:
    response = client.get("/stories/by-child/not-a-uuid")

    assert response.status_code == 422


def test_get_story_returns_complete_story_with_ordered_pages(
    client: TestClient,
) -> None:
    child = _create_child(client)
    created_story = _create_story(
        client,
        child["id"],
        "Camille helped make dinner.",
    )

    response = client.get(f"/stories/{created_story['id']}")

    assert response.status_code == 200
    story = response.json()
    assert story == created_story
    assert [page["page_number"] for page in story["pages"]] == list(
        range(1, 11)
    )


def test_get_story_returns_not_found_for_missing_story(
    client: TestClient,
) -> None:
    response = client.get(f"/stories/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_get_story_rejects_invalid_story_id(client: TestClient) -> None:
    response = client.get("/stories/not-a-uuid")

    assert response.status_code == 422


def test_get_story_route_coexists_with_list_by_child_route(
    client: TestClient,
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")

    list_response = client.get(f"/stories/by-child/{child['id']}")
    get_response = client.get(f"/stories/{created_story['id']}")

    assert list_response.status_code == 200
    assert [story["id"] for story in list_response.json()] == [
        created_story["id"]
    ]
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created_story["id"]
