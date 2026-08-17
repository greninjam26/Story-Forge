from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["database"] == "ok"


def test_health_degraded_when_db_down():
    client = TestClient(app)

    def boom():
        raise OSError("connection refused")

    with patch("app.main.SessionLocal") as mock_factory:
        mock_session = mock_factory.return_value.__enter__.return_value
        mock_session.execute.side_effect = boom

        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["database"] == "unreachable"
