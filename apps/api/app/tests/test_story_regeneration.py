from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Child, Story, StoryStatus
from app.schemas import StoryGenerationResult
from app.services import story_workflow


def _create_story(
    client: TestClient,
    *,
    language: str = "en",
    event_text: str = "Camille helped make dinner.",
) -> dict[str, Any]:
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
            "language": language,
        },
    )
    assert child_response.status_code == 201

    story_response = client.post(
        "/stories",
        json={
            "child_id": child_response.json()["id"],
            "event_text": event_text,
        },
    )
    assert story_response.status_code == 201
    return story_response.json()


def test_regenerate_story_replaces_edited_draft_content(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"
    edit_response = client.patch(
        story_url,
        json={
            "title": "A manually edited title",
            "pages": [{"page_number": 1, "text": "A manually edited page."}],
        },
    )
    assert edit_response.status_code == 200
    edited_story = edit_response.json()

    response = client.post(f"{story_url}/regenerate")

    assert response.status_code == 200
    regenerated_story = response.json()
    assert regenerated_story["id"] == created_story["id"]
    assert regenerated_story["title"] == created_story["title"]
    assert [page["text"] for page in regenerated_story["pages"]] == [
        page["text"] for page in created_story["pages"]
    ]
    assert [page["page_number"] for page in regenerated_story["pages"]] == list(
        range(1, 11)
    )
    assert {
        page["id"] for page in regenerated_story["pages"]
    }.isdisjoint({page["id"] for page in edited_story["pages"]})
    assert all(page["image_url"]
               is None for page in regenerated_story["pages"])
    assert all(page["audio_url"]
               is None for page in regenerated_story["pages"])

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille helped make dinner."
        assert stored_story.title == created_story["title"]
        assert [page.text for page in stored_story.pages] == [
            page["text"] for page in created_story["pages"]
        ]


def test_regenerate_story_preserves_story_language(
    client: TestClient,
) -> None:
    created_story = _create_story(
        client,
        language="fr",
        event_text="Camille a aidé à préparer le dîner.",
    )
    story_url = f"/stories/{created_story['id']}"
    edit_response = client.patch(
        story_url,
        json={"title": "Un titre modifié"},
    )
    assert edit_response.status_code == 200

    response = client.post(f"{story_url}/regenerate")

    assert response.status_code == 200
    story = response.json()
    assert story["language"] == "fr"
    assert story["title"] == "Camille et la douce étoile"


def test_regenerate_story_uses_current_child_profile(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    created_story = _create_story(client)
    with db_session_factory() as db:
        child = db.get(Child, UUID(created_story["child_id"]))
        assert child is not None
        child.name = "Amélie"
        child.age = 10
        child.interests = "dragons"
        child.language = "fr"
        db.commit()

    response = client.post(f"/stories/{created_story['id']}/regenerate")

    assert response.status_code == 200
    story = response.json()
    assert story["language"] == "en"
    assert story["title"] == "Amélie and the Courage to Try"
    assert len(story["pages"]) == 12
    assert any("dragons" in page["text"] for page in story["pages"])


def test_regenerate_story_returns_not_found_for_missing_story(
    client: TestClient,
) -> None:
    response = client.post(f"/stories/{uuid4()}/regenerate")

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_regenerate_story_rejects_invalid_story_id(
    client: TestClient,
) -> None:
    response = client.post("/stories/not-a-uuid/regenerate")

    assert response.status_code == 422


@pytest.mark.parametrize("approve", [True, False])
def test_regenerate_story_rejects_reviewed_story(
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

    response = client.post(f"{story_url}/regenerate")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Story is not pending review."
    }
    assert client.get(story_url).json() == review_response.json()


def test_regenerate_story_discards_unsafe_generated_content(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"

    def generate_unsafe_story(**_: object) -> StoryGenerationResult:
        return StoryGenerationResult(
            title="Camille and the Hidden Weapon",
            pages=["Camille followed a friendly guide home."],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_unsafe_story,
    )

    response = client.post(f"{story_url}/regenerate")

    assert response.status_code == 200
    story = response.json()
    assert story["id"] == created_story["id"]
    assert story["status"] == StoryStatus.REJECTED.value
    assert story["title"] == ""
    assert story["failure_reason"] == "safety_generated_title_blocked"
    assert story["pages"] == []

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        assert stored_story.status is StoryStatus.REJECTED
        assert stored_story.title == ""
        assert stored_story.failure_reason == story["failure_reason"]
        assert stored_story.pages == []


def test_regenerate_story_preserves_draft_when_generation_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"
    edit_response = client.patch(
        story_url,
        json={
            "title": "Keep this edited title",
            "pages": [{"page_number": 1, "text": "Keep this edited page."}],
        },
    )
    assert edit_response.status_code == 200
    edited_story = edit_response.json()

    def fail_generation(**_: object) -> None:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(story_workflow, "generate_story", fail_generation)

    response = client.post(f"{story_url}/regenerate")

    assert response.status_code == 502
    assert response.json() == {"detail": "Story regeneration failed."}
    assert client.get(story_url).json() == edited_story


@pytest.mark.parametrize("unsafe_generated_output", [False, True])
def test_regenerate_story_does_not_overwrite_a_concurrent_review(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    unsafe_generated_output: bool,
) -> None:
    created_story = _create_story(client)
    story_id = UUID(created_story["id"])
    story_url = f"/stories/{created_story['id']}"
    edit_response = client.patch(
        story_url,
        json={
            "title": "Keep this reviewed title",
            "pages": [{"page_number": 1, "text": "Keep this reviewed page."}],
        },
    )
    assert edit_response.status_code == 200
    edited_story = edit_response.json()
    original_generate_story = story_workflow.generate_story

    def generate_then_review(**values: Any):
        generated = (
            StoryGenerationResult(
                title="Camille and the Hidden Weapon",
                pages=["Camille followed a friendly guide home."],
            )
            if unsafe_generated_output
            else original_generate_story(**values)
        )
        with db_session_factory() as review_db:
            story_workflow.review_story(
                db=review_db,
                story_id=story_id,
                approve=True,
            )
        return generated

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_then_review,
    )

    response = client.post(f"{story_url}/regenerate")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Story is not pending review."
    }
    stored_story = client.get(story_url).json()
    assert stored_story["status"] == StoryStatus.APPROVED.value
    assert stored_story["title"] == edited_story["title"]
    assert stored_story["pages"] == edited_story["pages"]
