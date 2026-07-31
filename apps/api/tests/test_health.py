from contextlib import nullcontext

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api import health as health_api
from app.main import app


def test_health_check() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_check_queries_database(monkeypatch) -> None:
    class Connection:
        def execute(self, statement) -> None:
            assert str(statement) == "SELECT 1"

    class Engine:
        def connect(self):
            return nullcontext(Connection())

    monkeypatch.setattr(health_api, "engine", Engine())
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_check_reports_unavailable_database(monkeypatch) -> None:
    class Engine:
        def connect(self):
            raise SQLAlchemyError("unavailable")

    monkeypatch.setattr(health_api, "engine", Engine())
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
