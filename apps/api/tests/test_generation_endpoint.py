import hashlib
import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.applications import StoredApplicationRecord
from app.models.documents import DocumentRecord
from app.models.generation_runs import ApplicationGenerationRunRecord
from app.models.jobs import StoredJobRecord
from app.models.resume import ResumeMasterRecord, ResumeMasterVersionRecord
from app.services import ai_backend
from app.services.document_generator import get_document_generator
from app.services.generation_examples import ExampleDocumentGenerator


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
        "id": "master-profile",
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


@pytest.fixture
def generation_api() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    profile_data = master_profile_data()
    master = ResumeMasterRecord(
        id="master-profile",
        name="Ada Lovelace",
        language="English",
        current_version=1,
    )
    master.versions.append(
        ResumeMasterVersionRecord(
            id="master-profile-version",
            resume_master_id=master.id,
            version=1,
            schema_version="1.0",
            data=profile_data,
            content_sha256=canonical_hash(profile_data),
        )
    )
    with sessions() as db:
        db.add_all(
            [
                StoredApplicationRecord(
                    id="application-1",
                    data={
                        "id": "application-1",
                        "status": "draft",
                        "job": {"id": "vacancy-1"},
                    },
                ),
                StoredJobRecord(
                    id="vacancy-1",
                    data={
                        "id": "vacancy-1",
                        "title": "Platform Engineer",
                        "company": "Example AG",
                        "overview": "Build reliable platforms.",
                    },
                ),
                master,
            ]
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), sessions
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_document_generator, None)
        engine.dispose()


def generation_payload() -> dict[str, object]:
    return {
        "documentTypes": ["tailored_resume", "cover_letter"],
        "language": "de-CH",
        "formattingParameters": {"tailored_resume": {"maxPages": 2}},
        "userPreferences": "Keep it concise.",
    }


@pytest.mark.parametrize("template_id", ["moderncv_banking", "roman"])
def test_run_endpoint_persists_selected_resume_template(
    generation_api: tuple[TestClient, sessionmaker[Session]],
    template_id: str,
) -> None:
    client, sessions = generation_api
    response = client.post(
        "/applications/application-1/generation/runs",
        json={
            **generation_payload(),
            "documentTypes": ["tailored_resume"],
            "formattingParameters": {"tailored_resume": {"templateId": template_id}},
            "idempotencyKey": "template-selection",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["events"][0]["data"]["resumeTemplateId"] == template_id
    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, payload["id"])
        assert run is not None
        assert run.input_snapshot["templates"][0]["templateId"] == template_id


def test_run_endpoint_rejects_unknown_resume_template_without_creating_a_run(
    generation_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = generation_api
    response = client.post(
        "/applications/application-1/generation/runs",
        json={
            **generation_payload(),
            "documentTypes": ["tailored_resume"],
            "formattingParameters": {"tailored_resume": {"templateId": "not-a-template"}},
            "idempotencyKey": "template-selection",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resume_template_unsupported"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(ApplicationGenerationRunRecord)) == 0


def test_endpoint_uses_safe_stub_without_ai_documents_or_application_changes(
    generation_api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sessions = generation_api

    def reject_ai_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("The unavailable generator must not invoke AI")

    monkeypatch.setattr(ai_backend.OpenAIAPIBackend, "generate", reject_ai_call)
    monkeypatch.setattr(ai_backend.OpenClawCodexBackend, "generate", reject_ai_call)

    availability = client.get(
        "/applications/application-1/generation/availability",
    )
    response = client.post(
        "/applications/application-1/generation",
        json=generation_payload(),
    )

    assert availability.status_code == 200
    assert availability.json() == {
        "available": False,
        "code": "generator_unavailable",
        "message": "Document generation is not configured yet.",
    }
    assert response.status_code == 200
    assert response.json()["state"] == "failed"
    assert response.json()["error"] == {
        "code": "generator_unavailable",
        "message": "Document generation is not configured yet.",
        "retryable": False,
    }
    assert [item["state"] for item in response.json()["documents"]] == [
        "failed",
        "failed",
    ]
    assert all(item["files"] == [] for item in response.json()["documents"])

    with sessions() as db:
        application = db.get(StoredApplicationRecord, "application-1")
        document_count = db.scalar(select(func.count()).select_from(DocumentRecord))
    assert application is not None
    assert application.data["status"] == "draft"
    assert document_count == 0


def test_endpoint_generator_dependency_is_replaceable_for_development(
    generation_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = generation_api
    app.dependency_overrides[get_document_generator] = lambda: ExampleDocumentGenerator(
        "partial",
        execution_id="dev-partial",
    )

    availability = client.get(
        "/applications/application-1/generation/availability",
    )
    response = client.post(
        "/applications/application-1/generation",
        json=generation_payload(),
    )

    assert availability.status_code == 200
    assert availability.json()["available"] is True
    assert availability.json()["code"] == "available"
    assert response.status_code == 200
    assert response.json()["executionId"] == "dev-partial"
    assert response.json()["state"] == "completed"
    assert [item["state"] for item in response.json()["documents"]] == [
        "completed",
        "failed",
    ]


def test_generation_availability_requires_an_owned_application(
    generation_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = generation_api

    missing = client.get("/applications/missing/generation/availability")
    foreign = client.get(
        "/applications/application-1/generation/availability",
        headers={"X-Rufina-Owner-Id": "another-owner"},
    )

    assert missing.status_code == 404
    assert foreign.status_code == 404


def test_versioned_run_endpoint_lists_and_restores_the_immutable_run(
    generation_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = generation_api
    payload = {
        **generation_payload(),
        "idempotencyKey": "application-ui-run",
    }

    started = client.post(
        "/applications/application-1/generation/runs",
        json=payload,
    )
    current = client.get(
        "/applications/application-1/generation/runs/current",
    )
    history = client.get(
        "/applications/application-1/generation/runs",
    )
    foreign_history = client.get(
        "/applications/application-1/generation/runs",
        headers={"X-Rufina-Owner-Id": "another-owner"},
    )

    assert started.status_code == 202
    assert current.status_code == 200
    assert current.json()["id"] == started.json()["id"]
    assert current.json()["inputFingerprint"] == started.json()["inputFingerprint"]
    assert history.status_code == 200
    assert [run["id"] for run in history.json()] == [started.json()["id"]]
    assert history.json()[0]["events"][0]["data"] == {
        "inputFingerprint": started.json()["inputFingerprint"],
        "applicationRevision": 1,
        "vacancyRevision": 1,
        "masterProfileVersion": 2,
        "resumeTemplateId": "moderncv_banking",
        "documentTemplateId": "moderncv_banking",
    }
    assert foreign_history.status_code == 200
    assert foreign_history.json() == []


def test_versioned_run_endpoint_rejects_mixed_document_templates(generation_api) -> None:
    client, _ = generation_api
    response = client.post(
        "/applications/application-1/generation/runs",
        json={
            **generation_payload(),
            "documentTypes": ["tailored_resume", "cover_letter"],
            "formattingParameters": {
                "tailored_resume": {"templateId": "roman"},
                "cover_letter": {"templateId": "moderncv_banking"},
            },
            "idempotencyKey": "mismatched-template-run",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_template_mismatch"
    assert client.get("/applications/application-1/generation/runs").json() == []
