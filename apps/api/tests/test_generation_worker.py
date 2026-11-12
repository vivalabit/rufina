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
    GenerationRunCheckRecord,
    GenerationRunEventRecord,
    GenerationRunStartRequest,
)
from app.services.generation_store import (
    create_generation_run,
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

    def run(self, db: Session, run: ApplicationGenerationRunRecord) -> None:
        self.owner_ids.append(get_bound_owner_id())
        transition_generation_run(
            db,
            run=run,
            status="completed",
            stage="final_review",
            event_kind="run.completed",
        )


def test_worker_reserves_a_run_and_finishes_it_in_one_cycle(
    sessions: sessionmaker[Session],
) -> None:
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
        assert run is not None and run.status == "completed"
        assert run.lease_token is None and run.lease_until is None
    assert workflow.owner_ids == ["local-owner"]
    # Nothing is left to do: a finished run is never picked up again.
    assert (
        run_generation_cycle(
            settings=_settings(),
            session_factory=sessions,
            workflow_factory=lambda _settings: workflow,
        )
        is None
    )


@pytest.mark.parametrize("database_failure", [False, True])
def test_unhandled_worker_failure_is_terminal_and_releases_lease(
    sessions: sessionmaker[Session], database_failure: bool,
) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", request=_start(), settings=_settings(),
        )
        run_id = run.id

    class BrokenWorkflow(FakeWorkflow):
        def run(self, db, run):
            transition_generation_run(
                db, run=run, status="running", stage="fit", event_kind="plan.completed",
            )
            if database_failure:
                db.add(GenerationRunCheckRecord(
                    id="invalid-check", run_id=run.id, check_type="example", status=None,
                ))
                db.flush()
            raise RuntimeError("Unexpected workflow failure")

    assert run_generation_cycle(
        settings=_settings(), session_factory=sessions,
        workflow_factory=lambda _settings: BrokenWorkflow(),
    ) == run_id
    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "failed"
        assert run.error["code"] == "worker_failed"
        assert run.completed_at is not None
        assert run.lease_token is None and run.lease_until is None
        assert db.get(GenerationRunCheckRecord, "invalid-check") is None
        failures = db.scalars(select(GenerationRunEventRecord).where(
            GenerationRunEventRecord.run_id == run_id,
            GenerationRunEventRecord.kind == "run.failed",
        )).all()
        assert len(failures) == 1
    assert run_generation_cycle(
        settings=_settings(), session_factory=sessions,
        workflow_factory=lambda _settings: BrokenWorkflow(),
    ) is None


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
        # A recovered run starts again from the first stage.
        assert run.stage == "sources"
        assert event is not None and event.kind == "run.recovered"
