from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.applications import CandidateConfirmationRecord, StoredApplicationRecord
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.services.ai_match import MATCHER_VERSION
from app.services.generation_context import load_stored_application_guide
from app.services.job_match_store import APPLICATION_GUIDE_STORAGE_KEY


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
        assert events_read_response.json()[0]["application_id"] == "application-linkedin-product-designer"
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
        delete_application_response = client.delete("/applications/application-linkedin-product-designer")
        applications_after_delete_response = client.get("/applications")
        events_after_application_delete_response = client.get("/applications/events")

        assert delete_application_response.status_code == 204
        assert applications_after_delete_response.status_code == 200
        assert applications_after_delete_response.json() == []
        assert events_after_application_delete_response.status_code == 200
        assert events_after_application_delete_response.json() == []
    finally:
        app.dependency_overrides.clear()


def test_applications_expose_the_generators_authoritative_analysis_revision() -> None:
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
    with testing_session_local() as db:
        db.add(
            StoredJobRecord(
                id="job-revision",
                data={
                    "id": "job-revision",
                    "title": "Authoritative title",
                    "company": "Acme",
                },
            )
        )
        for revision, created_at, positioning in (
            ("match-old", now - timedelta(minutes=5), "Old positioning"),
            ("match-current", now, "Current positioning"),
        ):
            db.add(
                JobMatchRecord(
                    id=revision,
                    job_id="job-revision",
                    profile_hash=f"profile-{revision}",
                    matcher_version=MATCHER_VERSION,
                    cache_key=f"cache-{revision}",
                    score=92,
                    source="openclaw_codex",
                    confidence="high",
                    breakdown={
                        APPLICATION_GUIDE_STORAGE_KEY: {
                            "language": "English",
                            "positioning": positioning,
                        }
                    },
                    reasons=[positioning],
                    gaps=[],
                    heuristic_score=90,
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
                            "applicationGuide": {
                                "positioning": "Client positioning"
                            },
                        },
                    },
                },
            },
        )
        list_response = client.get("/applications")
        analysis_response = client.get("/applications/application-revision/analysis")
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert analysis_response.status_code == 200
    listed_match = list_response.json()[0]["data"]["job"]["aiMatch"]
    analysis_match = analysis_response.json()["data"]["job"]["aiMatch"]
    assert listed_match == analysis_match
    assert analysis_match["revision"] == "match-current"
    assert len(analysis_match["fingerprint"]) == 64
    assert analysis_match["applicationGuide"]["positioning"] == "Current positioning"
    assert analysis_response.json()["data"]["job"]["title"] == "Authoritative title"

    with testing_session_local() as db:
        stored = db.get(StoredApplicationRecord, "application-revision")
        assert stored is not None
        assert "aiMatch" not in stored.data["job"]
        assert load_stored_application_guide(db, job_id="job-revision") == {
            "language": "English",
            "positioning": "Current positioning",
        }


def test_candidate_confirmations_are_structured_validated_and_persisted() -> None:
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
    application_id = "application-confirmations"
    job_id = "job-confirmations"

    try:
        create_response = client.post(
            "/applications",
            json={
                "id": application_id,
                "data": {
                    "id": application_id,
                    "status": "draft",
                    "job": {
                        "id": job_id,
                        "aiMatch": {
                            "version": MATCHER_VERSION,
                            "applicationGuide": {
                                "clarificationQuestions": [
                                    {
                                        "id": "client-spoof",
                                        "requirement": "Client-controlled requirement",
                                        "blocking": False,
                                    }
                                ]
                            },
                        },
                    },
                },
            },
        )
        assert create_response.status_code == 201

        unavailable_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={"confirmations": []},
        )
        assert unavailable_response.status_code == 409
        assert "Stored ai-match-v3 is required" in unavailable_response.json()["detail"]

        with testing_session_local() as db:
            db.add(
                JobMatchRecord(
                    id="match-confirmations",
                    job_id=job_id,
                    profile_hash="profile-confirmations",
                    matcher_version=MATCHER_VERSION,
                    cache_key="cache-confirmations",
                    score=80,
                    source="openclaw_codex",
                    confidence="high",
                    breakdown={
                        APPLICATION_GUIDE_STORAGE_KEY: {
                            "clarificationQuestions": [
                                {
                                    "id": "python-example",
                                    "requirement": "Production Python",
                                    "question": "Have you run Python in production?",
                                    "blocking": True,
                                },
                                {
                                    "id": "german-level",
                                    "requirement": "German C1",
                                    "question": "Do you speak German at C1 level?",
                                    "blocking": True,
                                },
                                {
                                    "id": "leadership",
                                    "requirement": "Team leadership",
                                    "question": "Have you led a team?",
                                    "blocking": False,
                                },
                            ]
                        }
                    },
                    reasons=[],
                    gaps=[],
                    heuristic_score=80,
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()

        incomplete_draft_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={
                "confirmations": [
                    {
                        "questionId": "python-example",
                        "response": "yes",
                        "exampleText": "yes",
                    },
                    {
                        "questionId": "german-level",
                        "response": "no",
                        "exampleText": "",
                    },
                ]
            },
        )
        assert incomplete_draft_response.status_code == 200
        incomplete_by_id = {
            item["questionId"]: item for item in incomplete_draft_response.json()
        }
        assert incomplete_by_id["python-example"]["exampleText"] == "yes"

        empty_draft_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={"confirmations": []},
        )
        assert empty_draft_response.status_code == 200
        assert empty_draft_response.json() == []

        unknown_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={
                "confirmations": [
                    {
                        "questionId": "client-spoof",
                        "response": "no",
                        "exampleText": "",
                    }
                ]
            },
        )
        assert unknown_response.status_code == 422
        assert "Unknown candidate confirmation" in unknown_response.json()["detail"]

        cover_context_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={
                "confirmations": [
                    {
                        "questionId": "cover-letter-recipient-name",
                        "response": "yes",
                        "exampleText": "Anna Müller",
                    },
                    {
                        "questionId": "cover-letter-company-contact",
                        "response": "yes",
                        "exampleText": "Marco Rossi",
                    },
                    {
                        "questionId": "cover-letter-additional-context",
                        "response": "yes",
                        "exampleText": "Emphasize the product mission.",
                    },
                ]
            },
        )
        assert cover_context_response.status_code == 200
        cover_context_by_id = {
            item["questionId"]: item for item in cover_context_response.json()
        }
        assert cover_context_by_id["cover-letter-recipient-name"]["exampleText"] == "Anna Müller"
        assert cover_context_by_id["cover-letter-company-contact"]["exampleText"] == "Marco Rossi"
        assert cover_context_by_id["cover-letter-company-contact"]["blocking"] is False

        client_metadata_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={
                "confirmations": [
                    {
                        "questionId": "python-example",
                        "requirement": "Client-controlled requirement",
                        "response": "no",
                        "exampleText": "",
                        "blocking": False,
                    }
                ]
            },
        )
        assert client_metadata_response.status_code == 422

        confirmations = [
            {
                "questionId": "python-example",
                "response": "yes",
                "exampleText": "Built and operated a Python API in production.",
            },
            {
                "questionId": "german-level",
                "response": "no",
                "exampleText": "",
            },
            {
                "questionId": "leadership",
                "response": "partial",
                "exampleText": "Mentored two engineers during a delivery project.",
            },
        ]
        save_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={"confirmations": confirmations},
        )
        read_response = client.get(f"/applications/{application_id}/confirmations")

        assert save_response.status_code == 200
        assert read_response.status_code == 200
        saved_by_id = {item["questionId"]: item for item in read_response.json()}
        assert saved_by_id["python-example"]["response"] == "yes"
        assert saved_by_id["python-example"]["requirement"] == "Production Python"
        assert saved_by_id["python-example"]["blocking"] is True
        assert saved_by_id["python-example"]["exampleText"].startswith("Built and operated")
        assert saved_by_id["python-example"]["updatedAt"]
        assert saved_by_id["german-level"]["response"] == "no"
        assert saved_by_id["german-level"]["exampleText"] == ""
        assert saved_by_id["leadership"]["requirement"] == "Team leadership"
        assert saved_by_id["leadership"]["blocking"] is False

        unchanged_response = client.put(
            f"/applications/{application_id}/confirmations",
            json={"confirmations": confirmations},
        )
        unchanged_by_id = {item["questionId"]: item for item in unchanged_response.json()}
        assert (
            unchanged_by_id["python-example"]["updatedAt"]
            == saved_by_id["python-example"]["updatedAt"]
        )

        delete_response = client.delete(f"/applications/{application_id}")
        assert delete_response.status_code == 204
        with testing_session_local() as db:
            assert db.query(CandidateConfirmationRecord).count() == 0
    finally:
        app.dependency_overrides.clear()
