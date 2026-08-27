from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import PendingAssetDeletion, Story, StoryStatus
from app.services import openai_moderation, storage, story_workflow
from app.tests.testing import StoryForgeTestClient
from app.services.story_workflow import (
    StoryNotPendingReviewError,
    review_story,
    update_story as update_story_workflow,
)


def _create_story(client: StoryForgeTestClient) -> dict[str, Any]:
    parent = client.create_parent()

    child_response = client.post(
        f"/parents/{parent['id']}/children",
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
    original_audio_by_page = {
        page["page_number"]: page["audio_url"]
        for page in created_story["pages"]
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
    audio_by_page = {
        page["page_number"]: page["audio_url"] for page in story["pages"]
    }
    assert audio_by_page[2] != original_audio_by_page[2]
    assert audio_by_page[4] != original_audio_by_page[4]
    assert audio_by_page[1] == original_audio_by_page[1]

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        stored_text_by_page = {
            page.page_number: page.text for page in stored_story.pages
        }
        assert stored_text_by_page[2] == "A calmer second page."
        assert stored_text_by_page[4] == "A brighter fourth page."


def test_update_story_retains_failed_old_audio_cleanup_for_retry(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    old_reference = (
        "r2://narration/"
        "0123456789abcdef0123456789abcdef.mp3"
    )
    new_reference = "https://audio.example/new.mp3"
    with db_session_factory() as db:
        story = db.get(Story, UUID(created_story["id"]))
        assert story is not None
        story.pages[0].audio_url = old_reference
        db.commit()

    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        lambda **_kwargs: new_reference,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda _reference: (_ for _ in ()).throw(
            OSError("cleanup unavailable")
        ),
    )

    response = client.patch(
        f"/stories/{created_story['id']}",
        json={
            "pages": [
                {"page_number": 1, "text": "A newly edited first page."}
            ]
        },
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        story = db.get(Story, UUID(created_story["id"]))
        assert story is not None
        assert story.pages[0].audio_url == new_reference
        pending = db.scalar(select(PendingAssetDeletion))
        assert pending is not None
        assert pending.reference == old_reference
        assert pending.attempts == 1


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
    assert client.get(story_url).json() == {
        **created_story,
        "event_text": "Camille helped make dinner.",
        "safety_reason": None,
        "recovery_allowed": False,
    }


def test_update_story_uses_configured_moderation_provider(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"
    edited_title = "Camille's Gentle Evening"
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def moderate(
        inputs: list[str],
    ) -> openai_moderation.ModerationResponse:
        results = tuple(
            openai_moderation.ModerationResult(
                flagged=text == edited_title,
                categories={"sexual": text == edited_title},
                category_scores={
                    "sexual": 0.99 if text == edited_title else 0.01
                },
            )
            for text in inputs
        )
        return openai_moderation.ModerationResponse(
            request_id="req_edit_unsafe",
            model="omni-moderation-test",
            results=results,
        )

    monkeypatch.setattr(
        story_workflow.safety.openai_moderation,
        "moderate",
        moderate,
    )

    response = client.patch(story_url, json={"title": edited_title})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Story content failed safety checks."
    }
    assert client.get(story_url).json() == {
        **created_story,
        "event_text": "Camille helped make dinner.",
        "safety_reason": None,
        "recovery_allowed": False,
    }


def test_update_story_fails_closed_when_moderation_is_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"
    monkeypatch.setattr(settings, "safety_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "provider_retry_attempts", 1)

    def fail(_inputs: list[str]) -> None:
        raise openai_moderation.ModerationProviderError(
            "private provider failure"
        )

    monkeypatch.setattr(
        story_workflow.safety.openai_moderation,
        "moderate",
        fail,
    )
    client._transport.raise_server_exceptions = False

    response = client.patch(
        story_url,
        json={"title": "Camille's Revised Evening"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "safety_review_unavailable"
    }
    assert client.get(story_url).json() == {
        **created_story,
        "event_text": "Camille helped make dinner.",
        "safety_reason": None,
        "recovery_allowed": False,
    }


def test_update_story_preserves_draft_when_narration_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    story_url = f"/stories/{created_story['id']}"
    monkeypatch.setattr(settings, "tts_provider", "unknown")

    response = client.patch(
        story_url,
        json={
            "pages": [
                {"page_number": 1, "text": "A newly edited first page."}
            ]
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Story narration generation failed."
    }
    assert client.get(story_url).json() == {
        **created_story,
        "event_text": "Camille helped make dinner.",
        "safety_reason": None,
        "recovery_allowed": False,
    }


def test_update_story_retains_created_audio_when_later_narration_fails(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    created_reference = (
        "r2://narration/"
        "11111111111111111111111111111111.mp3"
    )
    narration_calls = 0

    def generate_test_narration(**_: object) -> str:
        nonlocal narration_calls
        narration_calls += 1
        if narration_calls == 2:
            raise RuntimeError("provider unavailable")
        return created_reference

    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        generate_test_narration,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda _reference: (_ for _ in ()).throw(
            OSError("cleanup unavailable")
        ),
    )

    response = client.patch(
        f"/stories/{created_story['id']}",
        json={
            "pages": [
                {"page_number": 1, "text": "A new first page."},
                {"page_number": 2, "text": "A new second page."},
            ]
        },
    )

    assert response.status_code == 502
    with db_session_factory() as db:
        pending = db.scalar(select(PendingAssetDeletion))
        assert pending is not None
        assert pending.reference == created_reference
        assert pending.attempts == 1


def test_update_story_cleans_up_created_audio_when_finalization_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    created_reference = (
        "r2://narration/"
        "11111111111111111111111111111111.mp3"
    )
    deleted_references: list[str] = []

    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        lambda **_kwargs: created_reference,
    )

    def fail_finalization(_recorder: object, **_: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        story_workflow.RunCostRecorder,
        "finalize",
        fail_finalization,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        deleted_references.append,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.patch(
            f"/stories/{created_story['id']}",
            json={
                "pages": [
                    {"page_number": 1, "text": "A new first page."}
                ]
            },
        )

    assert deleted_references == [created_reference]


def test_update_story_keeps_created_audio_committed_before_error(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_story = _create_story(client)
    created_reference = (
        "r2://narration/"
        "11111111111111111111111111111111.mp3"
    )
    deleted_references: list[str] = []
    original_finalize = story_workflow.RunCostRecorder.finalize

    monkeypatch.setattr(
        story_workflow,
        "generate_narration",
        lambda **_kwargs: created_reference,
    )

    def fail_after_finalization(
        recorder: story_workflow.RunCostRecorder,
        **kwargs: object,
    ) -> None:
        original_finalize(recorder, **kwargs)
        raise RuntimeError("connection lost after commit")

    monkeypatch.setattr(
        story_workflow.RunCostRecorder,
        "finalize",
        fail_after_finalization,
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        deleted_references.append,
    )

    with pytest.raises(RuntimeError, match="connection lost after commit"):
        client.patch(
            f"/stories/{created_story['id']}",
            json={
                "pages": [
                    {"page_number": 1, "text": "A new first page."}
                ]
            },
        )

    assert deleted_references == []
    with db_session_factory() as db:
        story = db.get(Story, UUID(created_story["id"]))
        assert story is not None
        assert story.pages[0].audio_url == created_reference


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
    _create_story(client)
    response = client.patch(
        f"/stories/{uuid4()}",
        json={"title": "A different title"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_update_story_rejects_invalid_story_id(client: TestClient) -> None:
    _create_story(client)
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
    assert client.get(story_url).json() == {
        **review_response.json(),
        "event_text": "Camille helped make dinner.",
        "safety_reason": None,
        "recovery_allowed": False,
    }


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
