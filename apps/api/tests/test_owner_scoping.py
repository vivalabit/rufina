from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.identity import current_owner_id
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.applications import CandidateConfirmationRecord, StoredApplicationRecord
from app.models.documents import (
    DocumentFileRecord,
    DocumentPackJobRecord,
    DocumentRecord,
    DocumentTemplateRecord,
    DocumentVersionRecord,
)
from app.models.jobs import JobMatchFeedbackRecord, StoredJobRecord


def test_application_data_is_scoped_to_request_owner() -> None:
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

    now = datetime.now(UTC)
    with testing_session_local() as db:
        for owner_id, suffix in (("owner-a", "a"), ("owner-b", "b")):
            application = StoredApplicationRecord(
                id=f"application-{suffix}",
                owner_id=owner_id,
                data={"id": f"application-{suffix}", "status": "draft"},
            )
            template = DocumentTemplateRecord(
                id=f"template-{suffix}",
                owner_id=owner_id,
                type="tailored_resume",
                name=f"Template {suffix}",
                file_name=f"template-{suffix}.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                content_sha256="a" * 64,
                content=b"same-template",
                extracted_text="",
                created_at=now,
                updated_at=now,
            )
            document = DocumentRecord(
                id=f"document-{suffix}",
                owner_id=owner_id,
                type="tailored_resume",
                title=f"Document {suffix}",
                current_version=1,
                created_at=now,
                updated_at=now,
            )
            document.versions.append(
                DocumentVersionRecord(
                    id=f"version-{suffix}",
                    document_id=document.id,
                    version=1,
                    content='{"replacements": []}',
                    created_at=now,
                )
            )
            document.files.append(
                DocumentFileRecord(
                    id=f"file-{suffix}",
                    document_id=document.id,
                    version=1,
                    template_id=template.id,
                    content=f"rendered-{suffix}".encode(),
                    created_at=now,
                )
            )
            db.add_all(
                [
                    application,
                    CandidateConfirmationRecord(
                        application_id=application.id,
                        question_id=f"question-{suffix}",
                        owner_id=owner_id,
                        requirement="Requirement",
                        response="yes",
                        example_text="Evidence",
                        blocking=False,
                        updated_at=now,
                    ),
                    template,
                    document,
                    DocumentPackJobRecord(
                        id=f"pack-{suffix}",
                        owner_id=owner_id,
                        request_fingerprint=suffix * 64,
                        application_id=application.id,
                        persistence_mode="atomic",
                        status="completed",
                        document_ids=[document.id],
                        stages=[],
                        message="completed",
                        created_at=now,
                        updated_at=now,
                        expires_at=now + timedelta(days=1),
                    ),
                    StoredJobRecord(
                        owner_id=owner_id,
                        id="shared-job",
                        data={
                            "id": "shared-job",
                            "title": f"Vacancy {suffix}",
                        },
                    ),
                ]
            )
        db.commit()

    owner_a = {"X-Rufina-Owner-Id": "owner-a"}
    owner_b = {"X-Rufina-Owner-Id": "owner-b"}
    legacy_owner_a = {"X-Tasko-Owner-Id": "owner-a"}
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        applications_a = client.get("/applications", headers=owner_a)
        applications_b = client.get("/applications", headers=owner_b)
        applications_a_legacy_header = client.get(
            "/applications",
            headers=legacy_owner_a,
        )
        conflicting_owner_headers = client.get(
            "/applications",
            headers={
                "X-Rufina-Owner-Id": "owner-a",
                "X-Tasko-Owner-Id": "owner-b",
            },
        )
        confirmations_a = client.get(
            "/applications/application-a/confirmations",
            headers=owner_a,
        )
        foreign_confirmations = client.get(
            "/applications/application-a/confirmations",
            headers=owner_b,
        )
        templates_a = client.get("/documents/templates/library", headers=owner_a)
        templates_b = client.get("/documents/templates/library", headers=owner_b)
        resume_templates_a = client.get(
            "/documents/resume-templates",
            headers=owner_a,
        )
        resume_templates_b = client.get(
            "/documents/resume-templates",
            headers=owner_b,
        )
        documents_a = client.get("/documents", headers=owner_a)
        documents_b = client.get("/documents", headers=owner_b)
        own_download = client.get("/documents/document-a/download", headers=owner_a)
        foreign_document = client.get("/documents/document-a", headers=owner_b)
        foreign_download = client.get("/documents/document-a/download", headers=owner_b)
        own_pack = client.get(
            "/documents/packs/pack-a?applicationId=application-a",
            headers=owner_a,
        )
        foreign_pack = client.get(
            "/documents/packs/pack-a?applicationId=application-a",
            headers=owner_b,
        )
        created_for_b = client.put(
            "/applications",
            headers=owner_b,
            json={
                "applications": [
                    {
                        "id": "created-for-b",
                        "data": {"id": "created-for-b", "status": "draft"},
                    }
                ]
            },
        )
        jobs_a = client.get("/jobs", headers=owner_a)
        jobs_b = client.get("/jobs", headers=owner_b)
        feedback_a = client.post(
            "/jobs/shared-job/match-feedback",
            headers=owner_a,
            json={"feedback": "good_match"},
        )
        feedback_b = client.post(
            "/jobs/shared-job/match-feedback",
            headers=owner_b,
            json={"feedback": "not_interested"},
        )
    finally:
        app.dependency_overrides.clear()

    assert [item["id"] for item in applications_a.json()] == ["application-a"]
    assert [item["id"] for item in applications_b.json()] == ["application-b"]
    assert [item["id"] for item in applications_a_legacy_header.json()] == [
        "application-a"
    ]
    assert conflicting_owner_headers.status_code == 400
    assert [item["questionId"] for item in confirmations_a.json()] == ["question-a"]
    assert foreign_confirmations.status_code == 404
    assert templates_a.json() == []
    assert templates_b.json() == []
    assert [item["id"] for item in resume_templates_a.json()] == [
        "classic_single",
        "modern_single",
        "modern_two_column",
        "swiss_classic",
        "swiss_local_german",
    ]
    assert resume_templates_b.json() == resume_templates_a.json()
    assert [item["id"] for item in documents_a.json()] == ["document-a"]
    assert [item["id"] for item in documents_b.json()] == ["document-b"]
    assert own_download.status_code == 200
    assert own_download.content == b"rendered-a"
    assert foreign_document.status_code == 404
    assert foreign_download.status_code == 404
    assert own_pack.status_code == 410
    assert foreign_pack.status_code == 410
    assert {item["id"] for item in created_for_b.json()} == {
        "application-b",
        "created-for-b",
    }
    assert jobs_a.json()[0]["data"]["title"] == "Vacancy a"
    assert jobs_b.json()[0]["data"]["title"] == "Vacancy b"
    assert feedback_a.status_code == 200
    assert feedback_b.status_code == 200
    with testing_session_local() as db:
        assert db.get(StoredApplicationRecord, "created-for-b").owner_id == "owner-b"
        assert db.get(StoredJobRecord, ("owner-a", "shared-job")).data["title"] == "Vacancy a"
        assert db.get(StoredJobRecord, ("owner-b", "shared-job")).data["title"] == "Vacancy b"
        feedback_by_owner = {
            record.owner_id: record.feedback
            for record in db.query(JobMatchFeedbackRecord).all()
        }
        assert feedback_by_owner == {
            "owner-a": "good_match",
            "owner-b": "not_interested",
        }
    owner_token = current_owner_id.set("owner-a")
    try:
        with testing_session_local() as db:
            assert {
                record.feedback for record in db.query(JobMatchFeedbackRecord).all()
            } == {"good_match"}
    finally:
        current_owner_id.reset(owner_token)


def test_non_local_requests_require_authenticated_owner_identity() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="production")
    client = TestClient(app)
    try:
        response = client.get("/applications")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Authenticated owner identity is required"
