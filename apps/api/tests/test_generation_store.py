from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.applications import StoredApplicationRecord
from app.models.generation_runs import (
    GenerationRunArtifactRecord,
    GenerationRunCheckRecord,
    GenerationRunEventRecord,
    GenerationRunStartRequest,
)
from app.models.jobs import StoredJobRecord
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


def _settings(backend: str = "openclaw_codex") -> SimpleNamespace:
    return SimpleNamespace(
        ai_backend_mode=backend,
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
    assert payload.events[0].data["resumeTemplateId"] == "moderncv_banking"
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


def test_parallel_applications_are_isolated_and_backend_changes_only_affect_new_runs(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        db.add_all(
            [
                StoredApplicationRecord(
                    id="application-2",
                    revision=1,
                    data={
                        "id": "application-2",
                        "status": "draft",
                        "job": {"id": "vacancy-2"},
                    },
                ),
                StoredJobRecord(
                    id="vacancy-2",
                    revision=1,
                    data={
                        "id": "vacancy-2",
                        "title": "Reliability Engineer",
                        "company": "Second AG",
                        "overview": "Improve production reliability.",
                    },
                ),
            ]
        )
        db.commit()

        first = create_generation_run(
            db,
            application_id="application-1",
            request=_request("application-one"),
            settings=_settings("openclaw_codex"),
        )
        parallel = create_generation_run(
            db,
            application_id="application-2",
            request=_request("application-two"),
            settings=_settings("openai_api"),
        )
        old_artifact = persist_run_artifact(
            db,
            run=first,
            artifact_type="resume_pdf",
            document_type="tailored_resume",
            file_name="first.pdf",
            content_type="application/pdf",
            content=b"%PDF-first",
        )
        persist_run_check(
            db,
            run=first,
            artifact=old_artifact,
            check_type="text_layer",
            status="passed",
        )
        transition_generation_run(
            db,
            run=first,
            status="completed",
            stage="final_review",
            event_kind="run.completed",
        )
        replacement = create_generation_run(
            db,
            application_id="application-1",
            request=_request("application-one-revision"),
            settings=_settings("openai_api"),
        )
        replacement_artifact = persist_run_artifact(
            db,
            run=replacement,
            artifact_type="resume_pdf_attempt",
            document_type="tailored_resume",
            file_name="replacement-attempt.pdf",
            content_type="application/pdf",
            content=b"%PDF-replacement",
        )
        replacement_payload = generation_run_payload(db, replacement)
        first_backend = first.backend
        first_snapshot_backend = first.settings_snapshot["backend"]
        parallel_backend = parallel.backend
        replacement_backend = replacement.backend
        parallel_application_id = parallel.application_id
        replacement_application_id = replacement.application_id
        old_sha256 = old_artifact.content_sha256

    assert first_backend == "openclaw_codex"
    assert first_snapshot_backend == "openclaw_codex"
    assert parallel_backend == "openai_api"
    assert replacement_backend == "openai_api"
    assert parallel_application_id != replacement_application_id
    assert replacement_payload.checks == []
    assert replacement_payload.artifacts[0].content_sha256 == (
        replacement_artifact.content_sha256
    )
    assert replacement_payload.artifacts[0].content_sha256 != old_sha256
