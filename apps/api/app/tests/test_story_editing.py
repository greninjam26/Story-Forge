from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Story, StoryStatus
from app.services.story_workflow import (
    StoryNotPendingReviewError,
    review_story,
    update_story as update_story_workflow,
)


def _create_story(client: TestClient) -> dict[str, Any]:
    parent_response = client.post(
        "/parents",
        json={"email": "parent@example.com"},
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

    story_response = client.post(
        "/stories",
        json={
            "child_id": child_response.json()["id"],
            "event_text": "Camille helped make dinner.",
        },
    )
    assert story_response.status_code == 201
    return story_response.json()


def test_update_story_changes_title_and_preserves_pages(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    created_story = _create_story(client)

    response = client.patch(
        f"/stories/{created_story['id']}",
        json={"title": "  Camille's Wonderful Evening  "},
    )

    assert response.status_code == 200
    story = response.json()
    assert story["title"] == "Camille's Wonderful Evening"
    assert story["pages"] == created_story["pages"]
    assert story["status"] == "pending_review"

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        assert stored_story.title == "Camille's Wonderful Evening"


def test_update_story_changes_only_selected_pages(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    created_story = _create_story(client)
    original_text_by_page = {
        page["page_number"]: page["text"] for page in created_story["pages"]
    }

    response = client.patch(
        f"/stories/{created_story['id']}",
        json={
            "pages": [
                {"page_number": 2, "text": "A calmer second page."},
                {"page_number": 4, "text": "A brighter fourth page."},
            ],
        },
    )

    assert response.status_code == 200
    story = response.json()
    text_by_page = {
        page["page_number"]: page["text"] for page in story["pages"]
    }
    assert text_by_page[2] == "A calmer second page."
    assert text_by_page[4] == "A brighter fourth page."
    assert text_by_page[1] == original_text_by_page[1]
    assert story["title"] == created_story["title"]

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        stored_text_by_page = {
            page.page_number: page.text for page in stored_story.pages
        }
        assert stored_text_by_page[2] == "A calmer second page."
        assert stored_text_by_page[4] == "A brighter fourth page."


def test_update_story_changes_title_and_pages_together(
    client: TestClient,
) -> None:
    created_story = _create_story(client)

    response = client.patch(
        f"/stories/{created_story['id']}",
        json={
            "title": "Camille's Cozy Evening",
            "pages": [
                {"page_number": 1, "text": "Camille began a cozy evening."}
            ],
        },
    )

    assert response.status_code == 200
    story = response.json()
    assert story["title"] == "Camille's Cozy Evening"
    assert story["pages"][0]["text"] == "Camille began a cozy evening."


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Camille and the Hidden Weapon"},
        {
            "pages": [
                {
                    "page_number": 1,
                    "text": "Camille discovered a weapon.",
                }
            ]
        },
    ],
)
def test_update_story_rejects_unsafe_content_without_changing_draft(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"

    response = client.patch(story_url, json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Story content failed safety checks."
    }
    assert client.get(story_url).json() == created_story


def test_update_story_rolls_back_all_changes_for_unknown_page(
    client: TestClient,
) -> None:
    created_story = _create_story(client)

    response = client.patch(
        f"/stories/{created_story['id']}",
        json={
            "title": "This title must not persist",
            "pages": [
                {"page_number": 11, "text": "This page does not exist."}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Story page not found."}

    stored_story = client.get(f"/stories/{created_story['id']}").json()
    assert stored_story["title"] == created_story["title"]
    assert stored_story["pages"] == created_story["pages"]


def test_update_story_returns_not_found_for_missing_story(
    client: TestClient,
) -> None:
    response = client.patch(
        f"/stories/{uuid4()}",
        json={"title": "A different title"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_update_story_rejects_invalid_story_id(client: TestClient) -> None:
    response = client.patch(
        "/stories/not-a-uuid",
        json={"title": "A different title"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"pages": []},
        {"title": "A title", "unexpected": "value"},
    ],
)
def test_update_story_rejects_invalid_payload(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    created_story = _create_story(client)

    response = client.patch(
        f"/stories/{created_story['id']}",
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("approve", [True, False])
def test_update_story_rejects_reviewed_story(
    client: TestClient,
    approve: bool,
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"
    review_response = client.patch(
        f"{story_url}/approve",
        json={"approve": approve},
    )
    assert review_response.status_code == 200

    response = client.patch(
        story_url,
        json={
            "title": "This edit must not persist",
            "pages": [{"page_number": 1, "text": "Neither should this."}],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Story is not pending review."
    }
    assert client.get(story_url).json() == review_response.json()


def test_update_story_does_not_overwrite_a_concurrent_review(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    created_story = _create_story(client)
    story_id = UUID(created_story["id"])

    with db_session_factory() as stale_db:
        stale_story = stale_db.get(Story, story_id)
        assert stale_story is not None
        assert stale_story.status is StoryStatus.PENDING_REVIEW

        with db_session_factory() as current_db:
            review_story(
                db=current_db,
                story_id=story_id,
                approve=True,
            )

        with pytest.raises(StoryNotPendingReviewError):
            update_story_workflow(
                db=stale_db,
                story_id=story_id,
                title="This edit must not persist",
                pages={1: "Neither should this."},
            )

        stale_db.expire_all()
        stored_story = stale_db.get(Story, story_id)
        assert stored_story is not None
        assert stored_story.status is StoryStatus.APPROVED
        assert stored_story.title == created_story["title"]
        assert stored_story.pages[0].text == created_story["pages"][0]["text"]
