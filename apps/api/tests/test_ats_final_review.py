from collections.abc import Generator
from inspect import signature
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import resume_tailoring as resume_tailoring_api
from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.resume import (
    AtsFinalReview,
    AtsFinalReviewRecord,
    ExperienceRewrite,
    ExperienceRewriteRecord,
    MasterResume,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    ResumeTailoringRunRecord,
    ResumeTailoringStageRecord,
    SeniorRecruiterAnalysis,
    SeniorRecruiterAnalysisRecord,
)
from app.services.ai_backend import AIRequest, AIResult, AIUsage
from app.services.ai_privacy import require_current_ai_consent
from app.services.document_export import render_final_resume_json
from app.services.resume_pdf_renderer import (
    ResumePdfRenderError,
    load_template_bundle,
    render_final_resume_html,
    render_final_resume_pdf,
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
    )

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.headers["content-disposition"] == (
        'attachment; filename="Ada-Lovelace-resume.pdf"'
    )
    assert downloaded.content == b"%PDF-1.7\nserver-rendered"
    assert rendered_templates == ["modern_two_column"]
    invalid_template = client.get(
        f"/resume-tailoring/ats-final-review/{body['id']}/pdf",
        params={"templateId": "client_template"},
    )
    assert invalid_template.status_code == 422
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
    ["classic_single", "modern_single", "modern_two_column"],
)
def test_pdf_template_manifests_are_valid_and_render_escaped_html(
    template_id: str,
) -> None:
    final_resume_json = final_review_payload("master-resume")["finalResume"]
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


def test_pdf_renderer_rejects_non_final_resume_fields() -> None:
    final_resume_json = final_review_payload("master-resume")["finalResume"]
    final_resume_json["html"] = "<h1>AI-controlled HTML</h1>"
    final_resume_json["css"] = "body { display: none }"

    with pytest.raises(
        ResumePdfRenderError,
        match="FinalResume JSON failed schema validation",
    ):
        render_final_resume_html(final_resume_json)
