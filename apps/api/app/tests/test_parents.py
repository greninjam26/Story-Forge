from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient


def test_create_parent(client: TestClient) -> None:
    response = client.post("/parents", json={"email": "parent@example.com"})

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["email"] == "parent@example.com"
    assert body["locale"] == "en"
    assert body["created_at"] is not None


def test_create_parent_accepts_french_and_normalizes_email(
    client: TestClient,
) -> None:
    response = client.post(
        "/parents",
        json={"email": "PARENT@EXAMPLE.COM", "locale": "fr"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "parent@example.com"
    assert response.json()["locale"] == "fr"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email"},
        {"email": "parent@example.com", "locale": "es"},
    ],
)
def test_create_parent_rejects_invalid_input(
    client: TestClient,
    payload: dict[str, str],
) -> None:
    response = client.post("/parents", json=payload)

    assert response.status_code == 422


def test_create_parent_rejects_duplicate_email(client: TestClient) -> None:
    first_response = client.post(
        "/parents", json={"email": "parent@example.com"}
    )
    duplicate_response = client.post(
        "/parents", json={"email": "PARENT@example.com"}
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "A parent with this email already exists."
    }


def test_get_parent(client: TestClient) -> None:
    created = client.post(
        "/parents",
        json={"email": "parent@example.com", "locale": "fr"},
    ).json()

    response = client.get(f"/parents/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_parent_returns_not_found(client: TestClient) -> None:
    client.post("/parents", json={"email": "parent@example.com"})
    response = client.get(f"/parents/{uuid4()}")

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied."}


def test_get_parent_rejects_invalid_uuid(client: TestClient) -> None:
    response = client.get("/parents/not-a-uuid")

    assert response.status_code == 401
