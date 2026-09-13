from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.core.identity import get_bound_owner_id
from app.models.generation_runs import (
    ApplicationGenerationRunRecord,
    GenerationRunEventRecord,
    GenerationRunStartRequest,
)
from app.services.generation_store import (
    create_generation_run,
    queue_fit_decision,
    transition_generation_run,
)
from app.services.generation_worker import (
    recover_expired_generation_runs,
    run_generation_cycle,
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
        openclaw_assistant_model="openai/gpt-worker",
        openclaw_assistant_thinking="high",
        openclaw_assistant_timeout_seconds=180,
        openclaw_assistant_max_attempts=1,
        openclaw_assistant_retry_backoff_seconds=0,
    )


def _start() -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=("tailored_resume",),
        language="English",
        formattingParameters={"tailored_resume": {"templateId": "classic_single"}},
        userPreferences="",
        idempotencyKey="worker-run",
    )


class FakeWorkflow:
    def __init__(self) -> None:
        self.owner_ids: list[str] = []

    def evaluate_fit(self, db: Session, run: ApplicationGenerationRunRecord) -> None:
        self.owner_ids.append(get_bound_owner_id())
        transition_generation_run(
            db,
            run=run,
            status="awaiting_approval",
            stage="fit",
            event_kind="fit.completed",
            pending_question={"id": "continue_after_fit"},
        )

    def continue_approved_run(self, db: Session, run: ApplicationGenerationRunRecord) -> None:
        self.owner_ids.append(get_bound_owner_id())
        transition_generation_run(
            db,
            run=run,
            status="completed",
            stage="final_review",
            event_kind="run.completed",
        )


def test_worker_reserves_pauses_and_resumes_a_run(sessions: sessionmaker[Session]) -> None:
    seed_complete_sources(sessions)
    workflow = FakeWorkflow()
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run_id = run.id

    assert (
        run_generation_cycle(
            settings=_settings(),
            session_factory=sessions,
            workflow_factory=lambda _settings: workflow,
        )
        == run_id
    )
    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run is not None and run.status == "awaiting_approval"
        queue_fit_decision(
            db,
            run=run,
            question_id="continue_after_fit",
            response="continue",
            expected_revision=run.revision,
        )

    assert (
        run_generation_cycle(
            settings=_settings(),
            session_factory=sessions,
            workflow_factory=lambda _settings: workflow,
        )
        == run_id
    )
    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run is not None and run.status == "completed"
        assert run.lease_token is None and run.lease_until is None
    assert workflow.owner_ids == ["local-owner", "local-owner"]


def test_expired_running_lease_is_requeued_with_an_audit_event(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    now = datetime.now(UTC)
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.status = "running"
        run.stage = "draft"
        run.lease_token = "dead-worker"
        run.lease_until = now - timedelta(seconds=1)
        db.commit()
        run_id = run.id

    assert recover_expired_generation_runs(sessions, now=now) == [run_id]
    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        event = db.scalar(
            select(GenerationRunEventRecord)
            .where(GenerationRunEventRecord.run_id == run_id)
            .order_by(GenerationRunEventRecord.sequence.desc())
        )
        assert run is not None and run.status == "queued"
        assert event is not None and event.kind == "run.recovered"
