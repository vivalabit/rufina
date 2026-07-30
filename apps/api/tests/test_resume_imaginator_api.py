from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import resume_tailoring as resume_tailoring_api
from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.documents import DocumentFileRecord
from app.models.jobs import StoredJobRecord
from app.models.resume import (
    ImaginatorDraft,
    ImaginatorProtectedFactsAudit,
    ImaginatorProtectedFactsAuditAttestation,
    ImaginatorResumeMetrics,
    ImaginatorResumeRecord,
    MasterResume,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
)
from app.services import resume_imaginator as resume_imaginator_service
from app.services.ai_backend import AIResult, AIUsage
from app.services.ai_privacy import require_current_ai_consent
from app.services.resume_imaginator import (
    ImaginatorOutcome,
    ResumeImaginatorError,
    assemble_imaginator_resume,
    build_imaginator_protected_facts_audit_prompt,
    imaginator_auditable_claims,
    persist_imaginator_resume,
)
from app.services.resume_tailoring import ResumeTailoringError

MASTER_ID = "a" * 32
MASTER_VERSION_ID = "b" * 32
GENERATION_ID = "c" * 32
JOB_ID = "job-imaginator-api"


@pytest.fixture(autouse=True)
def bypass_ai_consent_boundary() -> Generator[None, None, None]:
    app.dependency_overrides[require_current_ai_consent] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def api_sessions() -> Generator[sessionmaker[Session], None, None]:
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
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True,
    )
    try:
        yield testing_session_local
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        engine.dispose()


def source_resume() -> MasterResume:
    return MasterResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": MASTER_ID,
            "language": "English",
            "basics": {
                "fullName": "Ada Lovelace",
                "headline": "Platform Engineer",
                "email": "ada@example.test",
                "location": "Zurich",
            },
            "summary": None,
            "experiences": [
                {
                    "id": "experience:acme",
                    "company": "Acme AG",
                    "title": "Platform Engineer",
                    "location": "Zurich",
                    "startDate": "2022",
                    "isCurrent": True,
                    "bullets": [
                        {
                            "id": "bullet:acme:one",
                            "text": "Built reliable services.",
                            "evidenceIds": ["profile:acme:one"],
                        }
                    ],
                }
            ],
            "skills": [],
            "education": [
                {
                    "id": "education:eth",
                    "institution": "ETH Zürich",
                    "credential": "MSc",
                    "fieldOfStudy": "Computer Science",
                    "location": "Zurich",
                    "startDate": "2018",
                    "endDate": "2020",
                    "details": [],
                }
            ],
            "projects": [],
            "certifications": [],
            "languages": [],
            "additionalSections": [],
            "evidence": [
                {
                    "id": "profile:acme:one",
                    "type": "profile",
                    "text": "Built reliable services at Acme AG.",
                }
            ],
            "sectionOrder": ["experience", "education"],
        }
    )


def generated_draft() -> ImaginatorDraft:
    return ImaginatorDraft.model_validate(
        {
            "headline": "Principal AI Platform Architect",
            "summary": "Principal architect delivering global AI platforms.",
            "experiences": [
                {
                    "masterExperienceId": "experience:acme",
                    "title": "Principal AI Platform Architect",
                    "location": "Zurich",
                    "period": "2022 — Present",
                    "bullets": [
                        "Scaled an AI platform to millions of requests.",
                    ],
                }
            ],
            "omittedExperiences": [],
            "skillGroups": [
                {
                    "category": "Data & AI",
                    "skills": ["LLM Platforms", "Machine Learning"],
                }
            ],
            "projects": [],
            "certifications": [],
            "languages": [],
            "additionalSections": [],
            "sectionOrder": [
                "summary",
                "skills",
                "experience",
                "education",
            ],
        }
    )


def seed_generation_inputs(
    sessions: sessionmaker[Session],
) -> None:
    master = source_resume()
    with sessions() as db:
        db.add(
            ResumeMasterRecord(
                id=MASTER_ID,
                name="Main resume",
                language="English",
                current_version=1,
            )
        )
        db.add(
            ResumeMasterVersionRecord(
                id=MASTER_VERSION_ID,
                resume_master_id=MASTER_ID,
                version=1,
                schema_version="1.0",
                data=master.model_dump(by_alias=True, exclude_none=True),
                content_sha256="d" * 64,
            )
        )
        db.add(
            StoredJobRecord(
                id=JOB_ID,
                data={
                    "id": JOB_ID,
                    "title": "Principal AI Architect",
                    "company": "Target AG",
                    "description": "Lead the enterprise AI platform.",
                },
                status="active",
            )
        )
        db.commit()


def generated_outcome(
    *,
    master_resume: MasterResume,
    target_job_id: str,
) -> ImaginatorOutcome:
    draft = generated_draft()
    final_resume, claim_ledger = assemble_imaginator_resume(
        generation_id=GENERATION_ID,
        draft=draft,
        master_resume=master_resume,
        target_job_id=target_job_id,
        target_language="English",
    )
    _prompt, audit_fingerprint, audited_claim_count = (
        build_imaginator_protected_facts_audit_prompt(
            draft=draft,
            master_resume=master_resume,
        )
    )
    protected_facts_audit = ImaginatorProtectedFactsAuditAttestation(
        passed=True,
        audited_claim_count=audited_claim_count,
        prompt_version="imaginator-protected-facts-audit-v1",
        result=ImaginatorProtectedFactsAudit(
            input_fingerprint=audit_fingerprint,
            verdict="pass",
            safe_paths=[
                claim["path"]
                for claim in imaginator_auditable_claims(draft)
            ],
            violations=[],
        ),
        metrics=ImaginatorResumeMetrics(
            latency_ms=25,
            input_tokens=30,
            output_tokens=20,
            total_tokens=50,
            token_count_source="provider",
        ),
        model="gpt-5.6-terra",
        backend="openai_api",
        provider_session_id="response-imaginator-audit-api",
    )
    return ImaginatorOutcome(
        generation_id=GENERATION_ID,
        draft=draft,
        final_resume=final_resume,
        claim_ledger=claim_ledger,
        result=AIResult(
            text="",
            structured_data=draft.model_dump(
                by_alias=True,
                exclude_none=True,
            ),
            model="gpt-5.6-terra",
            backend="openai_api",
            usage=AIUsage(
                input_tokens=100,
                output_tokens=200,
                total_tokens=300,
                source="provider",
            ),
            latency_ms=123,
            session_id="response-imaginator-api",
        ),
        protected_facts_audit=protected_facts_audit,
        vacancy_hash="e" * 64,
        input_fingerprint="f" * 64,
    )


def test_imaginator_post_persists_and_renders_owner_scoped_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)
    calls: list[tuple[str, str, str]] = []

    def fake_generate(**kwargs) -> ImaginatorOutcome:
        calls.append(
            (
                kwargs["master_resume"].id,
                kwargs["target_job_id"],
                kwargs["revision_instruction"],
            )
        )
        return generated_outcome(
            master_resume=kwargs["master_resume"],
            target_job_id=kwargs["target_job_id"],
        )

    monkeypatch.setattr(
        resume_tailoring_api,
        "generate_imaginator_resume_with_settings",
        fake_generate,
    )
    rendered: list[str] = []

    def fake_render(
        final_resume_json: dict[str, object],
        *,
        template_id: str,
    ) -> bytes:
        rendered.append(template_id)
        assert final_resume_json["targetJobId"] == JOB_ID
        return b"%PDF-1.7\nimaginator"

    monkeypatch.setattr(
        resume_tailoring_api,
        "render_final_resume_pdf",
        fake_render,
    )

    client = TestClient(app)
    generated = client.post(
        "/resume-tailoring/imaginator",
        json={
            "masterResumeId": MASTER_ID,
            "targetJobId": JOB_ID,
            "generationMode": "imaginator",
            "targetLanguage": "English",
            "revisionInstruction": "Emphasize AI leadership.",
        },
    )

    assert generated.status_code == 200
    body = generated.json()
    assert body["id"] == GENERATION_ID
    assert body["generationMode"] == "imaginator"
    assert body["finalResume"]["experiences"][0]["company"] == "Acme AG"
    assert body["finalResume"]["education"][0]["institution"] == "ETH Zürich"
    assert body["metrics"]["totalTokens"] == 350
    assert body["metrics"]["latencyMs"] == 148
    assert body["protectedFactsAudit"]["passed"] is True
    assert (
        body["protectedFactsAudit"]["auditedClaimCount"]
        == len(body["protectedFactsAudit"]["result"]["safePaths"])
    )
    assert calls == [
        (
            MASTER_ID,
            JOB_ID,
            "Emphasize AI leadership.",
        )
    ]

    pdf = client.get(
        f"/resume-tailoring/imaginator/{GENERATION_ID}/pdf",
        params={"templateId": "classic_single"},
    )
    assert pdf.status_code == 200
    assert pdf.content == b"%PDF-1.7\nimaginator"
    document_id = pdf.headers["x-rufina-document-id"]
    cached_pdf = client.get(
        f"/resume-tailoring/imaginator/{GENERATION_ID}/pdf",
        params={"templateId": "classic_single"},
    )
    assert cached_pdf.status_code == 200
    assert rendered == ["classic_single"]

    docx = client.get(
        f"/resume-tailoring/imaginator/{GENERATION_ID}/docx",
        params={"templateId": "classic_single"},
    )
    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")

    detail = client.get(f"/documents/{document_id}")
    assert detail.status_code == 200
    artifact = detail.json()["versions"][0]["artifact"]
    assert artifact["sourceImaginatorResumeId"] == GENERATION_ID
    assert artifact["sourceAtsFinalReviewId"] is None
    assert artifact["stageResults"]["generationMode"] == "imaginator"
    assert artifact["stageResults"]["protectedFactsAudit"]["passed"] is True
    assert artifact["provenance"]["syntheticClaimCount"] > 0
    assert artifact["provenance"]["protectedFactsAudit"]["passed"] is True

    assert client.get(
        f"/resume-tailoring/imaginator/{GENERATION_ID}/pdf",
        headers={"X-Rufina-Owner-Id": "other-owner"},
    ).status_code == 404
    assert client.get(
        f"/resume-tailoring/imaginator/{GENERATION_ID}/docx",
        headers={"X-Rufina-Owner-Id": "other-owner"},
    ).status_code == 404

    with api_sessions() as db:
        record = db.get(ImaginatorResumeRecord, GENERATION_ID)
        stored_file = db.scalar(
            select(DocumentFileRecord).where(
                DocumentFileRecord.document_id == document_id
            )
        )
        assert record is not None
        assert record.resume_master_version_id == MASTER_VERSION_ID
        assert record.protected_facts_audit["passed"] is True
        assert stored_file is not None
        assert stored_file.source_imaginator_resume_id == GENERATION_ID
        assert stored_file.source_ats_final_review_id is None


def test_imaginator_maps_shared_tailoring_validation_errors_to_422(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)

    def reject_generation(**_kwargs):
        raise ResumeTailoringError(
            "Vacancy context is invalid",
            code="invalid_input",
        )

    monkeypatch.setattr(
        resume_tailoring_api,
        "generate_imaginator_resume_with_settings",
        reject_generation,
    )
    response = TestClient(app).post(
        "/resume-tailoring/imaginator",
        json={
            "masterResumeId": MASTER_ID,
            "targetJobId": JOB_ID,
            "generationMode": "imaginator",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Vacancy context is invalid"
    with api_sessions() as db:
        assert db.scalar(select(ImaginatorResumeRecord)) is None


def test_imaginator_maps_protected_fact_rejection_to_422(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)

    def reject_generation(**_kwargs):
        raise ResumeImaginatorError(
            "Imaginator generated content that conflicts with protected source facts",
            code="protected_fact_violation",
        )

    monkeypatch.setattr(
        resume_tailoring_api,
        "generate_imaginator_resume_with_settings",
        reject_generation,
    )
    response = TestClient(app).post(
        "/resume-tailoring/imaginator",
        json={
            "masterResumeId": MASTER_ID,
            "targetJobId": JOB_ID,
            "generationMode": "imaginator",
        },
    )

    assert response.status_code == 422
    assert "protected source facts" in response.json()["detail"]
    with api_sessions() as db:
        assert db.scalar(select(ImaginatorResumeRecord)) is None


def test_persisted_imaginator_records_are_immutable(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)
    monkeypatch.setattr(
        resume_tailoring_api,
        "generate_imaginator_resume_with_settings",
        lambda **kwargs: generated_outcome(
            master_resume=kwargs["master_resume"],
            target_job_id=kwargs["target_job_id"],
        ),
    )
    assert TestClient(app).post(
        "/resume-tailoring/imaginator",
        json={
            "masterResumeId": MASTER_ID,
            "targetJobId": JOB_ID,
        },
    ).status_code == 200

    with api_sessions() as db:
        record = db.get(ImaginatorResumeRecord, GENERATION_ID)
        assert record is not None
        record.created_at = datetime.now(UTC)
        with pytest.raises(
            ValueError,
            match="Imaginator resumes are immutable",
        ):
            db.commit()


def test_persistence_rechecks_locked_facts_against_master_version(
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)
    outcome = generated_outcome(
        master_resume=source_resume(),
        target_job_id=JOB_ID,
    )
    changed_experience = outcome.final_resume.experiences[0].model_copy(
        update={"company": "Invented Holdings SA"},
    )
    tampered = replace(
        outcome,
        final_resume=outcome.final_resume.model_copy(
            update={"experiences": [changed_experience]},
        ),
    )

    with api_sessions() as db:
        master_version = db.get(
            ResumeMasterVersionRecord,
            MASTER_VERSION_ID,
        )
        assert master_version is not None
        with pytest.raises(
            ResumeImaginatorError,
            match="locked employer binding",
        ):
            persist_imaginator_resume(
                db,
                master_version=master_version,
                application_id=None,
                outcome=tampered,
            )
        assert db.get(ImaginatorResumeRecord, GENERATION_ID) is None


def test_persistence_rejects_render_content_not_present_in_audited_draft(
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)
    outcome = generated_outcome(
        master_resume=source_resume(),
        target_job_id=JOB_ID,
    )
    assert outcome.final_resume.summary is not None
    tampered_summary = outcome.final_resume.summary.model_copy(
        update={
            "text": "Harvard MBA who served as CTO of Google.",
        },
    )
    tampered = replace(
        outcome,
        final_resume=outcome.final_resume.model_copy(
            update={"summary": tampered_summary},
        ),
    )

    with api_sessions() as db:
        master_version = db.get(
            ResumeMasterVersionRecord,
            MASTER_VERSION_ID,
        )
        assert master_version is not None
        with pytest.raises(
            ResumeImaginatorError,
            match="differs from the audited draft",
        ) as error:
            persist_imaginator_resume(
                db,
                master_version=master_version,
                application_id=None,
                outcome=tampered,
            )
        assert error.value.code == "immutable_violation"
        assert db.get(ImaginatorResumeRecord, GENERATION_ID) is None


def test_render_rejects_stored_content_not_present_in_audited_draft(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)
    monkeypatch.setattr(
        resume_tailoring_api,
        "generate_imaginator_resume_with_settings",
        lambda **kwargs: generated_outcome(
            master_resume=kwargs["master_resume"],
            target_job_id=kwargs["target_job_id"],
        ),
    )
    client = TestClient(app)
    assert client.post(
        "/resume-tailoring/imaginator",
        json={
            "masterResumeId": MASTER_ID,
            "targetJobId": JOB_ID,
        },
    ).status_code == 200

    with api_sessions() as db:
        record = db.get(ImaginatorResumeRecord, GENERATION_ID)
        assert record is not None
        tampered_render_input = deepcopy(record.render_input)
        tampered_render_input["summary"]["text"] = (
            "Harvard MBA who served as CTO of Google."
        )
        db.execute(
            update(ImaginatorResumeRecord)
            .where(ImaginatorResumeRecord.id == GENERATION_ID)
            .values(render_input=tampered_render_input)
        )
        db.commit()

    response = client.get(
        f"/resume-tailoring/imaginator/{GENERATION_ID}/pdf",
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Stored Imaginator resume violates locked source facts"
    )


def test_render_accepts_a_supported_historical_audit_version(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    seed_generation_inputs(api_sessions)
    monkeypatch.setattr(
        resume_tailoring_api,
        "generate_imaginator_resume_with_settings",
        lambda **kwargs: generated_outcome(
            master_resume=kwargs["master_resume"],
            target_job_id=kwargs["target_job_id"],
        ),
    )
    client = TestClient(app)
    assert client.post(
        "/resume-tailoring/imaginator",
        json={
            "masterResumeId": MASTER_ID,
            "targetJobId": JOB_ID,
        },
    ).status_code == 200

    monkeypatch.setattr(
        resume_imaginator_service,
        "IMAGINATOR_AUDIT_PROMPT_VERSION",
        "imaginator-protected-facts-audit-v2",
    )

    def reject_current_context(**_kwargs):
        raise AssertionError(
            "historical rerender must not use the current audit collector"
        )

    monkeypatch.setattr(
        resume_imaginator_service,
        "imaginator_protected_facts_audit_context",
        reject_current_context,
    )
    monkeypatch.setattr(
        resume_tailoring_api,
        "render_final_resume_pdf",
        lambda _resume, *, template_id: b"%PDF-1.7\nhistorical",
    )

    response = client.get(
        f"/resume-tailoring/imaginator/{GENERATION_ID}/pdf",
    )
    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\nhistorical"
