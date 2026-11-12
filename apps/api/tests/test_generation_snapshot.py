from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.generation import GenerationStartRequest
from app.services.document_rendering import (
    COVER_LETTER_TEMPLATE_VERSION,
    DOCUMENT_TEMPLATE_ORDER,
    resolve_document_template,
)
from app.services.generation_input import GenerationInputError
from app.services.generation_snapshot import (
    build_generation_run_snapshot,
    run_created_at,
    run_request,
    run_template_id,
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


def _start(document_types=("tailored_resume",), formatting=None) -> GenerationStartRequest:
    return GenerationStartRequest(
        documentTypes=document_types,
        language="de-CH",
        formattingParameters=formatting or {},
        userPreferences="Keep it concise.",
    )


def _snapshot(sessions, start: GenerationStartRequest, now: datetime | None = None):
    with sessions() as db:
        return build_generation_run_snapshot(
            db,
            application_id="application-1",
            start=start,
            settings=runtime_settings(),
            now=now,
        )


def test_generation_snapshot_pins_sources_templates_and_backend(sessions) -> None:
    seed_complete_sources(sessions)

    snapshot = _snapshot(sessions, _start(("tailored_resume", "cover_letter")))

    assert snapshot.execution.backend == "openclaw_codex"
    assert snapshot.execution.model == "openai/gpt-worker"
    assert snapshot.execution.parsing_model == "openai/gpt-6-luna"
    assert snapshot.request.application.revision == 4
    assert snapshot.request.vacancy.revision == 7
    assert snapshot.request.master_profile_version.version == 2
    assert snapshot.request.master_profile_version.content_sha256
    assert [item.document_type for item in snapshot.templates] == [
        "tailored_resume",
        "cover_letter",
    ]
    default = resolve_document_template(None)
    resume, letter = snapshot.templates
    assert resume.template_id == default.id == "swiss_classic"
    assert resume.template_version == default.version
    assert resume.content_sha256 == default.design_sha256
    assert resume.renderer == letter.renderer == "chromium"
    assert letter.template_id == "swiss_classic"
    assert letter.template_version == COVER_LETTER_TEMPLATE_VERSION
    assert len(letter.content_sha256) == 64 and letter.content_sha256 != resume.content_sha256
    assert len(snapshot.fingerprint) == 64
    serialized = snapshot.model_dump(mode="json", by_alias=True)
    assert "api_key" not in str(serialized).lower()


def test_generation_snapshot_fingerprint_is_stable_for_identical_inputs(sessions) -> None:
    seed_complete_sources(sessions)
    now = datetime(2026, 9, 13, tzinfo=UTC)

    first = _snapshot(sessions, _start(), now)
    second = _snapshot(sessions, _start(), now)
    other = _snapshot(
        sessions, _start(formatting={"tailored_resume": {"templateId": "modern_single"}}), now
    )

    assert first.fingerprint == second.fingerprint
    assert other.fingerprint != first.fingerprint


@pytest.mark.parametrize("template_id", DOCUMENT_TEMPLATE_ORDER)
def test_every_gallery_template_can_start_a_run(sessions, template_id: str) -> None:
    seed_complete_sources(sessions)

    snapshot = _snapshot(
        sessions, _start(formatting={"tailored_resume": {"templateId": template_id}})
    )

    assert snapshot.templates[0].template_id == template_id


@pytest.mark.parametrize(
    ("saved", "expected"),
    [("roman", "swiss_classic"), ("moderncv_banking", "modern_single")],
)
def test_template_ids_of_the_earlier_generator_map_to_gallery_templates(
    sessions, saved: str, expected: str
) -> None:
    seed_complete_sources(sessions)

    snapshot = _snapshot(sessions, _start(formatting={"tailored_resume": {"templateId": saved}}))

    assert snapshot.templates[0].template_id == expected


@pytest.mark.parametrize("template_id", ["unknown", "../../outside", 42])
def test_generation_snapshot_rejects_unsupported_templates(sessions, template_id) -> None:
    seed_complete_sources(sessions)

    with pytest.raises(GenerationInputError) as failure:
        _snapshot(sessions, _start(formatting={"tailored_resume": {"templateId": template_id}}))

    assert failure.value.code == "document_template_unsupported"


@pytest.mark.parametrize(
    ("document_types", "formatting"),
    [
        (("tailored_resume", "cover_letter"), {"tailored_resume": {"templateId": "modern_single"}}),
        (("tailored_resume", "cover_letter"), {"cover_letter": {"templateId": "modern_single"}}),
        (("cover_letter",), {"cover_letter": {"templateId": "modern_single"}}),
    ],
)
def test_document_family_is_shared_even_when_only_one_selection_is_provided(
    sessions, document_types, formatting
) -> None:
    seed_complete_sources(sessions)

    snapshot = _snapshot(sessions, _start(document_types, formatting))

    assert {item.template_id for item in snapshot.templates} == {"modern_single"}


def test_new_runs_reject_mismatched_document_families(sessions) -> None:
    seed_complete_sources(sessions)

    with pytest.raises(GenerationInputError) as failure:
        _snapshot(
            sessions,
            _start(
                ("tailored_resume", "cover_letter"),
                {
                    "tailored_resume": {"templateId": "swiss_classic"},
                    "cover_letter": {"templateId": "modern_single"},
                },
            ),
        )

    assert failure.value.code == "document_template_mismatch"


def test_persisted_snapshots_of_earlier_versions_stay_readable(sessions) -> None:
    seed_complete_sources(sessions)
    current = _snapshot(sessions, _start()).model_dump(mode="json", by_alias=True)
    # What the LaTeX-based pipeline stored for a run.
    legacy = {
        **current,
        "execution": {**current["execution"], "upstream_sha": "c7bd494", "instruction_version": "3"},
        "templates": [
            {
                "documentType": "tailored_resume",
                "templateId": "roman",
                "templateVersion": "1.0.2",
                "contentSha256": "0" * 64,
                "renderer": "lualatex",
            }
        ],
    }

    assert run_request(legacy).vacancy.id == "vacancy-1"
    assert run_template_id(legacy) == "roman"
    assert run_created_at(legacy) == datetime.fromisoformat(current["createdAt"])
