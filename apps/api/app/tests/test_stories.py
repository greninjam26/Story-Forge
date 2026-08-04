from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Story, StoryStatus
from app.schemas import StoryGenerationResult
from app.services import story_workflow
from app.services.story_workflow import (
    StoryNotPendingReviewError,
    review_story,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    assert [page["image_url"] for page in body["pages"]] == [
        (
            "https://picsum.photos/seed/"
            f"{child['id']}-{page_number}/640/480"
        )
        for page_number in range(1, 11)
    ]
    assert all(page["audio_url"] for page in body["pages"])

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille helped make dinner."
        assert [page.page_number for page in stored_story.pages] == list(
            range(1, 11)
        )
        assert [page.image_url for page in stored_story.pages] == [
            page["image_url"] for page in body["pages"]
        ]
        assert [page.audio_url for page in stored_story.pages] == [
            page["audio_url"] for page in body["pages"]
        ]


@pytest.mark.parametrize("language", ["en", "fr"])
def test_create_story_persists_deterministic_narration_urls(
    client: TestClient,
    language: str,
) -> None:
    child = _create_child(client, language=language)
    event_text = "Camille helped prepare dinner."

    first_story = _create_story(client, child["id"], event_text)
    second_story = _create_story(client, child["id"], event_text)

    assert first_story["status"] == "pending_review"
    assert second_story["status"] == "pending_review"
    assert first_story["pages"]
    assert second_story["pages"]
    first_urls = [page["audio_url"] for page in first_story["pages"]]
    second_urls = [page["audio_url"] for page in second_story["pages"]]
    assert all(isinstance(url, str) for url in first_urls)
    assert all(
        f"/media/placeholders/narration/{language}/" in url
        for url in first_urls
    )
    assert len(set(first_urls)) == len(first_urls)
    assert second_urls == first_urls
    assert [
        page["audio_url"]
        for page in client.get(f"/stories/{first_story['id']}").json()[
            "pages"
        ]
    ] == first_urls


def test_stub_narration_url_serves_wav_audio(client: TestClient) -> None:
    child = _create_child(client)
    story = _create_story(client, child["id"], "A good day.")

    response = client.get(story["pages"][0]["audio_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert response.content[8:12] == b"WAVE"
    assert len(response.content) > 44


def test_create_story_persists_rejected_event_without_generation(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client, language="fr")

    def fail_generation(**_: object) -> None:
        raise AssertionError("Unsafe event reached story generation.")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_generation,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille a trouvé une arme.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["language"] == "fr"
    assert body["status"] == "rejected"
    assert body["failure_reason"] == "safety_content_blocked"
    assert body["pages"] == []

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille a trouvé une arme."
        assert stored_story.status is StoryStatus.REJECTED
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


def test_create_story_discards_unsafe_generated_content(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)

    def generate_unsafe_story(**_: object) -> StoryGenerationResult:
        return StoryGenerationResult(
            title="Camille and the Gentle Star",
            pages=[
                "Camille followed a friendly guide.",
                "The guide discovered blood on the path.",
            ],
        )

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        generate_unsafe_story,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped prepare dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["language"] == "en"
    assert body["status"] == "rejected"
    assert body["failure_reason"] == "safety_generated_page_2_blocked"
    assert body["pages"] == []

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == "Camille helped prepare dinner."
        assert stored_story.title == ""
        assert stored_story.status is StoryStatus.REJECTED
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


def test_create_story_records_generation_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client, language="fr")

    def fail_generation(**_: object) -> None:
        raise RuntimeError("provider unavailable: secret details")

    monkeypatch.setattr(
        story_workflow,
        "generate_story",
        fail_generation,
    )

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "  Camille a aidé à préparer le dîner.  ",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["language"] == "fr"
    assert body["status"] == "generation_failed"
    assert body["failure_reason"] == "story_generation_failed"
    assert body["pages"] == []
    assert "secret details" not in response.text

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.event_text == (
            "Camille a aidé à préparer le dîner."
        )
        assert stored_story.status is StoryStatus.GENERATION_FAILED
        assert stored_story.failure_reason == "story_generation_failed"
        assert stored_story.pages == []


def test_create_story_records_illustration_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "image_gen_provider", "unknown")

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped prepare dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["status"] == "generation_failed"
    assert body["failure_reason"] == "illustration_generation_failed"
    assert body["pages"] == []
    assert "Unsupported illustration provider" not in response.text

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


def test_create_story_records_narration_failure(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _create_child(client)
    monkeypatch.setattr(settings, "tts_provider", "unknown")

    response = client.post(
        "/stories",
        json={
            "child_id": child["id"],
            "event_text": "Camille helped prepare dinner.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["child_id"] == child["id"]
    assert body["title"] == ""
    assert body["status"] == "generation_failed"
    assert body["failure_reason"] == "narration_generation_failed"
    assert body["pages"] == []
    assert "Unsupported narration provider" not in response.text

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(body["id"]))
        assert stored_story is not None
        assert stored_story.failure_reason == body["failure_reason"]
        assert stored_story.pages == []


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


def test_approve_story_persists_review_decision(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")
    review_started_at = datetime.now(timezone.utc)

    response = client.patch(
        f"/stories/{created_story['id']}/approve",
        json={"approve": True},
    )
    review_finished_at = datetime.now(timezone.utc)

    assert response.status_code == 200
    story = response.json()
    assert story["status"] == "approved"
    assert story["approved_at"] is not None
    approved_at = _as_utc(datetime.fromisoformat(story["approved_at"]))
    assert review_started_at <= approved_at <= review_finished_at
    assert story["pages"] == created_story["pages"]

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        assert stored_story.status is StoryStatus.APPROVED
        assert stored_story.approved_at is not None
        stored_approved_at = _as_utc(stored_story.approved_at)
        assert review_started_at <= stored_approved_at <= review_finished_at


def test_reject_story_persists_review_decision(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A difficult day.")

    response = client.patch(
        f"/stories/{created_story['id']}/approve",
        json={"approve": False},
    )

    assert response.status_code == 200
    story = response.json()
    assert story["status"] == "rejected"
    assert story["approved_at"] is None
    assert story["pages"] == created_story["pages"]

    with db_session_factory() as db:
        stored_story = db.get(Story, UUID(created_story["id"]))
        assert stored_story is not None
        assert stored_story.status is StoryStatus.REJECTED
        assert stored_story.approved_at is None


@pytest.mark.parametrize(
    ("first_decision", "second_decision", "expected_status"),
    [
        (True, False, "approved"),
        (False, True, "rejected"),
    ],
)
def test_review_story_rejects_a_second_decision(
    client: TestClient,
    first_decision: bool,
    second_decision: bool,
    expected_status: str,
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")
    story_url = f"/stories/{created_story['id']}"

    first_response = client.patch(
        f"{story_url}/approve",
        json={"approve": first_decision},
    )
    second_response = client.patch(
        f"{story_url}/approve",
        json={"approve": second_decision},
    )
    first_review = first_response.json()
    stored_review = client.get(story_url).json()

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": "Story is not pending review."
    }
    assert stored_review["status"] == expected_status
    assert stored_review["approved_at"] == first_review["approved_at"]


def test_review_story_does_not_overwrite_a_concurrent_decision(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")
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
            review_story(
                db=stale_db,
                story_id=story_id,
                approve=False,
            )

        stale_db.expire_all()
        stored_story = stale_db.get(Story, story_id)
        assert stored_story is not None
        assert stored_story.status is StoryStatus.APPROVED
        assert stored_story.approved_at is not None


def test_review_story_returns_not_found_for_missing_story(
    client: TestClient,
) -> None:
    response = client.patch(
        f"/stories/{uuid4()}/approve",
        json={"approve": True},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Story not found."}


def test_review_story_rejects_invalid_story_id(client: TestClient) -> None:
    response = client.patch(
        "/stories/not-a-uuid/approve",
        json={"approve": True},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"approve": None},
        {"approve": 1},
        {"approve": "true"},
        {"approve": True, "unexpected": "value"},
    ],
)
def test_review_story_rejects_invalid_payload(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    child = _create_child(client)
    created_story = _create_story(client, child["id"], "A good day.")

    response = client.patch(
        f"/stories/{created_story['id']}/approve",
        json=payload,
    )

    assert response.status_code == 422
