import app.ratelimit as rl
from app.config import settings


def test_disabled_by_default(client):
    for i in range(30):
        response = client.post(
            "/auth/register",
            json={
                "email": f"parent{i}@example.com",
                "password": "password123",
            },
        )
        assert response.status_code == 201


def test_register_enforced_when_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_requests_per_window", 3)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    rl._hits.clear()
    try:
        codes = [
            client.post(
                "/auth/register",
                json={
                    "email": f"u{i}@example.com",
                    "password": "password123",
                },
            ).status_code
            for i in range(5)
        ]
        assert codes.count(201) == 3
        assert codes.count(429) == 2
    finally:
        rl._hits.clear()


def test_login_enforced_when_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_requests_per_window", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    rl._hits.clear()
    try:
        client.post(
            "/auth/register",
            json={
                "email": "login-test@example.com",
                "password": "password123",
            },
        )
        codes = [
            client.post(
                "/auth/login",
                json={
                    "email": "login-test@example.com",
                    "password": "password123",
                },
            ).status_code
            for _ in range(4)
        ]
        assert codes.count(200) == 2
        assert codes.count(429) == 2
    finally:
        rl._hits.clear()
