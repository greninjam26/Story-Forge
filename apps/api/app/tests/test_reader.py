from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _create_child(
    client: TestClient,
    *,
    email: str,
) -> dict[str, Any]:
    parent_response = client.post(
        "/parents",
        json={"email": email},
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


def _create_story(
    client: TestClient,
    *,
    child_id: str,
    event_text: str,
) -> dict[str, Any]:
    response = client.post(
        "/stories",
        json={"child_id": child_id, "event_text": event_text},
    )
    assert response.status_code == 201
    return response.json()


def _review_story(
    client: TestClient,
    *,
    story_id: str,
    approve: bool,
) -> dict[str, Any]:
    response = client.patch(
        f"/stories/{story_id}/approve",
        json={"approve": approve},
    )
    assert response.status_code == 200
    return response.json()


def test_reader_lists_only_approved_stories_for_child_newest_first(
    client: TestClient,
) -> None:
    child = _create_child(client, email="reader@example.com")
    other_child = _create_child(client, email="other@example.com")

    first_approved = _create_story(
        client,
        child_id=child["id"],
        event_text="Camille helped make dinner.",
    )
    _review_story(
        client,
        story_id=first_approved["id"],
        approve=True,
    )

    _create_story(
        client,
        child_id=child["id"],
        event_text="Camille built a paper crane.",
    )

    rejected = _create_story(
        client,
        child_id=child["id"],
        event_text="Camille painted a picture.",
    )
    _review_story(client, story_id=rejected["id"], approve=False)

    second_approved = _create_story(
        client,
        child_id=child["id"],
        event_text="Camille planted a seed.",
    )
    _review_story(
        client,
        story_id=second_approved["id"],
        approve=True,
    )

    other_approved = _create_story(
        client,
        child_id=other_child["id"],
        event_text="Another child had a kind day.",
    )
    _review_story(
        client,
        story_id=other_approved["id"],
        approve=True,
    )

    response = client.get(f"/reader/children/{child['id']}/stories")

    assert response.status_code == 200
    stories = response.json()
    assert [story["id"] for story in stories] == [
        second_approved["id"],
        first_approved["id"],
    ]
    assert all(story["child_id"] == child["id"] for story in stories)
    assert all(story["status"] == "approved" for story in stories)
    assert all(len(story["pages"]) == 10 for story in stories)


def test_reader_returns_empty_list_for_child_without_approved_stories(
    client: TestClient,
) -> None:
    child = _create_child(client, email="empty-reader@example.com")
    _create_story(
        client,
        child_id=child["id"],
        event_text="Camille folded a paper boat.",
    )

    response = client.get(f"/reader/children/{child['id']}/stories")

    assert response.status_code == 200
    assert response.json() == []


def test_reader_requires_existing_child(client: TestClient) -> None:
    response = client.get(f"/reader/children/{uuid4()}/stories")

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}


def test_reader_gets_approved_story_with_ordered_pages(
    client: TestClient,
) -> None:
    child = _create_child(client, email="story-reader@example.com")
    story = _create_story(
        client,
        child_id=child["id"],
        event_text="Camille learned to tie a shoelace.",
    )
    _review_story(client, story_id=story["id"], approve=True)

    response = client.get(f"/reader/stories/{story['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == story["id"]
    assert body["child_id"] == child["id"]
    assert body["status"] == "approved"
    assert [page["page_number"] for page in body["pages"]] == list(
        range(1, 11)
    )


@pytest.mark.parametrize("approve", [None, False])
def test_reader_hides_unapproved_story(
    client: TestClient,
    approve: bool | None,
) -> None:
    child = _create_child(
        client,
        email=f"hidden-reader-{approve}@example.com",
    )
    story = _create_story(
        client,
        child_id=child["id"],
        event_text="Camille made a paper lantern.",
    )
    if approve is not None:
        _review_story(client, story_id=story["id"], approve=approve)

    response = client.get(f"/reader/stories/{story['id']}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_reader_requires_existing_story(client: TestClient) -> None:
    response = client.get(f"/reader/stories/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}
