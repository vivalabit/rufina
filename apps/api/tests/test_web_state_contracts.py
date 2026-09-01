from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.applications import (
    StoredApplicationEventRecord,
    StoredApplicationRecord,
)
from app.models.jobs import StoredJobRecord


def web_state_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    with testing_session_local() as db:
        db.add_all(
            [
                StoredJobRecord(
                    owner_id="local-owner",
                    id="web-contract-job",
                    data={
                        "id": "web-contract-job",
                        "title": "Platform Engineer",
                        "company": "Example AG",
                    },
                ),
                StoredApplicationRecord(
                    owner_id="local-owner",
                    id="web-contract-application",
                    data={
                        "id": "web-contract-application",
                        "status": "applied",
                        "job": {"id": "web-contract-job"},
                    },
                ),
                StoredApplicationEventRecord(
                    owner_id="local-owner",
                    id="web-contract-event",
                    application_id="web-contract-application",
                    data={
                        "id": "web-contract-event",
                        "applicationId": "web-contract-application",
                        "type": "interview",
                        "status": "scheduled",
                    },
                ),
            ]
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_web_state_collections_expose_authoritative_revisions() -> None:
    client = web_state_client()
    try:
        job_states = client.get("/jobs/state")
        applications = client.get("/applications")
        events = client.get("/applications/events")
        profile = client.get("/profile")
        settings = client.get("/settings")
    finally:
        app.dependency_overrides.clear()

    assert job_states.status_code == 200
    assert job_states.json()[0]["jobId"] == "web-contract-job"
    assert job_states.json()[0]["revision"] == 1

    assert applications.status_code == 200
    assert applications.json()[0]["id"] == "web-contract-application"
    assert applications.json()[0]["revision"] == 1

    assert events.status_code == 200
    assert events.json()[0]["id"] == "web-contract-event"
    assert events.json()[0]["revision"] == 1

    assert profile.status_code == 200
    assert profile.headers["etag"] == '"1"'

    assert settings.status_code == 200
    assert "auto_ai_match_enabled" in settings.json()
