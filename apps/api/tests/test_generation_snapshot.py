from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.generation import GenerationStartRequest
from app.services.generation_snapshot import build_generation_run_snapshot


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def runtime_settings() -> SimpleNamespace:
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


def test_generation_snapshot_pins_sources_templates_and_backend(
    sessions,
) -> None:
    seed_complete_sources(sessions)
    settings = runtime_settings()
    start = GenerationStartRequest(
        document_types=("tailored_resume", "cover_letter"),
        language="English",
        formatting_parameters={
            "tailored_resume": {
                "templateId": "classic_single",
                "maxPages": 2,
            },
            "cover_letter": {"pageSize": "A4"},
        },
        user_preferences="Keep it concise.",
    )

    with sessions() as db:
        snapshot = build_generation_run_snapshot(
            db,
            application_id="application-1",
            start=start,
            settings=settings,
            now=datetime(2026, 9, 13, tzinfo=UTC),
        )

    settings.ai_backend_mode = "openai_api"
    settings.openclaw_assistant_model = "changed-after-start"

    assert snapshot.execution.backend == "openclaw_codex"
    assert snapshot.execution.model == "openai/gpt-worker"
    assert snapshot.request.application.revision == 4
    assert snapshot.request.vacancy.revision == 7
    assert snapshot.request.master_profile_version.version == 2
    assert snapshot.request.master_profile_version.content_sha256
    assert [item.document_type for item in snapshot.templates] == [
        "tailored_resume",
        "cover_letter",
    ]
    assert snapshot.templates[0].template_version == "1.0.1"
    assert snapshot.templates[0].content_sha256
    assert snapshot.templates[1].content_sha256
    assert len(snapshot.fingerprint) == 64
    serialized = snapshot.model_dump(mode="json", by_alias=True)
    assert "api_key" not in str(serialized).lower()


def test_generation_snapshot_fingerprint_is_stable_for_identical_inputs(
    sessions,
) -> None:
    seed_complete_sources(sessions)
    start = GenerationStartRequest(
        document_types=("tailored_resume",),
        language="English",
        formatting_parameters={"tailored_resume": {"templateId": "classic_single"}},
        user_preferences="",
    )
    now = datetime(2026, 9, 13, tzinfo=UTC)

    with sessions() as db:
        first = build_generation_run_snapshot(
            db,
            application_id="application-1",
            start=start,
            settings=runtime_settings(),
            now=now,
        )
        second = build_generation_run_snapshot(
            db,
            application_id="application-1",
            start=start,
            settings=runtime_settings(),
            now=now,
        )

    assert first.fingerprint == second.fingerprint
