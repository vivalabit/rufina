import json
from collections.abc import Generator

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import resume_tailoring as resume_tailoring_api
from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.jobs import StoredJobRecord
from app.models.resume import (
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
from app.services.generation_context import AuthoritativeConfirmation
from app.services.resume_tailoring import (
    SENIOR_RECRUITER_PROMPT_VERSION,
    ResumeTailoringError,
    SeniorRecruiterAnalysisOutcome,
    analyze_resume_as_senior_recruiter,
    master_resume_with_candidate_confirmations,
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
        "summary": {
            "text": "Platform engineer building reliable Python services.",
            "evidenceIds": ["profile:python"],
        },
        "experiences": [],
        "skills": [
            {
                "id": "skill:python",
                "name": "Python",
                "evidenceIds": ["profile:python"],
            }
        ],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [
            {
                "id": "profile:python",
                "type": "profile",
                "text": "Built reliable Python services.",
            }
        ],
        "sectionOrder": ["summary", "skills"],
    }


def recruiter_analysis_payload() -> dict[str, object]:
    return {
        "missingKeywords": [
            {
                "keyword": "Kubernetes",
                "whyItMatters": "Required for the target platform.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
            {
                "keyword": "Terraform",
                "whyItMatters": "Required for infrastructure automation.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
            {
                "keyword": "Observability",
                "whyItMatters": "The role owns production reliability.",
                "evidenceStatus": "transferable",
                "evidenceIds": ["profile:python"],
            },
            {
                "keyword": "SRE",
                "whyItMatters": "The vacancy emphasizes reliability ownership.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
            {
                "keyword": "Incident response",
                "whyItMatters": "The team has an operational on-call scope.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
        ],
        "redFlags": [
            {
                "flag": "No quantified impact",
                "whyItIsVisible": "The summary has no measurable outcome.",
                "fix": "Surface an existing evidence-backed result.",
            },
            {
                "flag": "No recent experience chronology",
                "whyItIsVisible": "There are no experience entries.",
                "fix": "Add the verified work history.",
            },
            {
                "flag": "Cloud stack is not visible",
                "whyItIsVisible": "The skills section lists only Python.",
                "fix": "Add only cloud tools supported by evidence.",
            },
        ],
    }


def vacancy_payload() -> dict[str, object]:
    return {
        "id": "job-platform",
        "company": "Exact Company AG",
        "title": "Senior Platform Engineer",
        "overview": "Own Kubernetes infrastructure, reliability, and on-call.",
        "requirements": ["Kubernetes", "Terraform", "observability"],
    }


def test_senior_recruiter_output_requires_exactly_five_keywords_and_three_flags() -> None:
    analysis = SeniorRecruiterAnalysis.model_validate(recruiter_analysis_payload())

    assert len(analysis.missing_keywords) == 5
    assert len(analysis.red_flags) == 3

    too_few_keywords = recruiter_analysis_payload()
    too_few_keywords["missingKeywords"] = too_few_keywords["missingKeywords"][:4]
    with pytest.raises(ValidationError):
        SeniorRecruiterAnalysis.model_validate(too_few_keywords)

    too_many_flags = recruiter_analysis_payload()
    too_many_flags["redFlags"] = [
        *too_many_flags["redFlags"],
        {
            "flag": "Generic headline",
            "whyItIsVisible": "It does not name the target specialty.",
            "fix": "Use an evidence-backed specialty.",
        },
    ]
    with pytest.raises(ValidationError):
        SeniorRecruiterAnalysis.model_validate(too_many_flags)


def test_senior_recruiter_output_is_strict_and_evidence_consistent() -> None:
    extra_field = recruiter_analysis_payload()
    extra_field["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SeniorRecruiterAnalysis.model_validate(extra_field)

    unsupported_with_evidence = recruiter_analysis_payload()
    unsupported_with_evidence["missingKeywords"][0]["evidenceIds"] = [
        "profile:python"
    ]
    with pytest.raises(
        ValidationError,
        match="unsupported keywords must not cite resume evidence",
    ):
        SeniorRecruiterAnalysis.model_validate(unsupported_with_evidence)


def test_senior_recruiter_analysis_uses_one_isolated_typed_ai_request() -> None:
    requests: list[AIRequest] = []

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            return AIResult(
                text="",
                structured_data=recruiter_analysis_payload(),
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(
                    input_tokens=120,
                    output_tokens=80,
                    total_tokens=200,
                    source="provider",
                ),
                latency_ms=432,
                session_id="response-recruiter-1",
            )

    outcome = analyze_resume_as_senior_recruiter(
        master_resume=MasterResume.model_validate(
            master_resume_payload("master-resume")
        ),
        target_job_id="job-platform",
        vacancy=vacancy_payload(),
        backend=FakeBackend(),
        model="gpt-5.6-terra",
        agent_id="rufina-assistant",
        thinking="high",
        timeout_seconds=120,
    )

    assert len(requests) == 1
    assert requests[0].structured is True
    assert requests[0].response_model is SeniorRecruiterAnalysis
    assert "MANDATORY RESUME TAILORING REQUEST 1" in requests[0].prompt
    assert "Act as senior recruiter for this exact company" in requests[0].prompt
    assert "Exact Company AG" in requests[0].prompt
    assert "exactly five missingKeywords and exactly three redFlags" in (
        requests[0].prompt
    )
    schema_text = (
        requests[0]
        .prompt.split("SENIOR_RECRUITER_ANALYSIS_JSON_SCHEMA:\n", 1)[1]
        .split("\nCONTEXT_JSON:\n", 1)[0]
    )
    prompt_schema = json.loads(schema_text)
    assert set(prompt_schema["required"]) == {"missingKeywords", "redFlags"}
    assert prompt_schema["properties"]["missingKeywords"]["minItems"] == 5
    assert prompt_schema["properties"]["missingKeywords"]["maxItems"] == 5
    assert prompt_schema["properties"]["redFlags"]["minItems"] == 3
    assert prompt_schema["properties"]["redFlags"]["maxItems"] == 3
    assert len(outcome.analysis.missing_keywords) == 5
    assert len(outcome.analysis.red_flags) == 3


def test_senior_recruiter_analysis_rejects_unknown_evidence_ids() -> None:
    payload = recruiter_analysis_payload()
    payload["missingKeywords"][2]["evidenceIds"] = ["profile:invented"]

    class FakeBackend:
        name = "openai_api"

        def generate(self, _request: AIRequest) -> AIResult:
            return AIResult(
                text="",
                structured_data=payload,
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="response-recruiter-invalid",
            )

    with pytest.raises(ResumeTailoringError, match="unknown resume evidence IDs"):
        analyze_resume_as_senior_recruiter(
            master_resume=MasterResume.model_validate(
                master_resume_payload("master-resume")
            ),
            target_job_id="job-platform",
            vacancy=vacancy_payload(),
            backend=FakeBackend(),
            model="gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="high",
            timeout_seconds=120,
        )


def test_candidate_confirmations_enter_resume_pipeline_in_recruiter_analysis() -> None:
    requests: list[AIRequest] = []
    confirmation = AuthoritativeConfirmation(
        question_id="production-kubernetes",
        requirement="Production Kubernetes",
        question="What Kubernetes workload did you operate in production?",
        why="This detail can strengthen the CV and cover letter.",
        claim_if_confirmed="Operated Kubernetes workloads in production.",
        response="partial",
        example_text="Maintained deployment manifests and reviewed production incidents.",
        blocking=True,
    )
    master_resume = master_resume_with_candidate_confirmations(
        MasterResume.model_validate(master_resume_payload("master-resume")),
        (confirmation,),
    )

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            return AIResult(
                text="",
                structured_data=recruiter_analysis_payload(),
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="response-confirmation-evidence",
            )

    outcome = analyze_resume_as_senior_recruiter(
        master_resume=master_resume,
        target_job_id="job-platform",
        vacancy=vacancy_payload(),
        backend=FakeBackend(),
        model="gpt-5.6-terra",
        agent_id="rufina-assistant",
        thinking="high",
        timeout_seconds=120,
    )

    assert "confirmation:production-kubernetes" in requests[0].prompt
    assert confirmation.example_text in requests[0].prompt
    assert [
        evidence.id for evidence in outcome.analysis.supplemental_evidence
    ] == ["confirmation:production-kubernetes"]


def test_resume_confirmation_evidence_excludes_negative_and_contact_answers() -> None:
    master_resume = MasterResume.model_validate(
        master_resume_payload("master-resume")
    )
    confirmations = (
        AuthoritativeConfirmation(
            question_id="missing-skill",
            requirement="Missing skill",
            question="Do you have this skill?",
            why="It affects positioning.",
            claim_if_confirmed="Has the missing skill.",
            response="no",
            example_text="",
            blocking=True,
        ),
        AuthoritativeConfirmation(
            question_id="cover-letter-recipient-name",
            requirement="Recipient",
            question="Who is the recipient?",
            why="It changes the greeting.",
            claim_if_confirmed="Has a named recipient.",
            response="yes",
            example_text="Grace Hopper",
            blocking=False,
        ),
        AuthoritativeConfirmation(
            question_id="cover-letter-additional-context",
            requirement="Additional context",
            question="What should the documents emphasize?",
            why="It guides both documents.",
            claim_if_confirmed="Supplied additional document context.",
            response="yes",
            example_text="Emphasize the production migration achievement.",
            blocking=False,
        ),
    )

    enriched = master_resume_with_candidate_confirmations(
        master_resume,
        confirmations,
    )

    assert {
        evidence.id for evidence in enriched.evidence
    } == {
        "profile:python",
        "confirmation:cover-letter-additional-context",
    }


def test_senior_recruiter_endpoint_persists_result_and_metrics(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    master_resume_id = "a" * 32
    master_version_id = "b" * 32
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
                content_sha256="c" * 64,
            )
        )
        db.add(
            StoredJobRecord(
                id="job-platform",
                data=vacancy_payload(),
                status="active",
            )
        )
        db.commit()

    analysis = SeniorRecruiterAnalysis.model_validate(
        recruiter_analysis_payload()
    )
    result = AIResult(
        text="",
        structured_data=recruiter_analysis_payload(),
        model="gpt-5.6-terra",
        backend="openai_api",
        usage=AIUsage(
            input_tokens=120,
            output_tokens=80,
            total_tokens=200,
            source="provider",
        ),
        latency_ms=432,
        session_id="response-recruiter-1",
    )
    calls: list[tuple[str, str]] = []

    class FakeFacade:
        def analyze_as_senior_recruiter(
            self,
            *,
            master_resume: MasterResume,
            target_job_id: str,
            vacancy: dict[str, object],
        ) -> SeniorRecruiterAnalysisOutcome:
            calls.append((master_resume.id, target_job_id))
            return SeniorRecruiterAnalysisOutcome(
                analysis=analysis,
                result=result,
                vacancy_hash="d" * 64,
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
        "/resume-tailoring/senior-recruiter-analysis",
        json={
            "masterResumeId": master_resume_id,
            "targetJobId": "job-platform",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [(master_resume_id, "job-platform")]
    assert len(body["analysis"]["missingKeywords"]) == 5
    assert len(body["analysis"]["redFlags"]) == 3
    assert body["metrics"] == {
        "latencyMs": 432,
        "inputTokens": 120,
        "outputTokens": 80,
        "totalTokens": 200,
        "tokenCountSource": "provider",
    }
    assert body["model"] == "gpt-5.6-terra"
    assert body["backend"] == "openai_api"
    assert body["promptVersion"] == SENIOR_RECRUITER_PROMPT_VERSION
    assert body["attempt"] == 1
    assert isinstance(body["runId"], str)

    with api_sessions() as db:
        records = db.scalars(select(SeniorRecruiterAnalysisRecord)).all()
        assert len(records) == 1
        record = records[0]
        assert record.resume_master_version_id == master_version_id
        assert record.result == recruiter_analysis_payload()
        assert record.vacancy_hash == "d" * 64
        assert record.input_tokens == 120
        assert record.output_tokens == 80
        assert record.total_tokens == 200
        assert record.token_count_source == "provider"
        assert record.latency_ms == 432
        assert record.provider_session_id == "response-recruiter-1"
        run = db.get(ResumeTailoringRunRecord, body["runId"])
        stage = db.scalar(select(ResumeTailoringStageRecord))
        assert run is not None
        assert run.status == "running"
        assert run.current_stage == 1
        assert stage is not None
        assert stage.status == "succeeded"
        assert stage.output_record_id == record.id
        assert stage.structured_output == recruiter_analysis_payload()


def test_senior_recruiter_endpoint_enforces_owner_scope(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    master_resume_id = "e" * 32
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
                id="f" * 32,
                resume_master_id=master_resume_id,
                version=1,
                schema_version="1.0",
                data=master_resume.model_dump(by_alias=True, exclude_none=True),
                content_sha256="0" * 64,
                owner_id="owner-b",
            )
        )
        db.commit()

    monkeypatch.setattr(
        resume_tailoring_api,
        "create_resume_tailoring_ai_facade",
        lambda _settings: pytest.fail("AI must not run for a foreign resume"),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True
    )

    response = TestClient(app).post(
        "/resume-tailoring/senior-recruiter-analysis",
        headers={"X-Rufina-Owner-Id": "owner-a"},
        json={
            "masterResumeId": master_resume_id,
            "targetJobId": "job-platform",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Master resume not found"


def test_senior_recruiter_failure_is_persisted_as_failed_attempt(
    monkeypatch: pytest.MonkeyPatch,
    api_sessions: sessionmaker[Session],
) -> None:
    master_resume_id = "1" * 32
    master_version_id = "2" * 32
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
                content_sha256="3" * 64,
            )
        )
        db.add(
            StoredJobRecord(
                id="job-platform",
                data=vacancy_payload(),
                status="active",
            )
        )
        db.commit()

    class FailingFacade:
        def analyze_as_senior_recruiter(
            self,
            *,
            master_resume: MasterResume,
            target_job_id: str,
            vacancy: dict[str, object],
        ) -> SeniorRecruiterAnalysisOutcome:
            raise ResumeTailoringError("Simulated provider failure")

    monkeypatch.setattr(
        resume_tailoring_api,
        "create_resume_tailoring_ai_facade",
        lambda _settings: FailingFacade(),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_tailoring_enabled=True
    )

    response = TestClient(app).post(
        "/resume-tailoring/senior-recruiter-analysis",
        json={
            "masterResumeId": master_resume_id,
            "targetJobId": "job-platform",
        },
    )

    assert response.status_code == 502
    with api_sessions() as db:
        run = db.scalar(select(ResumeTailoringRunRecord))
        stage = db.scalar(select(ResumeTailoringStageRecord))
        assert run is not None
        assert run.status == "failed"
        assert run.error == "Simulated provider failure"
        assert stage is not None
        assert stage.status == "failed"
        assert stage.error == "Simulated provider failure"
        assert stage.attempt == 1
        assert stage.model
        assert stage.backend in {"openclaw_codex", "openai_api"}
        assert len(stage.input_fingerprint) == 64
        assert stage.structured_output is None
