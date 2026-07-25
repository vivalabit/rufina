from collections.abc import Callable, Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import resume_tailoring as resume_tailoring_api
from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.resume import (
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
from app.services.resume_tailoring import (
    EXPERIENCE_REWRITE_PROMPT_VERSION,
    ExperienceRewriteOutcome,
    ResumeTailoringError,
    rewrite_experience_with_xyz,
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
        },
        "experiences": [
            {
                "id": "experience:acme",
                "company": "Acme AG",
                "title": "Platform Engineer",
                "employmentType": "Full-time",
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
                    },
                    {
                        "id": "bullet:acme:reliability",
                        "text": "Reduced incidents from 20 to 8 with service alerts.",
                        "evidenceIds": ["profile:acme:reliability"],
                    },
                ],
            },
            {
                "id": "experience:beta",
                "company": "Beta GmbH",
                "title": "Software Engineer",
                "location": "Basel",
                "startDate": "2020-02",
                "endDate": "2021-12",
                "bullets": [
                    {
                        "id": "bullet:beta:api",
                        "text": "Cut API response time by 25% using Python caching.",
                        "evidenceIds": ["profile:beta:api"],
                    }
                ],
            },
        ],
        "skills": [],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [
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
                "id": "profile:acme:reliability",
                "type": "profile",
                "text": "Reduced incidents from 20 to 8 with service alerts.",
                "claimType": "achievement",
                "experienceId": "experience:acme",
            },
            {
                "id": "profile:beta:api",
                "type": "profile",
                "text": "Cut API response time by 25% using Python caching.",
                "claimType": "achievement",
                "experienceId": "experience:beta",
            },
        ],
        "sectionOrder": ["experience"],
    }


def recruiter_analysis_payload() -> dict[str, object]:
    keywords = [
        (
            "Kubernetes",
            "verified",
            ["profile:acme:scale"],
        ),
        ("Terraform", "unsupported", []),
        ("Observability", "transferable", ["profile:acme:reliability"]),
        ("SRE", "unsupported", []),
        ("Incident response", "unsupported", []),
    ]
    return {
        "missingKeywords": [
            {
                "keyword": keyword,
                "whyItMatters": f"{keyword} matters for this vacancy.",
                "evidenceStatus": evidence_status,
                "evidenceIds": evidence_ids,
            }
            for keyword, evidence_status, evidence_ids in keywords
        ],
        "redFlags": [
            {
                "flag": "Impact is buried",
                "whyItIsVisible": "Metrics do not lead the bullets.",
                "fix": "Lead with the measured outcome.",
            },
            {
                "flag": "Keywords are underrepresented",
                "whyItIsVisible": "Relevant tooling is hard to scan.",
                "fix": "Use supported role language naturally.",
            },
            {
                "flag": "Bullets read as duties",
                "whyItIsVisible": "The accomplishment is not emphasized.",
                "fix": "Use outcome-first XYZ wording.",
            },
        ],
    }


def experience_rewrite_payload(
    master_resume_id: str,
) -> dict[str, object]:
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
                    },
                    {
                        "id": "rewritten-bullet:0001:0002",
                        "text": (
                            "Reduced incidents from 20 to 8 by implementing "
                            "service-level alerts."
                        ),
                        "evidenceIds": ["profile:acme:reliability"],
                    },
                ],
            },
            {
                "id": "rewritten-experience:0002",
                "masterExperienceId": "experience:beta",
                "company": "Beta GmbH",
                "title": "Software Engineer",
                "location": "Basel",
                "period": "2020-02 — 2021-12",
                "bullets": [
                    {
                        "id": "rewritten-bullet:0002:0001",
                        "text": (
                            "Cut API response time by 25% by introducing "
                            "Python caching."
                        ),
                        "evidenceIds": ["profile:beta:api"],
                    }
                ],
            },
        ],
        "links": [
            {
                "originalExperienceId": "experience:acme",
                "rewrittenExperienceId": "rewritten-experience:0001",
                "bulletLinks": [
                    {
                        "originalBulletIds": ["bullet:acme:scale"],
                        "rewrittenBulletId": "rewritten-bullet:0001:0001",
                    },
                    {
                        "originalBulletIds": ["bullet:acme:reliability"],
                        "rewrittenBulletId": "rewritten-bullet:0001:0002",
                    },
                ],
            },
            {
                "originalExperienceId": "experience:beta",
                "rewrittenExperienceId": "rewritten-experience:0002",
                "bulletLinks": [
                    {
                        "originalBulletIds": ["bullet:beta:api"],
                        "rewrittenBulletId": "rewritten-bullet:0002:0001",
                    }
                ],
            },
        ],
    }


def ai_result(payload: dict[str, object]) -> AIResult:
    return AIResult(
        text="",
        structured_data=payload,
        model="gpt-5.6-terra",
        backend="openai_api",
        usage=AIUsage(
            input_tokens=180,
            output_tokens=120,
            total_tokens=300,
            source="provider",
        ),
        latency_ms=654,
        session_id="response-experience-rewrite-1",
    )


def test_xyz_rewrite_uses_one_typed_experience_only_ai_request() -> None:
    requests: list[AIRequest] = []
    master_resume_id = "master-resume"

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            return ai_result(experience_rewrite_payload(master_resume_id))

    outcome = rewrite_experience_with_xyz(
        master_resume=MasterResume.model_validate(
            master_resume_payload(master_resume_id)
        ),
        target_job_id="job-platform",
        recruiter_analysis=SeniorRecruiterAnalysis.model_validate(
            recruiter_analysis_payload()
        ),
        backend=FakeBackend(),
        model="gpt-5.6-terra",
        agent_id="rufina-assistant",
        thinking="high",
        timeout_seconds=120,
    )

    assert len(requests) == 1
    assert requests[0].structured is True
    assert requests[0].response_model is ExperienceRewrite
    assert "MANDATORY RESUME TAILORING REQUEST 2" in requests[0].prompt
    assert "Use the Google XYZ formula" in requests[0].prompt
    assert "Rewrite Experience only" in requests[0].prompt
    assert "Do not render a document" in requests[0].prompt
    assert len(outcome.rewrite.experiences) == 2
    assert [
        item.master_experience_id for item in outcome.rewrite.experiences
    ] == ["experience:acme", "experience:beta"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: (
                payload["experiences"].pop(),
                payload["links"].pop(),
            ),
            "every original experience in order",
        ),
        (
            lambda payload: payload["experiences"][0].update(
                {"company": "Invented Company"}
            ),
            "immutable experience fields",
        ),
        (
            lambda payload: payload["experiences"][0]["bullets"][0].update(
                {"evidenceIds": ["profile:beta:api"]}
            ),
            "evidence outside the original experience",
        ),
        (
            lambda payload: (
                payload["links"][0]["bulletLinks"][0].update(
                    {"originalBulletIds": ["bullet:acme:reliability"]}
                ),
                payload["links"][0]["bulletLinks"][1].update(
                    {"originalBulletIds": ["bullet:acme:scale"]}
                ),
            ),
            "link every original bullet one-to-one",
        ),
    ],
)
def test_xyz_rewrite_rejects_incomplete_or_cross_experience_changes(
    mutate: Callable[[dict[str, object]], object],
    message: str,
) -> None:
    master_resume_id = "master-resume"
    payload = experience_rewrite_payload(master_resume_id)
    mutate(payload)

    class FakeBackend:
        name = "openai_api"

        def generate(self, _request: AIRequest) -> AIResult:
            return ai_result(payload)

    with pytest.raises(ResumeTailoringError, match=message):
        rewrite_experience_with_xyz(
            master_resume=MasterResume.model_validate(
                master_resume_payload(master_resume_id)
            ),
            target_job_id="job-platform",
            recruiter_analysis=SeniorRecruiterAnalysis.model_validate(
                recruiter_analysis_payload()
            ),
            backend=FakeBackend(),
            model="gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="high",
            timeout_seconds=120,
        )


def test_xyz_rewrite_requires_an_existing_experience_section() -> None:
    payload = master_resume_payload("master-resume")
    payload["experiences"] = []
    payload["sectionOrder"] = []

    with pytest.raises(
        ResumeTailoringError,
        match="does not contain an Experience section",
    ):
        rewrite_experience_with_xyz(
            master_resume=MasterResume.model_validate(payload),
            target_job_id="job-platform",
            recruiter_analysis=SeniorRecruiterAnalysis.model_validate(
                recruiter_analysis_payload()
            ),
            backend=pytest.fail,
            model="gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="high",
            timeout_seconds=120,
        )


def test_experience_rewrite_endpoint_loads_stage_one_and_persists_links(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    master_resume_id = "a" * 32
    master_version_id = "b" * 32
    recruiter_analysis_id = "c" * 32
    master_resume = MasterResume.model_validate(
        master_resume_payload(master_resume_id)
    )
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
                content_sha256="d" * 64,
            )
        )
        db.add(
            SeniorRecruiterAnalysisRecord(
                id=recruiter_analysis_id,
                resume_master_id=master_resume_id,
                resume_master_version_id=master_version_id,
                target_job_id="job-platform",
                vacancy_hash="e" * 64,
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
        db.commit()

    rewrite = ExperienceRewrite.model_validate(
        experience_rewrite_payload(master_resume_id)
    )
    calls: list[tuple[str, str, str]] = []

    class FakeFacade:
        def rewrite_experience_with_xyz(
            self,
            *,
            master_resume: MasterResume,
            target_job_id: str,
            recruiter_analysis: SeniorRecruiterAnalysis,
        ) -> ExperienceRewriteOutcome:
            calls.append(
                (
                    master_resume.id,
                    target_job_id,
                    recruiter_analysis.missing_keywords[0].keyword,
                )
            )
            return ExperienceRewriteOutcome(
                rewrite=rewrite,
                result=ai_result(experience_rewrite_payload(master_resume_id)),
            )

    monkeypatch.setattr(
        resume_tailoring_api,
        "create_resume_tailoring_ai_facade",
        lambda _settings: FakeFacade(),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True
    )

    response = TestClient(app).post(
        "/resume-tailoring/experience-rewrite",
        json={"seniorRecruiterAnalysisId": recruiter_analysis_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [(master_resume_id, "job-platform", "Kubernetes")]
    assert body["seniorRecruiterAnalysisId"] == recruiter_analysis_id
    assert body["masterResumeId"] == master_resume_id
    assert body["masterResumeVersion"] == 1
    assert len(body["experienceRewrite"]["experiences"]) == 2
    assert len(body["experienceRewrite"]["links"]) == 2
    assert body["metrics"] == {
        "latencyMs": 654,
        "inputTokens": 180,
        "outputTokens": 120,
        "totalTokens": 300,
        "tokenCountSource": "provider",
    }
    assert body["promptVersion"] == EXPERIENCE_REWRITE_PROMPT_VERSION
    assert body["attempt"] == 1
    assert isinstance(body["runId"], str)

    with api_sessions() as db:
        records = db.scalars(select(ExperienceRewriteRecord)).all()
        assert len(records) == 1
        record = records[0]
        assert record.senior_recruiter_analysis_id == recruiter_analysis_id
        assert record.resume_master_version_id == master_version_id
        assert record.original_experiences == [
            experience.model_dump(by_alias=True, exclude_none=True)
            for experience in master_resume.experiences
        ]
        assert record.result == experience_rewrite_payload(master_resume_id)
        assert record.links == experience_rewrite_payload(master_resume_id)[
            "links"
        ]
        assert record.input_tokens == 180
        assert record.output_tokens == 120
        assert record.total_tokens == 300
        assert record.latency_ms == 654
        assert record.provider_session_id == "response-experience-rewrite-1"
        run = db.get(ResumeTailoringRunRecord, body["runId"])
        stages = db.scalars(
            select(ResumeTailoringStageRecord).order_by(
                ResumeTailoringStageRecord.stage_number
            )
        ).all()
        assert run is not None
        assert run.status == "running"
        assert run.current_stage == 2
        assert [stage.status for stage in stages] == [
            "succeeded",
            "succeeded",
        ]
        assert stages[1].structured_output == experience_rewrite_payload(
            master_resume_id
        )
        record.links = []
        with pytest.raises(ValueError, match="Experience rewrites are immutable"):
            db.commit()


def test_experience_rewrite_endpoint_requires_saved_stage_one(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    monkeypatch.setattr(
        resume_tailoring_api,
        "create_resume_tailoring_ai_facade",
        lambda _settings: pytest.fail("AI must not run without saved stage one"),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True
    )

    response = TestClient(app).post(
        "/resume-tailoring/experience-rewrite",
        json={"seniorRecruiterAnalysisId": "missing-analysis"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Senior recruiter analysis not found"


def test_experience_rewrite_request_cannot_override_saved_inputs(
    api_sessions: sessionmaker[Session],
) -> None:
    response = TestClient(app).post(
        "/resume-tailoring/experience-rewrite",
        json={
            "seniorRecruiterAnalysisId": "analysis-id",
            "masterResumeId": "different-master",
            "targetJobId": "different-job",
        },
    )

    assert response.status_code == 422


def test_experience_rewrite_endpoint_enforces_owner_scope(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    master_resume_id = "1" * 32
    master_version_id = "2" * 32
    recruiter_analysis_id = "3" * 32
    master_resume = MasterResume.model_validate(
        master_resume_payload(master_resume_id)
    )
    with api_sessions() as db:
        db.add(
            ResumeMasterRecord(
                id=master_resume_id,
                name="Foreign resume",
                language="English",
                current_version=1,
                owner_id="owner-b",
            )
        )
        db.add(
            ResumeMasterVersionRecord(
                id=master_version_id,
                resume_master_id=master_resume_id,
                version=1,
                schema_version="1.0",
                data=master_resume.model_dump(by_alias=True, exclude_none=True),
                content_sha256="4" * 64,
                owner_id="owner-b",
            )
        )
        db.add(
            SeniorRecruiterAnalysisRecord(
                id=recruiter_analysis_id,
                resume_master_id=master_resume_id,
                resume_master_version_id=master_version_id,
                target_job_id="job-platform",
                vacancy_hash="5" * 64,
                prompt_version="senior-recruiter-analysis-v1",
                result=recruiter_analysis_payload(),
                model="gpt-5.6-terra",
                backend="openai_api",
                provider_session_id="response-recruiter-owner-b",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                token_count_source="provider",
                latency_ms=321,
                owner_id="owner-b",
            )
        )
        db.commit()

    monkeypatch.setattr(
        resume_tailoring_api,
        "create_resume_tailoring_ai_facade",
        lambda _settings: pytest.fail("AI must not run for another owner"),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True
    )

    response = TestClient(app).post(
        "/resume-tailoring/experience-rewrite",
        headers={"X-Rufina-Owner-Id": "owner-a"},
        json={"seniorRecruiterAnalysisId": recruiter_analysis_id},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Senior recruiter analysis not found"
