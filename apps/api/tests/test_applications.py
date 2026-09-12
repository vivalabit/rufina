from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.applications import StoredApplicationRecord
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.models.profile import ProfilePayload, ProfileRecord
from app.services.ai_match import (
    DEFAULT_AI_MATCH_MODEL,
    MATCH_PROMPT_VERSION,
    MATCHER_VERSION,
    build_cache_key,
    build_job_snapshot,
    build_job_snapshot_hash,
    build_profile_input_hash,
)


def test_applications_and_events_can_be_created_updated_and_read() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        application_payload = {
            "id": "application-linkedin-product-designer",
            "data": {
                "id": "application-linkedin-product-designer",
                "status": "applied",
                "appliedAt": "2026-07-06T10:00:00.000Z",
                "nextStep": "Follow up in 5 days",
                "notes": "Moved from Jobs after applying.",
                "job": {
                    "id": "linkedin-product-designer",
                    "company": "Stripe",
                    "title": "Senior Product Designer",
                    "location": "Remote",
                    "type": "Full-time",
                },
            },
        }
        event_payload = {
            "id": "application-event-phone-screen",
            "application_id": "application-linkedin-product-designer",
            "data": {
                "id": "application-event-phone-screen",
                "applicationId": "application-linkedin-product-designer",
                "type": "screening",
                "title": "Phone screen",
                "startsAt": "2026-07-11T08:00:00.000Z",
                "durationMinutes": 30,
                "timezone": "Europe/Zurich",
                "location": "Google Meet",
                "notes": "",
            },
        }

        application_create_response = client.post("/applications", json=application_payload)
        applications_read_response = client.get("/applications")
        event_create_response = client.post("/applications/events", json=event_payload)
        events_read_response = client.get("/applications/events")

        assert application_create_response.status_code == 201
        assert applications_read_response.status_code == 200
        assert applications_read_response.json()[0]["id"] == "application-linkedin-product-designer"
        assert applications_read_response.json()[0]["data"]["status"] == "applied"

        assert event_create_response.status_code == 201
        assert events_read_response.status_code == 200
        assert (
            events_read_response.json()[0]["application_id"]
            == "application-linkedin-product-designer"
        )
        assert events_read_response.json()[0]["data"]["type"] == "screening"

        updated_event_payload = {
            "id": "application-event-phone-screen",
            "application_id": "application-linkedin-product-designer",
            "data": {
                **event_payload["data"],
                "status": "completed",
                "outcome": "positive",
            },
        }

        update_event_response = client.patch(
            "/applications/events/application-event-phone-screen",
            json=updated_event_payload,
        )
        delete_event_response = client.delete("/applications/events/application-event-phone-screen")
        events_after_delete_response = client.get("/applications/events")

        assert update_event_response.status_code == 200
        assert update_event_response.json()["data"]["status"] == "completed"
        assert update_event_response.json()["data"]["outcome"] == "positive"
        assert delete_event_response.status_code == 204
        assert events_after_delete_response.status_code == 200
        assert events_after_delete_response.json() == []

        client.post("/applications/events", json=event_payload)
        delete_application_response = client.delete(
            "/applications/application-linkedin-product-designer"
        )
        applications_after_delete_response = client.get("/applications")
        events_after_application_delete_response = client.get("/applications/events")

        assert delete_application_response.status_code == 204
        assert applications_after_delete_response.status_code == 200
        assert applications_after_delete_response.json() == []
        assert events_after_application_delete_response.status_code == 200
        assert events_after_application_delete_response.json() == []
    finally:
        app.dependency_overrides.clear()


def test_applications_expose_the_current_match_without_preparation_analysis() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    now = datetime.now(UTC)
    profile = ProfilePayload()
    job_data = {
        "id": "job-revision",
        "title": "Authoritative title",
        "company": "Acme",
    }
    profile_version = build_profile_input_hash(profile)
    vacancy_version = build_job_snapshot_hash(build_job_snapshot(job_data))
    with testing_session_local() as db:
        db.add(ProfileRecord(id="default", data=profile.model_dump()))
        db.add(
            StoredJobRecord(
                id="job-revision",
                data=job_data,
            )
        )
        for revision, created_at in (
            ("match-old", now - timedelta(minutes=5)),
            ("match-current", now),
        ):
            db.add(
                JobMatchRecord(
                    id=revision,
                    job_id="job-revision",
                    profile_hash=profile_version,
                    vacancy_hash=vacancy_version,
                    model=DEFAULT_AI_MATCH_MODEL,
                    backend="openclaw_codex",
                    prompt_version=MATCH_PROMPT_VERSION,
                    matcher_version=MATCHER_VERSION,
                    cache_key=build_cache_key(
                        profile_version=profile_version,
                        vacancy_version=vacancy_version,
                        model=DEFAULT_AI_MATCH_MODEL,
                        backend="openclaw_codex",
                        prompt_version=MATCH_PROMPT_VERSION,
                    ),
                    score=92,
                    source="openclaw_codex",
                    created_at=created_at,
                )
            )
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        create_response = client.post(
            "/applications",
            json={
                "id": "application-revision",
                "data": {
                    "id": "application-revision",
                    "status": "draft",
                    "job": {
                        "id": "job-revision",
                        "title": "Client snapshot",
                        "aiMatch": {
                            "version": MATCHER_VERSION,
                            "revision": "client-spoof",
                            "fingerprint": "client-spoof",
                            "reasons": ["Client-controlled reason"],
                        },
                    },
                },
            },
        )
        list_response = client.get("/applications")
        detail_response = client.get("/applications/application-revision")
        removed_analysis_response = client.get("/applications/application-revision/analysis")
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert removed_analysis_response.status_code == 404
    listed_match = list_response.json()[0]["data"]["job"]["aiMatch"]
    detail_match = detail_response.json()["data"]["job"]["aiMatch"]
    assert listed_match == detail_match
    assert detail_match["revision"] == "match-current"
    assert len(detail_match["fingerprint"]) == 64
    assert "reasons" not in detail_match
    assert detail_match["score"] == 92
    assert "applicationGuide" not in detail_match
    assert detail_response.json()["data"]["job"]["title"] == "Authoritative title"

    with testing_session_local() as db:
        stored = db.get(StoredApplicationRecord, "application-revision")
        assert stored is not None
        assert "aiMatch" not in stored.data["job"]
