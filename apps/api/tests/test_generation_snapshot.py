from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.generation import GenerationStartRequest
from app.services.generation_input import GenerationInputError
from app.services.generation_resume_templates import (
    LEGACY_GENERATION_RESUME_TEMPLATE_IDS,
    resolve_generation_resume_template,
)
from app.services.generation_snapshot import (
    build_generation_run_snapshot,
    resolve_run_resume_template,
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
    assert snapshot.templates[0].template_id == "moderncv_banking"
    assert snapshot.templates[0].template_version == "1.0.0"
    assert snapshot.templates[0].content_sha256 == (
        resolve_generation_resume_template("moderncv_banking").content_sha256
    )
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


@pytest.mark.parametrize("template_id", ["moderncv_banking", "ishchenko_classic"])
def test_generation_snapshot_pins_selected_latex_template(sessions, template_id: str) -> None:
    seed_complete_sources(sessions)
    start = GenerationStartRequest(
        document_types=("tailored_resume",),
        language="English",
        formatting_parameters={"tailored_resume": {"templateId": template_id}},
        user_preferences="",
    )
    with sessions() as db:
        snapshot = build_generation_run_snapshot(
            db,
            application_id="application-1",
            start=start,
            settings=runtime_settings(),
        )
        default = build_generation_run_snapshot(
            db,
            application_id="application-1",
            start=start.model_copy(update={"formatting_parameters": {}}),
            settings=runtime_settings(),
        )

    template = resolve_run_resume_template(snapshot)
    assert template.template_id == template_id
    assert template.renderer == "lualatex"
    assert default.templates[0].template_id == "moderncv_banking"
    if template_id == "ishchenko_classic":
        assert template.content_sha256 != default.templates[0].content_sha256
        assert snapshot.fingerprint != default.fingerprint


@pytest.mark.parametrize("template_id", sorted(LEGACY_GENERATION_RESUME_TEMPLATE_IDS))
def test_saved_legacy_resume_selections_resolve_to_original_banking_renderer(template_id: str) -> None:
    assert resolve_generation_resume_template(template_id) == resolve_generation_resume_template(
        "moderncv_banking"
    )


@pytest.mark.parametrize(
    "template_id",
    ["not-a-template", "../../outside.tex", "b426540f-a1e2-4e8b-965e-10ab38b28b40", 42],
)
def test_generation_snapshot_rejects_unsupported_resume_templates(sessions, template_id) -> None:
    seed_complete_sources(sessions)
    start = GenerationStartRequest(
        document_types=("tailored_resume",),
        language="English",
        formatting_parameters={"tailored_resume": {"templateId": template_id}},
        user_preferences="",
    )
    with sessions() as db, pytest.raises(GenerationInputError) as failure:
        build_generation_run_snapshot(
            db,
            application_id="application-1",
            start=start,
            settings=runtime_settings(),
        )
    assert failure.value.code == "resume_template_unsupported"
