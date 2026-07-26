from collections.abc import Generator
from copy import deepcopy
from dataclasses import replace
from inspect import signature
from io import BytesIO
import json

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import resume_tailoring as resume_tailoring_api
from app.core.database import Base, get_db
from app.core.identity import current_owner_id
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.documents import (
    DocumentFileRecord,
    DocumentGenerationProvenanceRecord,
    DocumentRecord,
)
from app.models.resume import (
    AtsFinalReview,
    AtsFinalReviewRecord,
    ExperienceRewrite,
    ExperienceRewriteRecord,
    FinalResume,
    MasterResume,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    ResumeTailoringRunRecord,
    ResumeTailoringStageRecord,
    SeniorRecruiterAnalysis,
    SeniorRecruiterAnalysisRecord,
)
from app.models.resume_templates import ResumeTemplateDefinitionRecord
from app.services.ai_backend import AIRequest, AIResult, AIUsage
from app.services.ai_privacy import require_current_ai_consent
from app.services.document_export import render_final_resume_json
from app.services.resume_pdf_renderer import (
    ResumeTemplateNotFoundError,
    ResumePdfRenderError,
    chromium_pdf_from_html,
    load_template_bundle,
    render_final_resume_html,
    render_final_resume_pdf,
    render_resolved_final_resume_html,
    render_resolved_final_resume_pdf,
    resolve_resume_template,
    validate_rendered_pdf,
)
from app.services.resume_pdf_validation import (
    PDF_TEMPLATE_VERSION_METADATA_KEY,
    ResumePdfValidationError,
    validate_expected_text,
    validate_reading_order,
)
from app.services.resume_tailoring import (
    ATS_FINAL_REVIEW_PROMPT_VERSION,
    AtsFinalReviewOutcome,
    ResumeTailoringError,
    build_resume_after_stage_two,
    final_resume_id,
    review_final_resume_for_ats,
)


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
    try:
        yield testing_session_local
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def master_resume_payload(master_resume_id: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": master_resume_id,
        "language": "English",
        "basics": {
            "fullName": "Ada Lovelace",
            "headline": "Platform Engineer",
            "email": "ada@example.com",
            "location": "Zurich",
        },
        "summary": {
            "text": "Platform engineer building services.",
            "evidenceIds": ["profile:summary"],
        },
        "experiences": [
            {
                "id": "experience:acme",
                "company": "Acme AG",
                "title": "Platform Engineer",
                "location": "Zurich",
                "startDate": "2022-01",
                "isCurrent": True,
                "bullets": [
                    {
                        "id": "bullet:acme:scale",
                        "text": (
                            "Improved deployment throughput by 40% using "
                            "Kubernetes automation."
                        ),
                        "evidenceIds": ["profile:acme:scale"],
                    }
                ],
            }
        ],
        "skills": [
            {
                "id": "skill:python",
                "name": "Python",
                "evidenceIds": ["profile:skill:python"],
            }
        ],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [
            {
                "id": "profile:summary",
                "type": "profile",
                "text": "Platform engineer building reliable services.",
            },
            {
                "id": "profile:acme:scale",
                "type": "profile",
                "text": (
                    "Improved deployment throughput by 40% using Kubernetes "
                    "automation."
                ),
                "claimType": "achievement",
                "experienceId": "experience:acme",
            },
            {
                "id": "profile:skill:python",
                "type": "profile",
                "text": "Python",
            },
        ],
        "sectionOrder": ["summary", "experience", "skills"],
    }


def recruiter_analysis_payload() -> dict[str, object]:
    return {
        "missingKeywords": [
            {
                "keyword": "Kubernetes",
                "whyItMatters": "Required for the platform.",
                "evidenceStatus": "verified",
                "evidenceIds": ["profile:acme:scale"],
            },
            {
                "keyword": "Python",
                "whyItMatters": "Required for automation.",
                "evidenceStatus": "transferable",
                "evidenceIds": ["profile:skill:python"],
            },
            {
                "keyword": "Terraform",
                "whyItMatters": "Required for infrastructure.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
            {
                "keyword": "SRE",
                "whyItMatters": "Relevant to reliability.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
            {
                "keyword": "Incident response",
                "whyItMatters": "Relevant to operations.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
        ],
        "redFlags": [
            {
                "flag": "Generic summary",
                "whyItIsVisible": "The value proposition is unclear.",
                "fix": "Make the summary specific and evidence-backed.",
            },
            {
                "flag": "Impact is buried",
                "whyItIsVisible": "The outcome is hard to scan.",
                "fix": "Lead with measured impact.",
            },
            {
                "flag": "Skills lack context",
                "whyItIsVisible": "The skills list is terse.",
                "fix": "Keep only relevant verified skills.",
            },
        ],
    }


def experience_rewrite_payload(master_resume_id: str) -> dict[str, object]:
    return {
        "masterResumeId": master_resume_id,
        "targetJobId": "job-platform",
        "experiences": [
            {
                "id": "rewritten-experience:0001",
                "masterExperienceId": "experience:acme",
                "company": "Acme AG",
                "title": "Platform Engineer",
                "location": "Zurich",
                "period": "2022-01 — Present",
                "bullets": [
                    {
                        "id": "rewritten-bullet:0001:0001",
                        "text": (
                            "Increased deployment throughput by 40% by "
                            "automating releases with Kubernetes."
                        ),
                        "evidenceIds": ["profile:acme:scale"],
                    }
                ],
            }
        ],
        "links": [
            {
                "originalExperienceId": "experience:acme",
                "rewrittenExperienceId": "rewritten-experience:0001",
                "bulletLinks": [
                    {
                        "originalBulletIds": ["bullet:acme:scale"],
                        "rewrittenBulletId": "rewritten-bullet:0001:0001",
                    }
                ],
            }
        ],
    }


def final_review_payload(master_resume_id: str) -> dict[str, object]:
    master_resume = MasterResume.model_validate(
        master_resume_payload(master_resume_id)
    )
    stage_two = build_resume_after_stage_two(
        master_resume=master_resume,
        target_job_id="job-platform",
        experience_rewrite=ExperienceRewrite.model_validate(
            experience_rewrite_payload(master_resume_id)
        ),
    )
    final_resume = stage_two.model_dump(by_alias=True, exclude_none=True)
    final_resume["id"] = final_resume_id(stage_two)
    final_resume["summary"]["text"] = (
        "Platform engineer who increased Kubernetes deployment throughput by 40%."
    )
    final_resume["summary"]["evidenceIds"] = [
        "profile:summary",
        "profile:acme:scale",
    ]
    return {
        "atsScan": {
            "skippedSections": [
                {
                    "section": "summary",
                    "reason": "The original summary is generic.",
                    "action": "Lead with verified platform impact.",
                }
            ]
        },
        "finalResume": final_resume,
    }


def complete_final_resume_payload(master_resume_id: str) -> dict[str, object]:
    final_resume = final_review_payload(master_resume_id)["finalResume"]
    final_resume["basics"].update(
        {
            "phone": "+41 44 000 00 00",
            "linkedin": "https://linkedin.example/ada",
            "github": "https://github.example/ada",
            "portfolio": "https://ada.example",
        }
    )
    final_resume["skills"][0]["category"] = "Engineering"
    final_resume["education"] = [
        {
            "id": "education:analytical-engine",
            "institution": "University of London",
            "credential": "BSc",
            "fieldOfStudy": "Mathematics",
            "location": "London",
            "startDate": "1833",
            "endDate": "1835",
            "details": [
                {
                    "id": "bullet:education:research",
                    "text": "Studied symbolic computation.",
                    "evidenceIds": ["profile:summary"],
                }
            ],
        }
    ]
    final_resume["projects"] = [
        {
            "id": "project:analytical-engine",
            "name": "Analytical Engine Notes",
            "role": "Author",
            "url": "https://ada.example/analytical-engine",
            "bullets": [
                {
                    "id": "bullet:project:algorithm",
                    "text": "Published an algorithm for Bernoulli numbers.",
                    "evidenceIds": ["profile:summary"],
                }
            ],
        }
    ]
    final_resume["certifications"] = [
        {
            "id": "certification:cloud",
            "name": "Cloud Architecture",
            "issuer": "Engineering Guild",
            "issuedOn": "2024-01",
            "expiresOn": "2027-01",
            "evidenceIds": ["profile:skill:python"],
        }
    ]
    final_resume["languages"] = [
        {
            "id": "language:english",
            "name": "English",
            "proficiency": "Native",
            "evidenceIds": ["profile:summary"],
        }
    ]
    final_resume["additionalSections"] = [
        {
            "id": "additional:community",
            "title": "Community",
            "items": [
                {
                    "id": "bullet:additional:mentoring",
                    "text": "Mentors early-career engineers.",
                    "evidenceIds": ["profile:summary"],
                }
            ],
        }
    ]
    final_resume["sectionOrder"] = [
        "summary",
        "experience",
        "skills",
        "education",
        "projects",
        "certifications",
        "languages",
        "additional",
    ]
    return final_resume


def ai_result(payload: dict[str, object]) -> AIResult:
    return AIResult(
        text="",
        structured_data=payload,
        model="gpt-5.6-terra",
        backend="openai_api",
        usage=AIUsage(
            input_tokens=240,
            output_tokens=180,
            total_tokens=420,
            source="provider",
        ),
        latency_ms=777,
        session_id="response-ats-final-1",
    )


def test_ats_final_review_uses_stage_two_resume_and_returns_full_resume() -> None:
    requests: list[AIRequest] = []
    master_resume_id = "master-resume"

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            return ai_result(final_review_payload(master_resume_id))

    outcome = review_final_resume_for_ats(
        master_resume=MasterResume.model_validate(
            master_resume_payload(master_resume_id)
        ),
        target_job_id="job-platform",
        recruiter_analysis=SeniorRecruiterAnalysis.model_validate(
            recruiter_analysis_payload()
        ),
        experience_rewrite=ExperienceRewrite.model_validate(
            experience_rewrite_payload(master_resume_id)
        ),
        backend=FakeBackend(),
        model="gpt-5.6-terra",
        agent_id="rufina-assistant",
        thinking="high",
        timeout_seconds=120,
    )

    assert len(requests) == 1
    assert requests[0].structured is True
    assert requests[0].response_model is AtsFinalReview
    assert "MANDATORY RESUME TAILORING REQUEST 3" in requests[0].prompt
    assert "reading 200 resumes in one sitting" in requests[0].prompt
    assert "resumeAfterStageTwo" in requests[0].prompt
    assert "sole renderer input" in requests[0].prompt
    schema_text = (
        requests[0]
        .prompt.split("ATS_FINAL_REVIEW_JSON_SCHEMA:\n", 1)[1]
        .split("\nATS_REVIEW_CONTEXT_JSON:\n", 1)[0]
    )
    prompt_schema = json.loads(schema_text)
    assert set(prompt_schema["required"]) == {"atsScan", "finalResume"}
    assert outcome.review.ats_scan.skipped_sections[0].section == "summary"
    assert outcome.review.final_resume.experiences[0].bullets[0].text.startswith(
        "Increased deployment throughput by 40%"
    )
    assert outcome.review.final_resume.skills[0].name == "Python"


def test_ats_final_review_rejects_changes_not_reported_by_scan() -> None:
    master_resume_id = "master-resume"
    payload = final_review_payload(master_resume_id)
    payload["atsScan"]["skippedSections"] = []

    class FakeBackend:
        name = "openai_api"

        def generate(self, _request: AIRequest) -> AIResult:
            return ai_result(payload)

    with pytest.raises(
        ResumeTailoringError,
        match="scan and rewritten final resume sections do not match",
    ):
        review_final_resume_for_ats(
            master_resume=MasterResume.model_validate(
                master_resume_payload(master_resume_id)
            ),
            target_job_id="job-platform",
            recruiter_analysis=SeniorRecruiterAnalysis.model_validate(
                recruiter_analysis_payload()
            ),
            experience_rewrite=ExperienceRewrite.model_validate(
                experience_rewrite_payload(master_resume_id)
            ),
            backend=FakeBackend(),
            model="gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="high",
            timeout_seconds=120,
        )


def test_ats_final_review_endpoint_loads_stage_two_and_persists_render_input(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    master_resume_id = "a" * 32
    master_version_id = "b" * 32
    analysis_id = "c" * 32
    rewrite_id = "d" * 32
    master_resume = MasterResume.model_validate(
        master_resume_payload(master_resume_id)
    )
    rewrite_payload = experience_rewrite_payload(master_resume_id)
    with api_sessions() as db:
        db.add(
            ResumeMasterRecord(
                id=master_resume_id,
                name="Main resume",
                language="English",
                current_version=1,
            )
        )
        db.add(
            ResumeMasterVersionRecord(
                id=master_version_id,
                resume_master_id=master_resume_id,
                version=1,
                schema_version="1.0",
                data=master_resume.model_dump(by_alias=True, exclude_none=True),
                content_sha256="e" * 64,
            )
        )
        db.add(
            SeniorRecruiterAnalysisRecord(
                id=analysis_id,
                resume_master_id=master_resume_id,
                resume_master_version_id=master_version_id,
                target_job_id="job-platform",
                vacancy_hash="f" * 64,
                prompt_version="senior-recruiter-analysis-v1",
                result=recruiter_analysis_payload(),
                model="gpt-5.6-terra",
                backend="openai_api",
                provider_session_id="response-recruiter-1",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                token_count_source="provider",
                latency_ms=321,
            )
        )
        db.add(
            ExperienceRewriteRecord(
                id=rewrite_id,
                senior_recruiter_analysis_id=analysis_id,
                resume_master_id=master_resume_id,
                resume_master_version_id=master_version_id,
                target_job_id="job-platform",
                prompt_version="xyz-experience-rewrite-v1",
                original_experiences=[
                    item.model_dump(by_alias=True, exclude_none=True)
                    for item in master_resume.experiences
                ],
                result=rewrite_payload,
                links=rewrite_payload["links"],
                model="gpt-5.6-terra",
                backend="openai_api",
                provider_session_id="response-rewrite-1",
                input_tokens=180,
                output_tokens=120,
                total_tokens=300,
                token_count_source="provider",
                latency_ms=654,
            )
        )
        db.commit()

    review = AtsFinalReview.model_validate(
        final_review_payload(master_resume_id)
    )
    calls: list[tuple[str, str, str]] = []

    class FakeFacade:
        def review_final_resume_for_ats(
            self,
            *,
            master_resume: MasterResume,
            target_job_id: str,
            recruiter_analysis: SeniorRecruiterAnalysis,
            experience_rewrite: ExperienceRewrite,
        ) -> AtsFinalReviewOutcome:
            calls.append(
                (
                    master_resume.id,
                    target_job_id,
                    experience_rewrite.experiences[0].bullets[0].text,
                )
            )
            return AtsFinalReviewOutcome(
                review=review,
                result=ai_result(final_review_payload(master_resume_id)),
            )

    monkeypatch.setattr(
        resume_tailoring_api,
        "create_resume_tailoring_ai_facade",
        lambda _settings: FakeFacade(),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True
    )

    client = TestClient(app)
    response = client.post(
        "/resume-tailoring/ats-final-review",
        json={"experienceRewriteId": rewrite_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert calls[0][:2] == (master_resume_id, "job-platform")
    assert calls[0][2].startswith("Increased deployment throughput by 40%")
    assert body["experienceRewriteId"] == rewrite_id
    assert body["atsScan"]["skippedSections"][0]["section"] == "summary"
    assert body["finalResume"] == final_review_payload(master_resume_id)[
        "finalResume"
    ]
    assert body["metrics"]["totalTokens"] == 420
    assert body["promptVersion"] == ATS_FINAL_REVIEW_PROMPT_VERSION
    assert body["attempt"] == 1
    assert isinstance(body["runId"], str)

    with api_sessions() as db:
        records = db.scalars(select(AtsFinalReviewRecord)).all()
        assert len(records) == 1
        record = records[0]
        assert record.experience_rewrite_id == rewrite_id
        assert record.result == final_review_payload(master_resume_id)
        assert record.render_input == record.result["finalResume"]
        run = db.get(ResumeTailoringRunRecord, body["runId"])
        stages = db.scalars(
            select(ResumeTailoringStageRecord).order_by(
                ResumeTailoringStageRecord.stage_number
            )
        ).all()
        assert run is not None
        assert run.status == "succeeded"
        assert run.current_stage == 3
        assert len(stages) == 3
        assert all(stage.status == "succeeded" for stage in stages)
        assert stages[2].structured_output == final_review_payload(
            master_resume_id
        )
        record.render_input = {}
        with pytest.raises(ValueError, match="ATS final reviews are immutable"):
            db.commit()

    rendered_templates: list[str] = []

    def fake_render_pdf(
        final_resume_json: dict[str, object],
        *,
        template_id: str,
    ) -> bytes:
        assert final_resume_json == body["finalResume"]
        rendered_templates.append(template_id)
        return b"%PDF-1.7\nserver-rendered"

    monkeypatch.setattr(
        resume_tailoring_api,
        "render_final_resume_pdf",
        fake_render_pdf,
    )
    downloaded = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        params={"templateId": "modern_two_column"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.headers["access-control-allow-origin"] == (
        "http://localhost:3000"
    )
    exposed_headers = {
        header.strip().casefold()
        for header in downloaded.headers["access-control-expose-headers"].split(
            ","
        )
    }
    assert "x-rufina-document-id" in exposed_headers
    assert downloaded.headers["content-disposition"] == (
        'attachment; filename="Ada-Lovelace-resume.pdf"'
    )
    assert downloaded.content == b"%PDF-1.7\nserver-rendered"
    document_id = downloaded.headers["x-rufina-document-id"]
    assert downloaded.headers["x-rufina-template-id"] == (
        "modern_two_column"
    )
    assert downloaded.headers["x-rufina-template-version"] == "1.0.1"
    assert rendered_templates == ["modern_two_column"]
    cached_download = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        params={"templateId": "modern_two_column"},
    )
    artifact_download = client.get(
        f"/documents/{document_id}/download"
    )
    listed_documents = client.get(
        "/documents",
        params={"jobId": "job-platform"},
    )
    document_detail = client.get(f"/documents/{document_id}")
    assert cached_download.status_code == 200
    assert cached_download.headers["x-rufina-document-id"] == document_id
    assert rendered_templates == ["modern_two_column"]
    assert artifact_download.status_code == 200
    assert artifact_download.content == downloaded.content
    assert artifact_download.headers["content-type"] == "application/pdf"
    assert artifact_download.headers["content-disposition"] == (
        'attachment; filename="Ada-Lovelace-resume.pdf"; '
        "filename*=UTF-8''Ada-Lovelace-resume.pdf"
    )
    assert listed_documents.status_code == 200
    assert listed_documents.json()[0]["id"] == document_id
    assert document_detail.status_code == 200
    stored_document = document_detail.json()
    assert stored_document["id"] == document_id
    assert stored_document["type"] == "tailored_resume"
    assert stored_document["versions"][0]["hasRenderedDocx"] is False
    assert stored_document["versions"][0]["hasRenderedArtifact"] is True
    artifact_payload = stored_document["versions"][0]["artifact"]
    assert artifact_payload["contentType"] == "application/pdf"
    assert artifact_payload["fileName"] == "Ada-Lovelace-resume.pdf"
    assert artifact_payload["templateId"] == "modern_two_column"
    assert artifact_payload["templateVersion"] == "1.0.1"
    assert artifact_payload["sourceAtsFinalReviewId"] == body["id"]
    assert artifact_payload["finalResumeJson"] == body["finalResume"]
    assert set(artifact_payload["stageResults"]) == {
        "schemaVersion",
        "seniorRecruiterAnalysis",
        "experienceRewrite",
        "atsFinalReview",
    }
    assert artifact_payload["provenance"]["atsFinalReviewId"] == body["id"]
    assert artifact_payload["provenance"]["templateId"] == (
        "modern_two_column"
    )
    with api_sessions() as db:
        document = db.get(DocumentRecord, document_id)
        artifact = db.scalar(
            select(DocumentFileRecord).where(
                DocumentFileRecord.document_id == document_id
            )
        )
        provenance = db.get(
            DocumentGenerationProvenanceRecord,
            document_id,
        )
        assert document is not None
        assert artifact is not None
        assert provenance is not None
        assert json.loads(document.versions[0].content) == body["finalResume"]
        assert artifact.content_type == "application/pdf"
        assert artifact.renderer_template_id == "modern_two_column"
        assert artifact.renderer_template_version == "1.0.1"
        assert artifact.renderer_design_sha256 is not None
        assert len(artifact.renderer_design_sha256) == 64
        assert artifact.final_resume_json == body["finalResume"]
        assert provenance.input_versions["atsFinalReviewId"] == body["id"]

    custom_template = client.post(
        "/resume-templates",
        json={
            "name": "Claret two column",
            "baseTemplateId": "modern_two_column",
            "designJson": {
                "accentColor": "#8A1538",
                "fontFamily": "Inter",
                "fontScale": 1,
                "density": "compact",
                "pageMargins": {
                    "top": 12,
                    "right": 12,
                    "bottom": 12,
                    "left": 12,
                },
                "headingStyle": "accent-rule",
                "skillsStyle": "pills",
                "sidebarWidth": 32,
                "sidebarSections": ["skills", "languages"],
            },
        },
    )
    assert custom_template.status_code == 201
    custom_template_id = custom_template.json()["id"]
    custom_renders: list[tuple[str, str]] = []

    def fake_render_resolved_pdf(
        final_resume_json: dict[str, object],
        *,
        template,
    ) -> bytes:
        assert final_resume_json == body["finalResume"]
        custom_renders.append((template.id, template.version))
        assert template.html_template == load_template_bundle(
            "modern_two_column"
        ).html_template
        assert "--resume-accent: #8A1538;" in template.stylesheet or (
            "--resume-accent: #243B53;" in template.stylesheet
        )
        return f"%PDF-1.7\\ncustom-v{template.version}".encode()

    monkeypatch.setattr(
        resume_tailoring_api,
        "render_resolved_final_resume_pdf",
        fake_render_resolved_pdf,
    )
    custom_download_v1 = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        params={"templateId": custom_template_id},
    )
    custom_cached_v1 = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        params={"templateId": custom_template_id},
    )
    assert custom_download_v1.status_code == 200
    assert custom_cached_v1.headers["x-rufina-document-id"] == (
        custom_download_v1.headers["x-rufina-document-id"]
    )
    assert custom_download_v1.headers["x-rufina-template-version"] == "1"
    assert custom_renders == [(custom_template_id, "1")]

    updated_custom_template = client.patch(
        f"/resume-templates/{custom_template_id}",
        json={
            "designJson": {
                **custom_template.json()["designJson"],
                "accentColor": "#243B53",
            }
        },
    )
    assert updated_custom_template.status_code == 200
    assert updated_custom_template.json()["version"] == 2

    custom_download_v2 = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        params={"templateId": custom_template_id},
    )
    assert custom_download_v2.status_code == 200
    assert custom_download_v2.headers["x-rufina-template-version"] == "2"
    assert custom_download_v2.headers["x-rufina-document-id"] != (
        custom_download_v1.headers["x-rufina-document-id"]
    )
    assert custom_renders == [
        (custom_template_id, "1"),
        (custom_template_id, "2"),
    ]
    historical_download = client.get(
        "/documents/"
        f"{custom_download_v1.headers['x-rufina-document-id']}/download"
    )
    assert historical_download.status_code == 200
    assert historical_download.content == custom_download_v1.content

    with api_sessions() as db:
        custom_artifacts = db.scalars(
            select(DocumentFileRecord)
            .where(
                DocumentFileRecord.renderer_template_id
                == custom_template_id
            )
            .order_by(DocumentFileRecord.renderer_template_version)
        ).all()
        assert [
            artifact.renderer_template_version
            for artifact in custom_artifacts
        ] == ["1", "2"]
        assert len(
            {
                artifact.renderer_design_sha256
                for artifact in custom_artifacts
            }
        ) == 2
        assert all(
            artifact.provenance["customTemplateId"] == custom_template_id
            for artifact in custom_artifacts
            if artifact.provenance is not None
        )
    invalid_template = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        params={"templateId": "client_template"},
    )
    assert invalid_template.status_code == 404
    foreign_owner = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        headers={"X-Rufina-Owner-Id": "another-owner"},
    )
    assert foreign_owner.status_code == 404


def test_ats_final_review_requires_saved_stage_two(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    monkeypatch.setattr(
        resume_tailoring_api,
        "create_resume_tailoring_ai_facade",
        lambda _settings: pytest.fail("AI must not run without stage two"),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True
    )

    response = TestClient(app).post(
        "/resume-tailoring/ats-final-review",
        json={"experienceRewriteId": "missing-rewrite"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Experience rewrite not found"


def test_ats_final_review_request_cannot_override_saved_resume(
    api_sessions: sessionmaker[Session],
) -> None:
    response = TestClient(app).post(
        "/resume-tailoring/ats-final-review",
        json={
            "experienceRewriteId": "rewrite-id",
            "finalResume": {"id": "client-controlled"},
        },
    )

    assert response.status_code == 422


def test_final_resume_json_is_the_renderers_only_input() -> None:
    final_resume_json = final_review_payload("master-resume")["finalResume"]

    assert list(signature(render_final_resume_json).parameters) == [
        "final_resume_json"
    ]
    rendered = render_final_resume_json(final_resume_json)
    reader = PdfReader(BytesIO(rendered))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert rendered.startswith(b"%PDF-")
    assert "Platform engineer who increased Kubernetes" in text
    assert "Increased deployment throughput by 40%" in text
    assert "Python" in text
    assert "Platform engineer building services." not in text


@pytest.mark.parametrize(
    "template_id",
    [
        "classic_single",
        "modern_single",
        "modern_two_column",
        "swiss_classic",
        "swiss_local_german",
    ],
)
def test_pdf_template_manifests_are_valid_and_render_escaped_html(
    template_id: str,
) -> None:
    final_resume_json = complete_final_resume_payload("master-resume")
    final_resume_json["basics"]["fullName"] = "<b>Ada Lovelace</b>"
    final_resume_json["basics"]["linkedin"] = "javascript:alert(1)"

    html, bundle = render_final_resume_html(
        final_resume_json,
        template_id=template_id,
    )

    assert bundle.manifest.template_id == template_id
    assert bundle.manifest.renderer == "chromium"
    assert "&lt;b&gt;Ada Lovelace&lt;/b&gt;" in html
    assert "<b>Ada Lovelace</b>" not in html
    assert 'href="javascript:' not in html
    assert "<script" not in html.lower()
    assert load_template_bundle(template_id).manifest == bundle.manifest
    rendered = render_final_resume_pdf(
        final_resume_json,
        template_id=template_id,
    )
    assert rendered.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(rendered)).pages) >= 1
    report = validate_rendered_pdf(
        rendered,
        resume=FinalResume.model_validate(final_resume_json),
        bundle=bundle,
    )
    assert report.page_count == report.png_page_count
    assert report.expected_text_fragment_count > 0
    assert report.template_id == template_id
    assert report.template_version == bundle.manifest.template_version
    assert report.overflow_issue_count == 0


def test_swiss_local_german_uses_localized_single_line_header() -> None:
    final_resume_json = complete_final_resume_payload("master-resume")
    final_resume_json["language"] = "Deutsch"
    final_resume_json["basics"]["location"] = "Männedorf, Zürich, Schweiz"

    html, _bundle = render_final_resume_html(
        final_resume_json,
        template_id="swiss_local_german",
    )

    assert "Berufserfahrung" in html
    assert "Technische Kenntnisse" in html
    assert "Männedorf, Zürich, Schweiz" in html
    assert 'class="identity-meta"' not in html


def test_custom_template_resolver_only_uses_server_owned_markup(
    api_sessions: sessionmaker[Session],
) -> None:
    with api_sessions() as db:
        db.add(
            ResumeTemplateDefinitionRecord(
                id="custom-resolved-template",
                owner_id="local-owner",
                name="Safe custom template",
                base_template_id="modern_two_column",
                design_json={
                    "accentColor": "#8A1538",
                    "fontFamily": "Inter",
                    "fontScale": 1,
                    "density": "compact",
                    "pageMargins": {
                        "top": 12,
                        "right": 13,
                        "bottom": 14,
                        "left": 15,
                    },
                    "headingStyle": "accent-rule",
                    "skillsStyle": "pills",
                    "sidebarWidth": 32,
                    "sidebarSections": ["skills", "languages"],
                },
                version=3,
                content_sha256="a" * 64,
            )
        )
        db.commit()
        resolved = resolve_resume_template(db, "custom-resolved-template")

        assert resolved.id == "custom-resolved-template"
        assert resolved.version == "3"
        assert resolved.base_template_id == "modern_two_column"
        assert resolved.html_template == load_template_bundle(
            "modern_two_column"
        ).html_template
        assert "--resume-accent: #8A1538;" in resolved.stylesheet
        assert "--resume-font-scale: 1;" in resolved.stylesheet
        assert "--resume-sidebar-width: 32%;" in resolved.stylesheet
        assert "--resume-page-margin-left: 15mm;" in resolved.stylesheet
        assert len(resolved.design_sha256) == 64

        html, _bundle = render_resolved_final_resume_html(
            final_review_payload("master-resume")["finalResume"],
            template=resolved,
        )
        assert "--resume-accent: #8A1538;" in html
        assert "sidebar_sections" not in html
        rendered = render_resolved_final_resume_pdf(
            final_review_payload("master-resume")["finalResume"],
            template=resolved,
        )
        reader = PdfReader(BytesIO(rendered))
        assert reader.metadata["/ResumeTemplateId"] == resolved.id
        assert reader.metadata["/ResumeTemplateVersion"] == resolved.version

        tampered = replace(
            resolved,
            stylesheet=resolved.stylesheet + "\nbody { display: none; }",
        )
        with pytest.raises(
            ResumePdfRenderError,
            match="does not use its server-owned bundle",
        ):
            render_resolved_final_resume_html(
                final_review_payload("master-resume")["finalResume"],
                template=tampered,
            )

        owner_token = current_owner_id.set("another-owner")
        try:
            with pytest.raises(
                ResumeTemplateNotFoundError,
                match="Resume template not found",
            ):
                resolve_resume_template(db, "custom-resolved-template")
        finally:
            current_owner_id.reset(owner_token)


@pytest.mark.parametrize(
    "template_id",
    [
        "classic_single",
        "modern_single",
        "modern_two_column",
        "swiss_classic",
        "swiss_local_german",
    ],
)
def test_pdf_templates_group_skills_by_category(template_id: str) -> None:
    final_resume_json = final_review_payload("master-resume")["finalResume"]
    final_resume_json["skills"] = [
        {
            "id": "skill:python",
            "name": "Python",
            "category": "Languages",
            "evidenceIds": ["profile:skill:python"],
        },
        {
            "id": "skill:typescript",
            "name": "TypeScript",
            "category": "Languages",
            "evidenceIds": ["profile:skill:python"],
        },
        {
            "id": "skill:fastapi",
            "name": "FastAPI",
            "category": "Frameworks",
            "evidenceIds": ["profile:skill:python"],
        },
        {
            "id": "skill:react",
            "name": "React",
            "category": "Frameworks",
            "evidenceIds": ["profile:skill:python"],
        },
    ]

    html, _bundle = render_final_resume_html(
        final_resume_json,
        template_id=template_id,
    )

    assert html.count("<strong>Languages:</strong>") == 1
    assert html.count("<strong>Frameworks:</strong>") == 1
    assert html.index("Python") < html.index("TypeScript")
    assert html.index("FastAPI") < html.index("React")


def test_pdf_renderer_rejects_non_final_resume_fields() -> None:
    final_resume_json = final_review_payload("master-resume")["finalResume"]
    final_resume_json["html"] = "<h1>AI-controlled HTML</h1>"
    final_resume_json["css"] = "body { display: none }"

    with pytest.raises(
        ResumePdfRenderError,
        match="FinalResume JSON failed schema validation",
    ):
        render_final_resume_html(final_resume_json)


def test_pdf_validation_rejects_wrong_template_version_and_page_count() -> None:
    final_resume_json = final_review_payload("master-resume")["finalResume"]
    resume = FinalResume.model_validate(final_resume_json)
    bundle = load_template_bundle("classic_single")
    rendered = render_final_resume_pdf(final_resume_json)

    wrong_version = rewrite_pdf(
        rendered,
        template_version="9.9.9",
    )
    with pytest.raises(
        ResumePdfValidationError,
        match="metadata does not match",
    ):
        validate_rendered_pdf(
            wrong_version,
            resume=resume,
            bundle=bundle,
        )

    too_many_pages = rewrite_pdf(
        rendered,
        page_count=bundle.manifest.validation.max_pages + 1,
    )
    with pytest.raises(
        ResumePdfValidationError,
        match="page count is outside",
    ):
        validate_rendered_pdf(
            too_many_pages,
            resume=resume,
            bundle=bundle,
        )


def test_pdf_validation_rejects_missing_text_reading_order_and_overflow() -> None:
    with pytest.raises(ResumePdfValidationError, match="missing expected text"):
        validate_expected_text("first third", ["first", "second", "third"])
    with pytest.raises(ResumePdfValidationError, match="reading order"):
        validate_reading_order("second first", ["first", "second"])

    final_resume_json = final_review_payload("master-resume")["finalResume"]
    with pytest.raises(ResumePdfValidationError, match="contains overflow"):
        validate_rendered_pdf(
            render_final_resume_pdf(final_resume_json),
            resume=FinalResume.model_validate(final_resume_json),
            bundle=load_template_bundle("classic_single"),
            html_overflow_issues=("paragraph exceeds resume width",),
        )


def test_chromium_layout_validation_detects_horizontal_overflow() -> None:
    result = chromium_pdf_from_html(
        """
        <!doctype html>
        <html>
          <body>
            <div class="resume-shell" style="width: 120px">
              <p style="width: 40px; white-space: nowrap">
                text-that-cannot-fit-inside-the-box
              </p>
            </div>
          </body>
        </html>
        """,
        load_template_bundle("classic_single").manifest.page,
    )

    assert any(
        "exceeds" in issue
        for issue in result.overflow_issues
    )


def test_pdf_validation_rasterizes_every_page_of_long_resume() -> None:
    final_resume_json = final_review_payload("master-resume")["finalResume"]
    source_experience = final_resume_json["experiences"][0]
    experiences = []
    for index in range(12):
        experience = deepcopy(source_experience)
        experience["id"] = f"rewritten-experience:{index:04d}"
        experience["masterExperienceId"] = f"experience:company:{index:04d}"
        experience["company"] = f"Company {index + 1}"
        experience["bullets"][0]["id"] = f"rewritten-bullet:{index:04d}"
        experiences.append(experience)
    final_resume_json["experiences"] = experiences

    rendered = render_final_resume_pdf(final_resume_json)
    resume = FinalResume.model_validate(final_resume_json)
    report = validate_rendered_pdf(
        rendered,
        resume=resume,
        bundle=load_template_bundle("classic_single"),
    )

    assert report.page_count > 1
    assert report.png_page_count == report.page_count


def rewrite_pdf(
    pdf: bytes,
    *,
    template_version: str | None = None,
    page_count: int | None = None,
) -> bytes:
    reader = PdfReader(BytesIO(pdf))
    writer = PdfWriter()
    if page_count is None:
        writer.clone_document_from_reader(reader)
    else:
        for _ in range(page_count):
            writer.add_page(reader.pages[0])
    metadata = {
        key: str(value)
        for key, value in (reader.metadata or {}).items()
        if isinstance(key, str) and value is not None
    }
    if template_version is not None:
        metadata[PDF_TEMPLATE_VERSION_METADATA_KEY] = template_version
    writer.add_metadata(metadata)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
