import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, create_db_engine, get_db
from app.main import app
from app.models import Parent
from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self) -> None:
        password = "secure-password-123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password_fails(self) -> None:
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_different_hashes_for_same_password(self) -> None:
        hashed1 = hash_password("same-password")
        hashed2 = hash_password("same-password")
        assert hashed1 != hashed2
        assert verify_password("same-password", hashed1)
        assert verify_password("same-password", hashed2)


class TestJWTTokens:
    def test_create_and_decode_token(self) -> None:
        parent_id = uuid.uuid4()
        token = create_access_token(parent_id)
        decoded = decode_access_token(token)
        assert decoded == parent_id

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(Exception):
            decode_access_token("invalid-token")

    def test_tampered_token_raises(self) -> None:
        token = create_access_token(uuid.uuid4())
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(Exception):
            decode_access_token(tampered)


@pytest.fixture
def db_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[sessionmaker[Session], None, None]:
    database_dir = tmp_path_factory.mktemp("database")
    engine = create_db_engine(f"sqlite:///{database_dir / 'test.db'}")
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)
    try:
        yield testing_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


class TestRegisterEndpoint:
    def test_register_returns_token(self, client: TestClient) -> None:
        response = client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "password": "securepass123",
                "locale": "en",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["token_type"] == "bearer"
        assert data["locale"] == "en"
        assert isinstance(decode_access_token(data["access_token"]), uuid.UUID)

    def test_register_duplicate_email_returns_409(self, client: TestClient) -> None:
        payload = {"email": "dup@example.com", "password": "securepass123"}
        client.post("/auth/register", json=payload)
        response = client.post("/auth/register", json=payload)
        assert response.status_code == 409

    def test_register_short_password_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "short"},
        )
        assert response.status_code == 422


def test_legacy_register_token_route_is_not_available(
    client: TestClient,
) -> None:
    response = client.post(
        "/auth/register/token",
        json={"email": "legacy@example.com", "password": "securepass123"},
    )

    assert response.status_code == 404


class TestLoginEndpoint:
    def test_login_returns_token(self, client: TestClient) -> None:
        client.post(
            "/auth/register",
            json={"email": "login@example.com", "password": "securepass123"},
        )
        response = client.post(
            "/auth/login",
            json={"email": "login@example.com", "password": "securepass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    def test_login_returns_the_stored_parent_locale(
        self,
        client: TestClient,
    ) -> None:
        client.post(
            "/auth/register",
            json={
                "email": "french-parent@example.com",
                "password": "securepass123",
                "locale": "fr",
            },
        )

        response = client.post(
            "/auth/login",
            json={
                "email": "french-parent@example.com",
                "password": "securepass123",
            },
        )

        assert response.status_code == 200
        assert response.json()["locale"] == "fr"

    def test_login_wrong_password_returns_401(self, client: TestClient) -> None:
        client.post(
            "/auth/register",
            json={"email": "login@example.com", "password": "securepass123"},
        )
        response = client.post(
            "/auth/login",
            json={"email": "login@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    def test_login_nonexistent_email_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login",
            json={"email": "nonexistent@example.com", "password": "securepass123"},
        )
        assert response.status_code == 401
