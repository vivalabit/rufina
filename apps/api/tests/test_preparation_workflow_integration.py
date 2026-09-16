import hashlib
import json
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.applications import StoredApplicationRecord
from app.models.documents import (
    DocumentAttachmentRecord,
    DocumentFileRecord,
    DocumentRecord,
    DocumentVersionRecord,
    WorkspaceSourceDocumentRecord,
)
from app.models.generation import GenerationRequest, GenerationResult
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.models.profile import ProfilePayload, ProfileRecord, ProfileVersionRecord
from app.models.resume import ResumeMasterRecord, ResumeMasterVersionRecord
from app.services.ai_match import (
    DEFAULT_AI_MATCH_MODEL,
    MATCH_PROMPT_VERSION,
    MATCHER_VERSION,
    build_cache_key,
    build_job_snapshot,
    build_job_snapshot_hash,
    build_profile_input_hash,
)
from app.services.document_generator import (
    UnavailableDocumentGenerator,
    get_document_generator,
)

OWNER_A = {"X-Rufina-Owner-Id": "workflow-owner-a"}
OWNER_B = {"X-Rufina-Owner-Id": "workflow-owner-b"}
PDF_CONTENT_TYPE = "application/pdf"
PDF_BYTES = b"%PDF-1.7\nexisting application file\n%%EOF"
PROHIBITED_GENERATION_KEYS = {
    "analysis",
    "aimatch",
    "applicationguide",
    "match",
    "matchreasons",
    "recommendations",
}


def canonical_hash(data: dict[str, object]) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def master_profile_data() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": "workflow-master-a",
        "language": "English",
        "basics": {"fullName": "Ada Lovelace"},
        "summary": None,
        "experiences": [],
        "skills": [],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [],
        "sectionOrder": [],
    }


def nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).replace("_", "").replace("-", "").casefold() for key in value} | {
            key for nested in value.values() for key in nested_keys(nested)
        }
    if isinstance(value, (list, tuple)):
        return {key for nested in value for key in nested_keys(nested)}
    return set()


class RecordingUnavailableGenerator(UnavailableDocumentGenerator):
    def __init__(self) -> None:
        super().__init__(execution_id_factory=lambda: "workflow-stub-run")
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        return super().generate(request)


@pytest.fixture
def workflow_api() -> Generator[
    tuple[TestClient, sessionmaker[Session], RecordingUnavailableGenerator],
    None,
    None,
]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    now = datetime.now(UTC)
    profile = ProfilePayload(
        name="Ada Lovelace",
        current_role="Platform Engineer",
        skills="Python\nKubernetes",
        migration={"master_resume_v1_complete": True},
    )
    profile_hash = build_profile_input_hash(profile)
    job_data = {
        "id": "workflow-job-a",
        "title": "Platform Engineer",
        "company": "Example AG",
        "overview": "Build reliable internal platforms.",
        "requirements": ["Python", "Kubernetes"],
        "match": 17,
        "analysis": {"strengths": ["Legacy match analysis"]},
        "recommendations": [{"action": "Reuse an obsolete generation plan"}],
        "aiMatch": {"score": 17, "reasons": ["Client-controlled"]},
    }
    vacancy_hash = build_job_snapshot_hash(build_job_snapshot(job_data))
    profile_data = master_profile_data()
    master = ResumeMasterRecord(
        id="workflow-master-a",
        owner_id="workflow-owner-a",
        name="Ada Lovelace",
        language="English",
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    master.versions.append(
        ResumeMasterVersionRecord(
            id="workflow-master-version-a",
            owner_id="workflow-owner-a",
            resume_master_id=master.id,
            version=1,
            schema_version="1.0",
            data=profile_data,
            content_sha256=canonical_hash(profile_data),
            created_at=now,
        )
    )
    document = DocumentRecord(
        id="workflow-document-a",
        owner_id="workflow-owner-a",
        type="cover_letter",
        title="Existing cover letter",
        job_id="workflow-job-a",
        current_version=2,
        created_at=now,
        updated_at=now,
    )
    for version in (1, 2):
        document.versions.append(
            DocumentVersionRecord(
                id=f"workflow-document-version-{version}",
                document_id=document.id,
                version=version,
                content=f"Existing cover letter version {version}",
                created_at=now,
            )
        )
        document.files.append(
            DocumentFileRecord(
                id=f"workflow-document-file-{version}",
                document_id=document.id,
                version=version,
                file_name=f"existing-cover-letter-v{version}.pdf",
                content_type=PDF_CONTENT_TYPE,
                content=f"%PDF-1.7\nversion {version}\n%%EOF".encode(),
                created_at=now,
            )
        )
    document.attachments.append(
        DocumentAttachmentRecord(
            id="workflow-document-attachment-a",
            document_id=document.id,
            application_id="workflow-application-a",
            created_at=now,
        )
    )

    with sessions() as db:
        db.add_all(
            [
                ProfileRecord(
                    id="workflow-profile-a",
                    owner_id="workflow-owner-a",
                    data=profile.model_dump(),
                ),
                ProfileVersionRecord(
                    profile_id="workflow-profile-a", owner_id="workflow-owner-a",
                    revision=1, data=profile.model_dump(), reason="fixture",
                ),
                StoredJobRecord(
                    id="workflow-job-a",
                    owner_id="workflow-owner-a",
                    data=job_data,
                ),
                JobMatchRecord(
                    id="workflow-match-a",
                    owner_id="workflow-owner-a",
                    job_id="workflow-job-a",
                    profile_hash=profile_hash,
                    vacancy_hash=vacancy_hash,
                    model=DEFAULT_AI_MATCH_MODEL,
                    backend="openclaw_codex",
                    prompt_version=MATCH_PROMPT_VERSION,
                    matcher_version=MATCHER_VERSION,
                    cache_key=build_cache_key(
                        profile_version=profile_hash,
                        vacancy_version=vacancy_hash,
                        model=DEFAULT_AI_MATCH_MODEL,
                        backend="openclaw_codex",
                        prompt_version=MATCH_PROMPT_VERSION,
                    ),
                    score=93,
                    source="openclaw_codex",
                    created_at=now,
                ),
                StoredApplicationRecord(
                    id="workflow-application-a",
                    owner_id="workflow-owner-a",
                    data={
                        "id": "workflow-application-a",
                        "status": "draft",
                        "job": {
                            "id": "workflow-job-a",
                            "match": 17,
                            "aiMatch": {"reasons": ["Client-controlled"]},
                        },
                        "applicationGuide": {"steps": ["Legacy questionnaire"]},
                    },
                ),
                master,
                document,
            ]
        )
        db.commit()

    generator = RecordingUnavailableGenerator()

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_generator] = lambda: generator
    try:
        yield TestClient(app), sessions, generator
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_document_generator, None)
        engine.dispose()


def test_rebuilt_preparation_workflow_is_independent_safe_and_owner_scoped(
    workflow_api: tuple[
        TestClient,
        sessionmaker[Session],
        RecordingUnavailableGenerator,
    ],
) -> None:
    client, sessions, generator = workflow_api

    application = client.get(
        "/applications/workflow-application-a",
        headers=OWNER_A,
    )
    assert application.status_code == 200
    match = application.json()["data"]["job"]["aiMatch"]
    assert match["score"] == 93
    assert set(match) == {
        "version",
        "profileHash",
        "vacancyHash",
        "model",
        "backend",
        "promptVersion",
        "cacheKey",
        "source",
        "score",
        "updatedAt",
        "revision",
        "fingerprint",
    }

    before_application_data = application.json()["data"]
    with sessions() as db:
        document_count_before = db.scalar(select(func.count()).select_from(DocumentRecord))
        source_count_before = db.scalar(
            select(func.count()).select_from(WorkspaceSourceDocumentRecord)
        )

    availability = client.get(
        "/applications/workflow-application-a/generation/availability",
        headers=OWNER_A,
    )
    generation = client.post(
        "/applications/workflow-application-a/generation",
        headers=OWNER_A,
        json={
            "documentTypes": ["tailored_resume", "cover_letter"],
            "language": "de-CH",
            "formattingParameters": {"tailored_resume": {"maxPages": 2}},
            "userPreferences": "Keep the application concise.",
        },
    )

    assert availability.json() == {
        "available": False,
        "code": "generator_unavailable",
        "message": "Document generation is not configured yet.",
    }
    assert generation.status_code == 200
    assert generation.json()["executionId"] == "workflow-stub-run"
    assert generation.json()["state"] == "failed"
    assert all(item["state"] == "failed" for item in generation.json()["documents"])
    assert all(item["files"] == [] for item in generation.json()["documents"])
    assert len(generator.requests) == 1
    generation_input = generator.requests[0].model_dump(mode="json", by_alias=True)
    assert nested_keys(generation_input).isdisjoint(PROHIBITED_GENERATION_KEYS)
    assert generation_input["vacancy"]["fullDescription"].startswith(
        "Overview\nBuild reliable internal platforms."
    )
    assert generation_input["masterProfileVersion"]["version"] == 1

    unchanged_application = client.get(
        "/applications/workflow-application-a",
        headers=OWNER_A,
    )
    assert unchanged_application.json()["data"] == before_application_data
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == document_count_before
        assert (
            db.scalar(select(func.count()).select_from(WorkspaceSourceDocumentRecord))
            == source_count_before
        )

    documents = client.get(
        "/documents",
        params={"applicationId": "workflow-application-a"},
        headers=OWNER_A,
    )
    assert documents.status_code == 200
    assert documents.json()[0]["currentVersion"] == 2
    assert documents.json()[0]["versionsTotal"] == 2
    old_download = client.get(
        "/documents/workflow-document-a/download",
        params={"version": 1},
        headers=OWNER_A,
    )
    old_preview = client.get(
        "/documents/workflow-document-a/pdf",
        params={"version": 1},
        headers=OWNER_A,
    )
    assert old_download.status_code == 200
    assert old_download.content == b"%PDF-1.7\nversion 1\n%%EOF"
    assert old_preview.status_code == 200
    assert old_preview.content == old_download.content

    uploaded = client.post(
        "/documents/workspace-sources/upload",
        params={
            "applicationId": "workflow-application-a",
            "category": "Application Attachment",
            "title": "Existing certificate",
            "fileName": "certificate.pdf",
        },
        content=PDF_BYTES,
        headers={**OWNER_A, "Content-Type": PDF_CONTENT_TYPE},
    )
    assert uploaded.status_code == 201
    source_id = uploaded.json()["id"]
    source_preview = client.get(
        f"/documents/workspace-sources/{source_id}/download",
        params={"applicationId": "workflow-application-a", "preview": True},
        headers=OWNER_A,
    )
    source_download = client.get(
        f"/documents/workspace-sources/{source_id}/download",
        params={"applicationId": "workflow-application-a"},
        headers=OWNER_A,
    )
    assert source_preview.status_code == 200
    assert source_preview.content == PDF_BYTES
    assert source_preview.headers["content-disposition"].startswith("inline;")
    assert source_download.status_code == 200
    assert source_download.content == PDF_BYTES
    assert source_download.headers["content-disposition"].startswith("attachment;")

    revision = unchanged_application.json()["revision"]
    submission = {
        "tailored_resume": {"documentId": f"source-{source_id}", "version": None},
        "cover_letter": {"documentId": "workflow-document-a", "version": 1},
    }
    applied = client.patch(
        "/applications/workflow-application-a",
        headers={**OWNER_A, "If-Match": f'"{revision}"'},
        json={
            "revision": revision,
            "data": {
                "status": "applied",
                "documentPreparation": {
                    "documentTypes": ["tailored_resume", "cover_letter"],
                    "language": "German",
                    "formatting": {"pageSize": "A4", "resumeMaxPages": 2},
                    "submission": submission,
                    "latestGeneration": None,
                    "userPreferences": "Keep the application concise.",
                },
            },
        },
    )
    reloaded = client.get(
        "/applications/workflow-application-a",
        headers=OWNER_A,
    )
    assert applied.status_code == 200
    assert reloaded.json()["data"]["status"] == "applied"
    assert reloaded.json()["data"]["documentPreparation"]["submission"] == submission

    assert client.get("/applications", headers=OWNER_B).json() == []
    assert (
        client.get(
            "/applications/workflow-application-a",
            headers=OWNER_B,
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/applications/workflow-application-a/generation/availability",
            headers=OWNER_B,
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/documents/workflow-document-a/download",
            headers=OWNER_B,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/documents/workspace-sources/{source_id}/download",
            params={"applicationId": "workflow-application-a"},
            headers=OWNER_B,
        ).status_code
        == 404
    )
    assert len(generator.requests) == 1
