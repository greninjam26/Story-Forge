import pytest
from fastapi.testclient import TestClient

from app.config import settings


def test_parent_profile_includes_configured_free_story_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "free_stories_limit", 7)
    register_response = client.post(
        "/auth/register",
        json={
            "email": "profile-parent@example.com",
            "password": "password123",
            "locale": "en",
        },
    )
    assert register_response.status_code == 201

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json().get("free_stories_limit") == 7
