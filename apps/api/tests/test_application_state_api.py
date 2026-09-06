from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.applications import StoredApplicationRecord


def state_api_client() -> tuple[TestClient, sessionmaker[Session]]:
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

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), testing_session_local


def test_point_application_and_event_writes_use_revisions() -> None:
    client, testing_session_local = state_api_client()
    try:
        rejected_created = client.post(
            "/applications",
            json={
                "id": "application-point-api",
                "data": {
                    "id": "application-point-api",
                    "status": "draft",
                    "notes": "Keep this field",
                    "documents": [
                        {
                            "id": "legacy-inline-document",
                            "dataUrl": "data:application/pdf;base64,JVBERi0=",
                        }
                    ],
                },
            },
        )
        assert rejected_created.status_code == 422

        rejected_nested_file = client.post(
            "/applications",
            json={
                "id": "application-point-api",
                "data": {
                    "id": "application-point-api",
                    "metadata": {"payload": {"data_url": "data:application/pdf;base64,JVBERi0="}},
                },
            },
        )
        assert rejected_nested_file.status_code == 422

        created = client.post(
            "/applications",
            json={
                "id": "application-point-api",
                "data": {
                    "id": "application-point-api",
                    "status": "draft",
                    "notes": "Keep this field",
                    "documents": [],
                },
            },
        )
        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        assert created.json()["revision"] == 1
        assert created.json()["created_at"]
        assert created.json()["updated_at"]
        assert "documents" not in created.json()["data"]

        rejected_patch = client.patch(
            "/applications/application-point-api",
            headers={"If-Match": '"1"'},
            json={
                "data": {
                    "status": "applied",
                    "documents": [{"id": "patch-inline-document"}],
                }
            },
        )
        assert rejected_patch.status_code == 422

        patched = client.patch(
            "/applications/application-point-api",
            headers={"If-Match": '"1"'},
            json={"data": {"status": "applied"}},
        )
        assert patched.status_code == 200
        assert patched.headers["etag"] == '"2"'
        assert patched.json()["revision"] == 2
        assert patched.json()["data"]["status"] == "applied"
        assert patched.json()["data"]["notes"] == "Keep this field"
        assert "documents" not in patched.json()["data"]

        stale_patch = client.patch(
            "/applications/application-point-api",
            headers={"If-Match": '"1"'},
            json={"data": {"status": "rejected"}},
        )
        assert stale_patch.status_code == 412
        assert stale_patch.json()["detail"]["current_revision"] == 2

        fetched = client.get("/applications/application-point-api")
        assert fetched.status_code == 200
        assert "documents" not in fetched.json()["data"]
        with testing_session_local() as db:
            stored = db.get(StoredApplicationRecord, "application-point-api")
            assert stored is not None
            assert "documents" not in stored.data

        event_created = client.post(
            "/applications/events",
            json={
                "id": "event-point-api",
                "application_id": "application-point-api",
                "data": {"type": "screening", "title": "Phone screen"},
            },
        )
        assert event_created.status_code == 201
        assert event_created.json()["revision"] == 1

        rejected_event_file = client.post(
            "/applications/events",
            json={
                "id": "event-with-file",
                "application_id": "application-point-api",
                "data": {"notes": '{"dataUrl":"data:image/png;base64,aW1hZ2U="}'},
            },
        )
        assert rejected_event_file.status_code == 422

        event_patched = client.patch(
            "/applications/events/event-point-api",
            json={"data": {"status": "completed"}, "revision": 1},
        )
        assert event_patched.status_code == 200
        assert event_patched.json()["revision"] == 2
        assert event_patched.json()["data"] == {
            "type": "screening",
            "title": "Phone screen",
            "status": "completed",
        }

        stale_delete = client.delete(
            "/applications/events/event-point-api",
            headers={"If-Match": '"1"'},
        )
        assert stale_delete.status_code == 412
        assert client.get("/applications/events/event-point-api").status_code == 200

        deleted = client.delete(
            "/applications/events/event-point-api",
            headers={"If-Match": '"2"'},
        )
        assert deleted.status_code == 204
    finally:
        app.dependency_overrides.clear()


def test_legacy_bulk_application_writes_are_not_available() -> None:
    client, _ = state_api_client()
    try:
        assert client.put(
            "/applications",
            json={"applications": []},
        ).status_code == 405
        assert client.put(
            "/applications/events",
            json={"events": []},
        ).status_code == 405
    finally:
        app.dependency_overrides.clear()


def test_application_preferences_are_owner_scoped_and_revisioned() -> None:
    client, _ = state_api_client()
    owner_a = {"X-Rufina-Owner-Id": "owner-a"}
    owner_b = {"X-Rufina-Owner-Id": "owner-b"}
    try:
        created = client.post(
            "/applications",
            headers=owner_a,
            json={
                "id": "application-preferences",
                "data": {"id": "application-preferences", "status": "draft"},
            },
        )
        assert created.status_code == 201

        absent = client.get(
            "/applications/application-preferences/preferences",
            headers=owner_a,
        )
        assert absent.status_code == 404

        saved = client.put(
            "/applications/application-preferences/preferences",
            headers=owner_a,
            json={
                "resume_template_id": "classic_single",
                "resume_generation_mode": "recruiter_xyz_ats",
            },
        )
        assert saved.status_code == 200
        assert saved.headers["etag"] == '"1"'
        assert saved.json()["revision"] == 1

        updated = client.patch(
            "/applications/application-preferences/preferences",
            headers={**owner_a, "If-Match": 'W/"1"'},
            json={"resume_template_id": "modern_single"},
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2
        assert updated.json()["resume_template_id"] == "modern_single"
        assert updated.json()["resume_generation_mode"] == "recruiter_xyz_ats"

        empty_patch = client.patch(
            "/applications/application-preferences/preferences",
            headers=owner_a,
            json={"revision": 2},
        )
        assert empty_patch.status_code == 422

        stale = client.patch(
            "/applications/application-preferences/preferences",
            headers=owner_a,
            json={"resume_generation_mode": "imaginator", "revision": 1},
        )
        assert stale.status_code == 412

        foreign = client.get(
            "/applications/application-preferences/preferences",
            headers=owner_b,
        )
        assert foreign.status_code == 404

        deleted = client.delete(
            "/applications/application-preferences/preferences",
            headers={**owner_a, "If-Match": '"2"'},
        )
        assert deleted.status_code == 204
    finally:
        app.dependency_overrides.clear()
