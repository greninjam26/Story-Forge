from uuid import uuid4

from app.tests.testing import StoryForgeTestClient


def test_unauthenticated_parent_creation_is_not_available(
    client: StoryForgeTestClient,
) -> None:
    response = client.post(
        "/parents",
        json={"email": "attacker@example.com"},
    )

    assert response.status_code == 404


def test_get_parent(client: StoryForgeTestClient) -> None:
    created = client.create_parent(
        email="parent@example.com",
        locale="fr",
    )

    response = client.get(f"/parents/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_parent_returns_not_found(
    client: StoryForgeTestClient,
) -> None:
    client.create_parent()
    response = client.get(f"/parents/{uuid4()}")

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied."}


def test_get_parent_rejects_invalid_uuid(
    client: StoryForgeTestClient,
) -> None:
    response = client.get("/parents/not-a-uuid")

    assert response.status_code == 401
