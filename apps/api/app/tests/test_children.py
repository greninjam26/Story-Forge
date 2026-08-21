from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.tests.testing import StoryForgeTestClient


def _create_parent(
    client: StoryForgeTestClient,
    email: str = "parent@example.com",
) -> dict[str, object]:
    return client.create_parent(email=email)


def _create_child(
    client: TestClient,
    parent_id: str,
    **overrides: object,
) -> dict[str, Any]:
    payload: dict[str, object] = {
        "name": "Camille",
        "age": 7,
        "interests": "stars",
        "language": "en",
    }
    payload.update(overrides)
    response = client.post(f"/parents/{parent_id}/children", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_child(client: TestClient) -> None:
    parent = _create_parent(client)

    response = client.post(
        f"/parents/{parent['id']}/children",
        json={"name": "  Camille  ", "age": 7},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["parent_id"] == parent["id"]
    assert body["name"] == "Camille"
    assert body["age"] == 7
    assert body["interests"] == ""
    assert body["language"] == "en"
    assert body["created_at"] is not None


def test_create_child_accepts_french(client: TestClient) -> None:
    parent = _create_parent(client)

    child = _create_child(
        client,
        parent["id"],
        language="fr",
        interests="les dinosaures",
    )

    assert child["language"] == "fr"
    assert child["interests"] == "les dinosaures"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "age": 7},
        {"name": "Camille", "age": 13},
        {"name": "Camille", "age": 7, "language": "es"},
    ],
)
def test_create_child_rejects_invalid_input(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    parent = _create_parent(client)

    response = client.post(
        f"/parents/{parent['id']}/children",
        json=payload,
    )

    assert response.status_code == 422


def test_create_child_requires_existing_parent(client: TestClient) -> None:
    _create_parent(client)
    response = client.post(
        f"/parents/{uuid4()}/children",
        json={"name": "Camille", "age": 7},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied."}


def test_list_children_is_scoped_to_parent(client: TestClient) -> None:
    first_parent = _create_parent(client, "first@example.com")
    second_parent = _create_parent(client, "second@example.com")
    _create_child(client, first_parent["id"], name="Camille")
    _create_child(client, first_parent["id"], name="Leo")
    _create_child(client, second_parent["id"], name="Other")

    response = client.get(f"/parents/{first_parent['id']}/children")

    assert response.status_code == 200
    assert [child["name"] for child in response.json()] == ["Camille", "Leo"]


def test_list_children_requires_existing_parent(client: TestClient) -> None:
    _create_parent(client)
    response = client.get(f"/parents/{uuid4()}/children")

    assert response.status_code == 403


def test_list_children_returns_empty_list(client: TestClient) -> None:
    parent = _create_parent(client)

    response = client.get(f"/parents/{parent['id']}/children")

    assert response.status_code == 200
    assert response.json() == []


def test_get_child(client: TestClient) -> None:
    parent = _create_parent(client)
    created = _create_child(client, parent["id"])

    response = client.get(
        f"/parents/{parent['id']}/children/{created['id']}"
    )

    assert response.status_code == 200
    assert response.json() == created


def test_get_child_is_scoped_to_parent(client: TestClient) -> None:
    owner = _create_parent(client, "owner@example.com")
    other_parent = _create_parent(client, "other@example.com")
    child = _create_child(client, owner["id"])

    response = client.get(
        f"/parents/{other_parent['id']}/children/{child['id']}"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Child not found."}


def test_update_child_changes_only_provided_fields(client: TestClient) -> None:
    parent = _create_parent(client)
    child = _create_child(client, parent["id"], interests="space")

    response = client.patch(
        f"/parents/{parent['id']}/children/{child['id']}",
        json={"name": "  Camille-Marie  ", "language": "fr"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Camille-Marie"
    assert body["language"] == "fr"
    assert body["age"] == 7
    assert body["interests"] == "space"


@pytest.mark.parametrize("payload", [{"age": 13}, {"name": None}])
def test_update_child_rejects_invalid_input(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])

    response = client.patch(
        f"/parents/{parent['id']}/children/{child['id']}",
        json=payload,
    )

    assert response.status_code == 422


def test_update_missing_child_returns_not_found(client: TestClient) -> None:
    parent = _create_parent(client)

    response = client.patch(
        f"/parents/{parent['id']}/children/{uuid4()}",
        json={"name": "Camille-Marie"},
    )

    assert response.status_code == 404


def test_delete_child(client: TestClient) -> None:
    parent = _create_parent(client)
    child = _create_child(client, parent["id"])
    child_url = f"/parents/{parent['id']}/children/{child['id']}"

    response = client.delete(child_url)

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(child_url).status_code == 404


def test_delete_child_is_scoped_to_parent(client: TestClient) -> None:
    owner = _create_parent(client, "owner@example.com")
    other_parent = _create_parent(client, "other@example.com")
    child = _create_child(client, owner["id"])

    response = client.delete(
        f"/parents/{other_parent['id']}/children/{child['id']}"
    )

    assert response.status_code == 404
    assert client.get(
        f"/parents/{owner['id']}/children/{child['id']}"
    ).status_code == 200
