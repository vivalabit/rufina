import hashlib
import json
from collections import deque
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.generation_runs import (
    GenerationRunMessageRecord,
    GenerationRunStartRequest,
)
from app.models.generation_workflow import DraftBundle
from app.models.resume import MasterResume, ResumeMasterVersionRecord
from app.services.ai_backend import AIResult, AIUsage
from app.services.generation_grounding import (
    GenerationGroundingError,
    validate_grounded_bundle,
)
from app.services.generation_store import create_generation_run
from app.services.generation_workflow import GenerationWorkflow


class FakeBackend:
    name = "openclaw_codex"

    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = deque(payloads)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        payload = self.payloads.popleft()
        return AIResult(
            text=json.dumps(payload),
            structured_data=payload,
            model=request.model,
            backend="openclaw_codex",
            usage=AIUsage(input_tokens=10, output_tokens=20, total_tokens=30),
            latency_ms=5,
            session_id=request.session_id,
            raw_response=json.dumps(payload),
        )


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        ai_backend_mode="openclaw_codex",
        openai_api_model="gpt-direct",
        openai_api_reasoning_effort="medium",
        openai_api_timeout_seconds=120,
        openai_api_max_attempts=2,
        openai_api_retry_backoff_seconds=0,
        openclaw_command="openclaw",
        openclaw_assistant_agent_id="rufina-assistant",
        openclaw_assistant_model="openai/gpt-worker",
        openclaw_assistant_thinking="high",
        openclaw_assistant_timeout_seconds=180,
        openclaw_assistant_max_attempts=1,
        openclaw_assistant_retry_backoff_seconds=0,
        openai_api_key="",
        openai_api_base_url="https://api.openai.com/v1",
    )


def _start() -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=("tailored_resume",),
        language="English",
        formattingParameters={"tailored_resume": {"templateId": "classic_single"}},
        userPreferences="Keep it factual.",
        idempotencyKey="workflow-1",
    )


def _seed(sessions: sessionmaker[Session]) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        version = db.scalar(
            select(ResumeMasterVersionRecord).where(
                ResumeMasterVersionRecord.resume_master_id == "master-profile",
                ResumeMasterVersionRecord.version == 2,
            )
        )
        assert version is not None
        data = dict(version.data)
        data["summary"] = {"text": "Builds reliable platforms.", "evidenceIds": ["source:one"]}
        data["evidence"] = [
            {"id": "source:one", "type": "source", "text": "Builds reliable platforms."}
        ]
        data["sectionOrder"] = ["summary"]
        canonical = json.dumps(
            data, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        db.execute(
            update(ResumeMasterVersionRecord)
            .where(ResumeMasterVersionRecord.id == version.id)
            .values(data=data, content_sha256=hashlib.sha256(canonical).hexdigest())
        )
        db.commit()


def _fit() -> dict[str, object]:
    return {
        "eligible": True,
        "overallScore": 82,
        "recommendation": "yes",
        "summary": "Good evidence-backed fit.",
        "strengths": ["Platform experience"],
        "gaps": ["No explicit Go experience"],
        "keywords": [
            {
                "term": "Python",
                "importance": "required",
                "support": "supported",
                "evidenceIds": [],
            }
        ],
        "clarificationQuestions": [],
    }


def _draft() -> dict[str, object]:
    return {
        "resume": {
            "schemaVersion": "1.0",
            "id": "tailored-1",
            "masterResumeId": "master-profile",
            "targetJobId": "vacancy-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace", "headline": "Platform Engineer"},
            "summary": {
                "text": "Builds reliable platforms.",
                "evidenceIds": ["source:one"],
            },
            "experiences": [],
            "skills": [],
            "education": [],
            "projects": [],
            "certifications": [],
            "languages": [],
            "additionalSections": [],
            "evidence": [
                {
                    "id": "source:one",
                    "type": "source",
                    "text": "Builds reliable platforms.",
                }
            ],
            "sectionOrder": ["summary"],
        },
        "coverLetter": None,
    }


def _review() -> dict[str, object]:
    return {
        "approved": True,
        "summary": "Grounded and consistent.",
        "findings": [],
        "meaningfulChanges": ["Focused the headline on platform engineering"],
        "companySources": [],
    }


def test_workflow_pauses_after_fit_then_uses_separate_author_and_reviewer_sessions(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    backend = FakeBackend([_fit(), _draft(), _review()])
    workflow = GenerationWorkflow(settings=_settings(), backend=backend)
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        evaluation = workflow.evaluate_fit(db, run)
        assert evaluation.overall_score == 82
        assert run.status == "awaiting_approval"
        assert run.pending_question["id"] == "continue_after_fit"

        outcome = workflow.respond_to_fit(db, run, continue_generation=True)
        messages = db.scalars(
            select(GenerationRunMessageRecord)
            .where(GenerationRunMessageRecord.run_id == run.id)
            .order_by(GenerationRunMessageRecord.sequence)
        ).all()

    assert outcome is not None and outcome.review.approved is True
    assert run.status == "running" and run.stage == "pdf_checks"
    assert backend.requests[-1].enable_web_search is True
    sessions_used = {request.session_id.rsplit(":", 1)[-1] for request in backend.requests}
    assert sessions_used == {"fit", "author", "reviewer"}
    assert {message.actor for message in messages} >= {"author", "reviewer", "user"}
    assert any(message.raw_response.startswith("{") for message in messages)
    assert "BEGIN UNTRUSTED APPLICATION DATA" in backend.requests[0].prompt


def test_declining_fit_finishes_without_drafting(sessions: sessionmaker[Session]) -> None:
    _seed(sessions)
    backend = FakeBackend([_fit()])
    workflow = GenerationWorkflow(settings=_settings(), backend=backend)
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        workflow.evaluate_fit(db, run)
        assert workflow.respond_to_fit(db, run, continue_generation=False) is None

    assert run.status == "cancelled"
    assert len(backend.requests) == 1


def test_grounding_rejects_modified_canonical_evidence() -> None:
    master = MasterResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "master-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace"},
            "summary": {"text": "Built APIs.", "evidenceIds": ["source:one"]},
            "evidence": [{"id": "source:one", "type": "source", "text": "Built APIs."}],
            "sectionOrder": ["summary"],
        }
    )
    bundle = DraftBundle.model_validate(
        {
            "resume": {
                "schemaVersion": "1.0",
                "id": "tailored-1",
                "masterResumeId": "master-1",
                "targetJobId": "job-1",
                "language": "English",
                "basics": {"fullName": "Ada Lovelace"},
                "summary": {
                    "text": "Built APIs for millions of users.",
                    "evidenceIds": ["source:one"],
                },
                "evidence": [
                    {
                        "id": "source:one",
                        "type": "source",
                        "text": "Built APIs for millions of users.",
                    }
                ],
                "sectionOrder": ["summary"],
            }
        }
    )

    with pytest.raises(GenerationGroundingError, match="non-canonical"):
        validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")
