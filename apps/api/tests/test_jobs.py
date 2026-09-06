from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.jobs import StoredJobRecord


def test_manual_jobs_can_be_upserted_but_parser_imports_require_screening() -> None:
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
        payload = {
            "jobs": [
                {
                    "id": "linkedin-product-designer",
                    "data": {
                        "id": "linkedin-product-designer",
                        "company": "Figma",
                        "title": "Product Designer",
                        "location": "Remote",
                        "type": "Full-time",
                        "salary": "Not specified",
                        "posted": "LinkedIn",
                        "experience": "Mid-Senior level",
                        "department": "LinkedIn import",
                        "match": 72,
                        "logo": "linkedin",
                    },
                },
                {
                    "id": "manual-job-product-designer",
                    "data": {
                        "id": "manual-job-product-designer",
                        "company": "Figma",
                        "title": "Manually added Product Designer",
                        "location": "Remote",
                        "type": "Full-time",
                        "salary": "Not specified",
                        "posted": "Today",
                        "experience": "Mid-Senior level",
                        "department": "Manual",
                        "match": 0,
                        "logo": "manual",
                        "archived": True,
                        "archivedAt": "2026-09-01T12:00:00Z",
                    },
                }
            ]
        }

        upsert_response = client.put("/jobs", json=payload)
        read_response = client.get("/jobs")

        assert upsert_response.status_code == 200
        assert read_response.status_code == 200
        assert [item["id"] for item in read_response.json()] == [
            "manual-job-product-designer"
        ]
        assert read_response.json()[0]["data"]["title"] == (
            "Manually added Product Designer"
        )
        assert "archived" not in read_response.json()[0]["data"]
        assert "archivedAt" not in read_response.json()[0]["data"]
    finally:
        app.dependency_overrides.clear()


def test_job_can_be_deleted() -> None:
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
        payload = {
            "jobs": [
                {
                    "id": "linkedin-product-designer",
                    "data": {
                        "id": "linkedin-product-designer",
                        "company": "Figma",
                        "title": "Product Designer",
                        "location": "Remote",
                        "type": "Full-time",
                        "salary": "Not specified",
                        "posted": "LinkedIn",
                        "experience": "Mid-Senior level",
                        "department": "LinkedIn import",
                        "match": 72,
                        "logo": "linkedin",
                    },
                }
            ]
        }

        with testing_session_local() as db:
            db.add(
                StoredJobRecord(
                    owner_id="local-owner",
                    id="linkedin-product-designer",
                    data=payload["jobs"][0]["data"],
                    status="active",
                )
            )
            db.commit()
        delete_response = client.delete("/jobs/linkedin-product-designer")
        read_response = client.get("/jobs")

        assert delete_response.status_code == 204
        assert read_response.status_code == 200
        assert read_response.json() == []

        with testing_session_local() as db:
            dismissed_job = db.get(
                StoredJobRecord,
                ("local-owner", "linkedin-product-designer"),
            )
            assert dismissed_job is not None
            assert dismissed_job.status == "dismissed"
            assert dismissed_job.dismissed_at is not None
            assert dismissed_job.data["title"] == "Product Designer"

        repeated_upsert_response = client.put("/jobs", json=payload)
        assert repeated_upsert_response.status_code == 200
        assert repeated_upsert_response.json() == []
        states = client.get("/jobs/state").json()
        assert states[0]["jobId"] == "linkedin-product-designer"
        assert states[0]["dismissed"] is True
    finally:
        app.dependency_overrides.clear()


def test_missing_job_delete_creates_a_tombstone_that_blocks_future_upserts() -> None:
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
        job_id = "indeed-hidden-vacancy"
        assert client.delete(f"/jobs/{job_id}").status_code == 204
        assert client.put(
            "/jobs",
            json={"jobs": [{"id": job_id, "data": {"id": job_id, "title": "Hidden"}}]},
        ).json() == []
        states = client.get("/jobs/state").json()
        assert states[0]["jobId"] == job_id
        assert states[0]["dismissed"] is True
    finally:
        app.dependency_overrides.clear()


def test_legacy_job_state_import_and_dismissed_id_routes_are_not_available() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        assert client.post(
            "/jobs/state/import",
            json={"states": []},
        ).status_code == 404
        assert client.get("/jobs/dismissed-ids").status_code == 405
        assert client.put(
            "/jobs/dismissed-ids",
            json={"job_ids": []},
        ).status_code == 405
    finally:
        app.dependency_overrides.clear()


def test_job_state_patch_requires_and_advances_revision() -> None:
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
        with testing_session_local() as db:
            db.add(
                StoredJobRecord(
                    owner_id="local-owner",
                    id="stateful-job",
                    data={"id": "stateful-job", "title": "Stateful vacancy"},
                )
            )
            db.commit()

        initial_response = client.get("/jobs/stateful-job/state")
        assert initial_response.status_code == 200
        assert initial_response.headers["etag"] == '"1"'
        assert initial_response.json() == {
            "jobId": "stateful-job",
            "saved": False,
            "archived": False,
            "dismissed": False,
            "savedAt": None,
            "archivedAt": None,
            "dismissedAt": None,
            "updatedAt": initial_response.json()["updatedAt"],
            "revision": 1,
        }

        missing_precondition = client.patch(
            "/jobs/stateful-job/state",
            json={"saved": True},
        )
        assert missing_precondition.status_code == 428

        saved_response = client.patch(
            "/jobs/stateful-job/state",
            json={"saved": True, "archived": True, "revision": 1},
        )
        assert saved_response.status_code == 200
        assert saved_response.headers["etag"] == '"2"'
        assert saved_response.json()["saved"] is True
        assert saved_response.json()["archived"] is True
        assert saved_response.json()["revision"] == 2
        assert saved_response.json()["savedAt"] is not None
        assert saved_response.json()["archivedAt"] is not None

        stale_body_response = client.patch(
            "/jobs/stateful-job/state",
            json={"saved": False, "revision": 1},
        )
        assert stale_body_response.status_code == 409
        assert stale_body_response.json()["detail"]["currentRevision"] == 2

        conflicting_preconditions = client.patch(
            "/jobs/stateful-job/state",
            headers={"If-Match": '"2"'},
            json={"archived": False, "revision": 1},
        )
        assert conflicting_preconditions.status_code == 400

        restored_response = client.patch(
            "/jobs/stateful-job/state",
            headers={"If-Match": saved_response.headers["etag"]},
            json={"archived": False},
        )
        assert restored_response.status_code == 200
        assert restored_response.headers["etag"] == '"3"'
        assert restored_response.json()["archived"] is False
        assert restored_response.json()["archivedAt"] is None
        assert restored_response.json()["saved"] is True

        stale_header_response = client.patch(
            "/jobs/stateful-job/state",
            headers={"If-Match": '"2"'},
            json={"saved": False},
        )
        assert stale_header_response.status_code == 412
        assert stale_header_response.json()["detail"]["currentRevision"] == 3

        collection_response = client.get("/jobs/state")
        assert collection_response.status_code == 200
        assert collection_response.json() == [restored_response.json()]
    finally:
        app.dependency_overrides.clear()
