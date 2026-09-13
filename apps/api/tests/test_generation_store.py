from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.generation_runs import (
    GenerationRunArtifactRecord,
    GenerationRunCheckRecord,
    GenerationRunEventRecord,
    GenerationRunStartRequest,
)
from app.services.generation_store import (
    GenerationStoreError,
    create_generation_run,
    generation_run_payload,
    persist_run_artifact,
    persist_run_check,
    request_run_cancellation,
    transition_generation_run,
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
        openai_api_retry_backoff_seconds=0.8,
        openclaw_assistant_model="openai/gpt-worker",
        openclaw_assistant_thinking="high",
        openclaw_assistant_timeout_seconds=180,
        openclaw_assistant_max_attempts=3,
        openclaw_assistant_retry_backoff_seconds=1.0,
    )


def _request(key: str) -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=("tailored_resume",),
        language="English",
        formattingParameters={"tailored_resume": {"templateId": "classic_single", "maxPages": 2}},
        userPreferences="Concise and factual.",
        idempotencyKey=key,
    )


def test_run_persists_snapshot_events_artifacts_checks_and_transition(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_request("start-1"),
            settings=_settings(),
        )
        artifact = persist_run_artifact(
            db,
            run=run,
            artifact_type="resume_pdf",
            document_type="tailored_resume",
            file_name="resume.pdf",
            content_type="application/pdf",
            content=b"%PDF-test",
            metadata={"renderer": "lualatex"},
        )
        persist_run_check(
            db,
            run=run,
            artifact=artifact,
            check_type="pdf_text_readable",
            status="passed",
        )
        transition_generation_run(
            db,
            run=run,
            status="completed",
            stage="final_review",
            event_kind="run.completed",
            result={"summary": "Ready"},
        )
        payload = generation_run_payload(db, run)

    assert run.input_snapshot["request"]["application"]["revision"] == 4
    assert run.settings_snapshot["backend"] == "openclaw_codex"
    assert payload.status == "completed"
    assert [event.sequence for event in payload.events] == [1, 2, 3]
    assert payload.artifacts[0].content_sha256 == artifact.content_sha256
    assert payload.checks[0].artifact_sha256 == artifact.content_sha256


def test_start_is_idempotent_and_rejects_a_second_active_run(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        first = create_generation_run(
            db,
            application_id="application-1",
            request=_request("same-key"),
            settings=_settings(),
        )
        retry = create_generation_run(
            db,
            application_id="application-1",
            request=_request("same-key"),
            settings=_settings(),
        )
        with pytest.raises(GenerationStoreError, match="already active"):
            create_generation_run(
                db,
                application_id="application-1",
                request=_request("another-key"),
                settings=_settings(),
            )

    assert first.id == retry.id


def test_cancellation_uses_optimistic_revision(sessions: sessionmaker[Session]) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_request("cancel-key"),
            settings=_settings(),
        )
        with pytest.raises(GenerationStoreError, match="stale"):
            request_run_cancellation(db, run=run, expected_revision=99)
        request_run_cancellation(db, run=run, expected_revision=run.revision)

        assert run.cancel_requested is True
        assert db.scalar(select(func.count()).select_from(GenerationRunEventRecord)) == 2
        assert db.scalar(select(func.count()).select_from(GenerationRunArtifactRecord)) == 0
        assert db.scalar(select(func.count()).select_from(GenerationRunCheckRecord)) == 0
