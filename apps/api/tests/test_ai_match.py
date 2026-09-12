import hashlib
import json
import subprocess
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.models.profile import (
    CandidateMatchSnapshotRecord,
    ProfileFileRecord,
    ProfilePayload,
    ProfileRecord,
)
from app.services import ai_match as ai_match_service
from app.services.ai_backend import AIRequest, AIResult, AIUsage, OpenAIAPIBackend
from app.services.ai_match import (
    OpenClawAiMatchError,
    OpenClawAiMatchPayload,
    build_cache_key,
    build_candidate_snapshot,
    build_job_snapshot,
    build_openclaw_ai_match_prompt,
    build_profile_files_fingerprint,
    calculate_ai_matches,
    create_vacancy_matching_ai_facade,
    extract_openclaw_ai_match_payload,
    infer_seniority,
    parse_number,
    score_with_openclaw,
)
from app.services.ai_privacy import record_ai_activity
from app.services.candidate_snapshot import (
    CandidateSnapshotError,
    build_openclaw_candidate_snapshot_prompt,
    build_profile_input_hash,
    build_snapshot_with_openclaw,
    extract_openclaw_candidate_snapshot_payload,
    get_candidate_match_snapshot,
)


def persist_accepted_jobs(
    sessions: sessionmaker[Session],
    jobs: list[dict],
) -> None:
    with sessions() as db:
        db.add_all(
            [
                StoredJobRecord(
                    owner_id="local-owner",
                    id=str(job["id"]),
                    data=job,
                    status="active",
                )
                for job in jobs
            ]
        )
        db.commit()


def valid_match_result(job_id: str = "job-strict") -> dict[str, object]:
    return {
        "id": job_id,
        "score": 88,
    }


@pytest.fixture(autouse=True)
def bypass_ai_activity_tracking() -> Generator[None, None, None]:
    app.dependency_overrides[record_ai_activity] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.pop(record_ai_activity, None)


def install_openclaw_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_snapshot_with_openclaw(
        *,
        fallback_snapshot: dict,
        **_: object,
    ) -> dict:
        return fallback_snapshot

    def fake_score_with_openclaw(*, jobs: list[dict], **_: object) -> list[dict]:
        matches = []
        for job in jobs:
            title = str(job.get("title") or "")
            is_relevant = "Accounting" not in title
            matches.append(
                {
                    "id": job["id"],
                    "score": 88 if is_relevant else 34,
                }
            )
        return matches

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fake_build_snapshot_with_openclaw,
    )
    monkeypatch.setattr(
        ai_match_service,
        "score_with_openclaw",
        fake_score_with_openclaw,
    )


def test_parse_number_reads_spaced_salary_values() -> None:
    assert parse_number("CHF 100 000") == 100000
    assert parse_number("$120k - $160k") == 160000


def test_ai_match_cache_key_separates_backends() -> None:
    profile_snapshot = {"skills": ["Python"]}
    job_snapshot = {"id": "job-cache", "skills": ["Python"]}

    openclaw_key = build_cache_key(
        profile_snapshot,
        job_snapshot,
        backend="openclaw_codex",
    )
    openai_key = build_cache_key(
        profile_snapshot,
        job_snapshot,
        backend="openai_api",
    )

    assert openclaw_key != openai_key


def test_openclaw_ai_match_scores_relevant_job_higher(monkeypatch: pytest.MonkeyPatch) -> None:
    install_openclaw_fakes(monkeypatch)
    profile = ProfilePayload(
        current_role="Machine Learning Engineer",
        desired_role="Audio ML Engineer",
        location="Zurich",
        skills="Python\nPyTorch\nMachine Learning\nAudio Processing\nComputer Vision",
        job_preferences=json.dumps(
            {
                "desired_roles": ["Machine Learning Engineer"],
                "locations": ["Zurich"],
                "work_formats": ["Hybrid", "Remote"],
                "employment_types": ["Full-Time"],
                "salary_min": "100000",
                "salary_currency": "CHF",
            }
        ),
    )
    relevant_job = {
        "id": "linkedin-audio-ml",
        "title": "Audio Machine Learning Engineer",
        "company": "Google",
        "location": "Zurich",
        "type": "Full-Time",
        "salary": "Not specified",
        "posted": "LinkedIn",
        "experience": "Mid-Senior level",
        "department": "Research",
        "match": 50,
        "logo": "linkedin",
        "overview": "Build PyTorch models for audio face tracking and computer vision.",
        "responsibilities": ["Train machine learning models"],
        "requirements": ["Python", "PyTorch", "Machine Learning"],
        "skills": ["Python", "PyTorch", "Machine Learning"],
    }
    unrelated_job = {
        **relevant_job,
        "id": "linkedin-accounting",
        "title": "Accounting Manager",
        "overview": "Own accounting close and financial reporting.",
        "requirements": ["CPA", "IFRS"],
        "skills": ["Accounting", "IFRS"],
    }

    matched = calculate_ai_matches(
        profile,
        [relevant_job, unrelated_job],
        command="openclaw",
        agent_id="main",
        thinking="low",
        timeout_seconds=1,
        openclaw_enabled=True,
        openclaw_max_jobs=20,
    )

    assert matched[0]["match"] > matched[1]["match"]
    assert matched[0]["aiMatch"]["source"] == "openclaw_codex"
    assert matched[0]["aiMatch"]["backend"] == "openclaw_codex"
    assert matched[0]["aiMatch"]["score"] == 88


def test_ai_match_requires_openclaw_enabled() -> None:
    profile = ProfilePayload(
        current_role="Senior LLM Engineer",
        desired_role="GenAI Platform Engineer",
        location="Zurich",
        skills="LLM\nMLOps\nReact.js\nNode",
        job_preferences=json.dumps(
            {
                "desired_roles": ["Generative AI Engineer"],
                "locations": ["Zurich"],
                "work_formats": ["Remote"],
                "employment_types": ["Full-Time"],
                "salary_min": "130000",
                "salary_currency": "CHF",
                "seniority": ["Senior"],
            }
        ),
    )
    job = {
        "id": "linkedin-genai-platform",
        "title": "Sr. GenAI Platform Engineer",
        "company": "Open Systems",
        "location": "Zürich, Switzerland / Remote EU",
        "type": "Full-Time Remote",
        "salary": "€140k - €160k",
        "posted": "LinkedIn",
        "experience": "Experienced",
        "department": "AI Platform",
        "match": 50,
        "logo": "linkedin",
        "overview": "Build LLM products with React, Node.js, and production ML Ops workflows.",
        "responsibilities": ["Ship large language model features"],
        "requirements": ["Generative AI", "React", "Node.js", "Machine Learning Operations"],
        "skills": ["GenAI", "React", "Node.js", "MLOps"],
    }

    with pytest.raises(OpenClawAiMatchError, match="required but disabled"):
        calculate_ai_matches(
            profile,
            [job],
            command="openclaw",
            agent_id="main",
            thinking="low",
            timeout_seconds=1,
            openclaw_enabled=False,
            openclaw_max_jobs=0,
        )


def test_openclaw_prompt_treats_score_as_expert_judgment() -> None:
    profile_snapshot = {
        "roles": ["Machine Learning Engineer"],
        "skills": ["Python", "PyTorch"],
    }
    job_snapshot = build_job_snapshot(
        {
            "id": "linkedin-prompt-ml-engineer",
            "title": "Machine Learning Engineer",
            "company": "Google",
            "location": "Zurich",
            "type": "Full-Time",
            "salary": "Not specified",
            "posted": "LinkedIn",
            "experience": "Mid-Senior level",
            "department": "LinkedIn import",
            "overview": "Work on machine learning systems using Python and PyTorch.",
            "responsibilities": ["Build ML systems"],
            "requirements": ["Python", "Machine Learning"],
            "skills": ["Python", "Machine Learning"],
        }
    )

    prompt = build_openclaw_ai_match_prompt(profile_snapshot, [job_snapshot])

    assert "score as your expert judgment from 0 to 100" in prompt
    assert '{"matches":[{"id":"job id","score":0}]}' in prompt
    assert "breakdownMaxScores" not in prompt
    assert '"weights"' not in prompt


@pytest.mark.parametrize(
    "missing_path",
    ["id", "score"],
)
def test_strict_ai_match_schema_rejects_missing_score_fields(missing_path: str) -> None:
    result = valid_match_result()
    result.pop(missing_path)

    with pytest.raises(OpenClawAiMatchError, match="Field required"):
        ai_match_service.validate_openclaw_result(result, {"id": "job-strict"})


@pytest.mark.parametrize("score", [-1, 101, 1.5, "88", True, None])
def test_strict_ai_match_schema_rejects_invalid_scores(score: object) -> None:
    result = {**valid_match_result(), "score": score}
    with pytest.raises(OpenClawAiMatchError, match="score"):
        ai_match_service.validate_openclaw_result(result, {"id": "job-strict"})


@pytest.mark.parametrize("field", [
    "confidence", "breakdown", "reasons", "gaps", "explanation", "rawExplanation",
    "strengths", "weaknesses", "documentPlan", "questions", "recommendations",
    "applicationGuide", "readyToApply", "readiness", "unsupported",
])
def test_strict_ai_match_schema_forbids_analysis_fields(field: str) -> None:
    result = {**valid_match_result(), field: []}
    with pytest.raises(OpenClawAiMatchError, match="Extra inputs are not permitted"):
        ai_match_service.validate_openclaw_result(result, {"id": "job-strict"})


def test_incomplete_ai_match_is_retried_and_never_synthetically_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def fake_score_with_openclaw(**_: object) -> list[dict]:
        nonlocal attempts
        attempts += 1
        result = valid_match_result("job-retry")
        if attempts == 1:
            result.pop("score")
        return [result]

    monkeypatch.setattr(ai_match_service, "score_with_openclaw", fake_score_with_openclaw)
    job = {
        "id": "job-retry",
        "title": "Python Engineer",
        "company": "Acme",
        "requirements": ["Python"],
        "skills": ["Python"],
    }

    matched = calculate_ai_matches(
        ProfilePayload(skills="Python"),
        [job],
        command="openclaw",
        agent_id="main",
        thinking="low",
        timeout_seconds=1,
        openclaw_enabled=True,
        openclaw_max_jobs=1,
        max_attempts=2,
    )

    assert attempts == 2
    assert matched[0]["aiMatch"]["score"] == 88


def test_ai_match_reports_progress_after_each_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ai_match_service,
        "score_with_openclaw",
        lambda *, jobs, **_: [valid_match_result(job["id"]) for job in jobs],
    )
    progress: list[tuple[int, int]] = []
    jobs = [
        {
            "id": f"job-progress-{index}",
            "title": "Python Engineer",
            "company": "Acme",
            "requirements": ["Python"],
            "skills": ["Python"],
        }
        for index in range(5)
    ]

    calculate_ai_matches(
        ProfilePayload(skills="Python"),
        jobs,
        command="openclaw",
        agent_id="main",
        thinking="low",
        timeout_seconds=1,
        openclaw_enabled=True,
        openclaw_max_jobs=2,
        progress_callback=lambda processed, total: progress.append((processed, total)),
    )

    assert progress == [(2, 5), (4, 5), (5, 5)]


def test_ai_match_records_provider_neutral_backend_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ai_match_service,
        "score_with_openclaw",
        lambda **_: [valid_match_result("job-openai-api")],
    )

    matched = calculate_ai_matches(
        ProfilePayload(skills="Python"),
        [
            {
                "id": "job-openai-api",
                "title": "Python Engineer",
                "company": "Acme",
                "requirements": ["Python"],
                "skills": ["Python"],
            }
        ],
        command="openclaw",
        agent_id="main",
        thinking="low",
        timeout_seconds=1,
        openclaw_enabled=True,
        openclaw_max_jobs=1,
        backend=OpenAIAPIBackend(api_key="test-key"),
    )

    assert matched[0]["aiMatch"]["source"] == "openai_api"


def test_ai_match_passes_strict_pydantic_output_model_to_backend() -> None:
    requests: list[AIRequest] = []

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            return AIResult(
                text="",
                structured_data={"matches": [valid_match_result("job-schema")]},
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="resp_match_123",
            )

    matches = score_with_openclaw(
        profile_snapshot={},
        jobs=[
            build_job_snapshot(
                {
                    "id": "job-schema",
                    "title": "Python Engineer",
                    "company": "Rufina",
                    "skills": ["Python"],
                }
            )
        ],
        command="openclaw",
        agent_id="rufina-assistant",
        thinking="low",
        timeout_seconds=30,
        model="gpt-5.6-terra",
        backend=FakeBackend(),
    )

    assert matches[0]["id"] == "job-schema"
    assert requests[0].response_model is OpenClawAiMatchPayload


def test_ai_match_retry_includes_validation_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    correction_feedback: list[str | None] = []
    backends: list[str] = []

    def fake_score_with_openclaw(*, jobs: list[dict], **kwargs: object) -> list[dict]:
        correction_feedback.append(kwargs.get("correction_feedback"))
        backend = kwargs.get("backend")
        backends.append(backend.name if backend is not None else "")
        if len(correction_feedback) == 1:
            raise OpenClawAiMatchError("score must not exceed 100")
        return [valid_match_result(jobs[0]["id"])]

    monkeypatch.setattr(ai_match_service, "score_with_openclaw", fake_score_with_openclaw)

    calculate_ai_matches(
        ProfilePayload(skills="Python"),
        [
            {
                "id": "job-correction-retry",
                "title": "Python Engineer",
                "company": "Acme",
                "requirements": ["Python"],
                "skills": ["Python"],
            }
        ],
        command="openclaw",
        agent_id="main",
        thinking="low",
        timeout_seconds=1,
        openclaw_enabled=True,
        openclaw_max_jobs=1,
        max_attempts=2,
        backend=OpenAIAPIBackend(api_key="test-key"),
    )

    assert correction_feedback == [
        None,
        "score must not exceed 100",
    ]
    assert backends == ["openai_api", "openai_api"]


def test_matching_facade_uses_direct_api_configuration() -> None:
    facade = create_vacancy_matching_ai_facade(
        Settings(
            ai_backend_mode="openai_api",
            openai_api_key="test-key",
            openai_api_model="gpt-5.6-terra",
            openai_api_reasoning_effort="high",
            ai_match_reasoning="high",
            openai_api_timeout_seconds=75,
            openai_api_max_attempts=3,
            openai_api_retry_backoff_seconds=1.25,
            openclaw_ai_match_max_jobs=4,
        )
    )

    assert facade.backend.name == "openai_api"
    assert facade.model == "gpt-5.6-terra"
    assert facade.thinking == "high"
    assert facade.timeout_seconds == 75
    assert facade.max_attempts == 3
    assert facade.retry_backoff_seconds == 1.25
    assert facade.max_jobs == 4


def test_matching_facade_prefers_dedicated_ai_match_configuration() -> None:
    facade = create_vacancy_matching_ai_facade(
        Settings(
            ai_backend_mode="openai_api",
            openai_api_key="test-key",
            openai_api_model="gpt-default",
            openai_api_reasoning_effort="medium",
            ai_match_model="openai/gpt-dedicated",
            ai_match_reasoning="high",
            ai_match_batch_size=6,
            ai_match_timeout_seconds=180,
            ai_match_max_attempts=4,
        )
    )

    assert facade.model == "openai/gpt-dedicated"
    assert facade.thinking == "high"
    assert facade.max_jobs == 6
    assert facade.timeout_seconds == 180
    assert facade.max_attempts == 4


def test_openclaw_candidate_snapshot_reads_top_level_payloads_text() -> None:
    payload = extract_openclaw_candidate_snapshot_payload(
        json.dumps(
            {
                "payloads": [
                    {
                        "text": json.dumps(
                            {
                                "candidate": {
                                    "roles": ["Backend Developer"],
                                    "skills": ["Python", "FastAPI"],
                                }
                            }
                        )
                    }
                ]
            }
        )
    )

    assert payload["roles"] == ["Backend Developer"]
    assert payload["skills"] == ["Python", "FastAPI"]


def test_candidate_snapshot_prompt_omits_embedded_document_data() -> None:
    embedded_data = "data:application/octet-stream;base64," + ("A" * 200_000)
    profile = ProfilePayload(
        current_role="Backend Developer",
        runtime_primary_resume={
            "id": "resume-1",
            "kind": "primary_resume",
            "title": "Main CV",
            "file_name": "resume.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "content_sha256": "a" * 64,
            "size_bytes": 1234,
            "extracted_text": "Resume evidence: built reliable FastAPI services.",
            "content": embedded_data,
        },
        runtime_supporting_documents=[
            {
                "id": "certificate-1",
                "kind": "supporting_document",
                "title": "Cloud Certificate",
                "category": "Certificate",
                "file_name": "certificate.pdf",
                "content_sha256": "b" * 64,
                "size_bytes": 456,
                "content": embedded_data,
            }
        ],
    )

    prompt = build_openclaw_candidate_snapshot_prompt(profile, {"roles": []})

    assert embedded_data not in prompt
    assert "resume.docx" in prompt
    assert "built reliable FastAPI services" in prompt
    assert "Cloud Certificate" in prompt
    assert '"content":' not in prompt
    assert "resume_data_url" not in prompt
    assert len(prompt) < 20_000


def test_candidate_snapshot_hydrates_profile_file_evidence_and_hashes() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    primary_content = b"%PDF-1.4 primary resume"
    supporting_content = b"%PDF-1.4 supporting certificate"
    primary_sha = hashlib.sha256(primary_content).hexdigest()
    supporting_sha = hashlib.sha256(supporting_content).hexdigest()

    with Session(engine) as db:
        db.add_all(
            [
                ProfileFileRecord(
                    id="primary-runtime-file",
                    kind="primary_resume",
                    singleton_key="primary_resume",
                    title="Primary resume",
                    category="Resume",
                    language="English",
                    issuer="",
                    notes="",
                    file_name="resume.pdf",
                    content_type="application/pdf",
                    content_sha256=primary_sha,
                    size_bytes=len(primary_content),
                    content=primary_content,
                    extracted_text="Built FastAPI services for financial workflows.",
                ),
                ProfileFileRecord(
                    id="supporting-runtime-file",
                    kind="supporting_document",
                    singleton_key=None,
                    title="Cloud certificate",
                    category="Certificate",
                    language="English",
                    issuer="Cloud Academy",
                    notes="Advanced cloud qualification",
                    file_name="certificate.pdf",
                    content_type="application/pdf",
                    content_sha256=supporting_sha,
                    size_bytes=len(supporting_content),
                    content=supporting_content,
                    extracted_text="This text is intentionally not hydrated.",
                ),
            ]
        )
        db.commit()

        profile = ProfilePayload(current_role="Backend Engineer")
        first = get_candidate_match_snapshot(db, profile=profile)

        assert profile.runtime_primary_resume is not None
        assert profile.runtime_primary_resume["content_sha256"] == primary_sha
        assert profile.runtime_primary_resume["extracted_text"].startswith("Built FastAPI")
        assert "content" not in profile.runtime_primary_resume
        assert len(profile.runtime_supporting_documents) == 1
        assert "content" not in profile.runtime_supporting_documents[0]
        assert "extracted_text" not in profile.runtime_supporting_documents[0]
        assert "runtime_primary_resume" not in profile.model_dump()
        assert "runtime_supporting_documents" not in profile.model_dump()

        fallback = build_candidate_snapshot(profile)
        assert fallback["evidence"]["resume"] is True
        assert fallback["evidence"]["documents"] == 1
        assert fallback["evidence"]["profile_files_hash"] == (
            build_profile_files_fingerprint(profile)
        )
        primary = db.get(ProfileFileRecord, "primary-runtime-file")
        assert primary is not None
        changed_content = b"%PDF-1.4 changed resume"
        primary.content = changed_content
        primary.content_sha256 = hashlib.sha256(changed_content).hexdigest()
        primary.size_bytes = len(changed_content)
        primary.extracted_text = "Led Kubernetes platform delivery."
        db.commit()

        second = get_candidate_match_snapshot(db, profile=profile)

    assert first.profile_input_hash != second.profile_input_hash
    assert primary_content.decode() not in build_openclaw_candidate_snapshot_prompt(
        profile,
        {"roles": []},
    )
    engine.dispose()


def test_candidate_snapshot_uses_message_file(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_prompt = ""
    captured_path = ""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal captured_path, captured_prompt
        assert "--message" not in args
        message_file_index = args.index("--message-file") + 1
        captured_path = args[message_file_index]
        captured_prompt = Path(captured_path).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps({"candidate": {"roles": ["Backend Developer"]}}),
            stderr="",
        )

    monkeypatch.setattr("app.services.candidate_snapshot.subprocess.run", fake_run)

    snapshot = build_snapshot_with_openclaw(
        profile=ProfilePayload(current_role="Backend Developer"),
        fallback_snapshot={"roles": []},
        settings=Settings(openclaw_ai_match_enabled=True),
    )

    assert snapshot["roles"] == ["Backend Developer"]
    assert "Normalize this candidate" in captured_prompt
    assert not Path(captured_path).exists()


def test_candidate_snapshot_caches_successful_openclaw_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_build_snapshot_with_openclaw(*, fallback_snapshot: dict, **_: object) -> dict:
        nonlocal calls
        calls += 1
        return {
            **fallback_snapshot,
            "roles": ["Senior Python Engineer"],
            "skills": ["Python", "FastAPI"],
        }

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fake_build_snapshot_with_openclaw,
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    profile = ProfilePayload(current_role="Python Engineer", skills="Python\nFastAPI")
    settings = Settings(openclaw_ai_match_enabled=True)

    with Session(engine) as db:
        first = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=settings,
            allow_openclaw=True,
            strict_openclaw=True,
        )
        db.commit()
        second = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=settings,
            allow_openclaw=True,
            strict_openclaw=True,
        )
        records = db.query(CandidateMatchSnapshotRecord).all()

    assert calls == 1
    assert first == second
    assert first.source == "openclaw_codex"
    assert first.model == settings.openclaw_ai_match_model
    assert first.data["roles"] == ["Senior Python Engineer"]
    assert first.data["skills"] == ["Python", "FastAPI"]
    assert len(records) == 1
    assert records[0].profile_input_hash == build_profile_input_hash(profile)
    assert records[0].model == settings.openclaw_ai_match_model


def test_candidate_snapshot_records_local_fallback_and_truncated_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    internal_error = "provider unavailable: " + "x" * 400

    def fail_build_snapshot_with_openclaw(**_: object) -> dict:
        raise CandidateSnapshotError(internal_error)

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fail_build_snapshot_with_openclaw,
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    profile = ProfilePayload(current_role="Python Engineer", skills="Python\nFastAPI")

    with Session(engine) as db:
        snapshot = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=Settings(openclaw_ai_match_enabled=True),
            allow_openclaw=True,
            strict_openclaw=False,
        )
        db.commit()
        record = db.query(CandidateMatchSnapshotRecord).one()

    assert snapshot.source == "local"
    assert snapshot.model == "local"
    assert snapshot.data["roles"] == ["Python Engineer"]
    assert snapshot.data["skills"] == ["Python", "FastAPI"]
    assert snapshot.provider_error == internal_error[:240]
    assert record.source == "local"
    assert record.model == "local"
    assert record.provider_error == internal_error[:240]


def test_candidate_snapshot_records_selected_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        lambda *, fallback_snapshot, **_: {
            **fallback_snapshot,
            "roles": ["Python Engineer"],
        },
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        snapshot = get_candidate_match_snapshot(
            db,
            profile=ProfilePayload(current_role="Python Engineer"),
            settings=Settings(
                ai_backend_mode="openai_api",
                openai_api_key="test-key",
                openclaw_ai_match_enabled=True,
            ),
            allow_openclaw=True,
            strict_openclaw=True,
        )

    assert snapshot.source == "openai_api"
    assert snapshot.model == "gpt-5.6-terra"
    assert snapshot.data["roles"] == ["Python Engineer"]


def test_candidate_snapshot_cache_separates_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models: list[str] = []

    def fake_build_snapshot_with_ai(
        *,
        fallback_snapshot: dict,
        model: str,
        **_: object,
    ) -> dict:
        models.append(model)
        return {**fallback_snapshot, "roles": ["Python Engineer"]}

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fake_build_snapshot_with_ai,
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    profile = ProfilePayload(current_role="Python Engineer")
    first_settings = Settings(
        ai_backend_mode="openai_api",
        openai_api_key="test-key",
        openai_api_model="gpt-5.6-terra",
        openclaw_ai_match_enabled=True,
    )
    second_settings = Settings(
        ai_backend_mode="openai_api",
        openai_api_key="test-key",
        openai_api_model="gpt-5.6-sol",
        openclaw_ai_match_enabled=True,
    )

    with Session(engine) as db:
        first = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=first_settings,
            allow_ai=True,
            strict_ai=True,
        )
        db.commit()
        second = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=second_settings,
            allow_ai=True,
            strict_ai=True,
        )
        db.commit()
        cached_second = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=second_settings,
            allow_ai=True,
            strict_ai=True,
        )
        records = db.query(CandidateMatchSnapshotRecord).all()

    assert models == ["gpt-5.6-terra", "gpt-5.6-sol"]
    assert first.model == "gpt-5.6-terra"
    assert second.model == "gpt-5.6-sol"
    assert cached_second == second
    assert {record.model for record in records} == {
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    }


def test_openclaw_ai_match_reads_top_level_payloads_text() -> None:
    payload = extract_openclaw_ai_match_payload(
        json.dumps(
            {
                "payloads": [
                    {
                        "text": json.dumps(
                            {
                                "matches": [
                                    {
                                        "id": "linkedin-python-backend",
                                        "score": 83,
                                    }
                                ]
                            }
                        )
                    }
                ]
            }
        )
    )

    assert payload["matches"][0]["id"] == "linkedin-python-backend"
    assert payload["matches"][0]["score"] == 83


@pytest.mark.parametrize(
    "response",
    [
        lambda match: match,
        lambda match: {"matches": match},
        lambda match: {"match": match},
        lambda match: [match],
        lambda match: {"payloads": [{"text": json.dumps(match)}]},
    ],
)
def test_openclaw_ai_match_normalizes_single_job_responses(response) -> None:
    match = valid_match_result("manual-job-single")

    payload = extract_openclaw_ai_match_payload(json.dumps(response(match)))

    assert payload == {"matches": [match]}


def test_openclaw_ai_match_does_not_coerce_unrelated_payloads() -> None:
    payload = extract_openclaw_ai_match_payload(
        json.dumps({"result": {"status": "completed", "score": 91}})
    )

    assert payload == {}


def test_score_with_openclaw_accepts_single_match_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    match = valid_match_result("manual-job-single")

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(match),
            stderr="",
        )

    monkeypatch.setattr(ai_match_service.subprocess, "run", fake_run)

    results = ai_match_service.score_with_openclaw(
        profile_snapshot={"roles": ["Python Engineer"]},
        jobs=[
            build_job_snapshot(
                {
                    "id": "manual-job-single",
                    "title": "Python Engineer",
                    "company": "Acme",
                    "overview": "Build Python services.",
                    "requirements": ["Python"],
                    "skills": ["Python"],
                }
            )
        ],
        command="openclaw",
        agent_id="main",
        thinking="low",
        timeout_seconds=10,
    )

    assert results == [match]


def test_seniority_normalization_handles_common_variants() -> None:
    assert infer_seniority("Sr. Machine Learning Engineer") == "senior"
    assert infer_seniority("Mid-Senior level software engineer") == "senior"
    assert infer_seniority("Principal AI Architect") == "lead"
    assert infer_seniority("Entry level graduate developer") == "junior"


def test_ai_match_endpoint_requires_openclaw_candidate_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_build_snapshot_with_openclaw(**_: object) -> dict:
        raise CandidateSnapshotError("snapshot failed")

    def fail_score_with_openclaw(**_: object) -> list[dict]:
        raise AssertionError("job scoring should not run without an OpenClaw candidate snapshot")

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fail_build_snapshot_with_openclaw,
    )
    monkeypatch.setattr(ai_match_service, "score_with_openclaw", fail_score_with_openclaw)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_ai_match_enabled=True)
    client = TestClient(app)

    try:
        with testing_session_local() as db:
            db.add(
                ProfileRecord(
                    id="default",
                    data=ProfilePayload(
                        current_role="Machine Learning Engineer",
                        desired_role="ML Software Engineer",
                        location="Zurich",
                        skills="Python\nMachine Learning\nPyTorch",
                    ).model_dump(),
                )
            )
            db.commit()

        job = {
            "id": "linkedin-strict-snapshot",
            "company": "Google",
            "title": "Machine Learning Engineer",
            "location": "Zurich",
            "type": "Full-Time",
            "salary": "Not specified",
            "posted": "LinkedIn",
            "experience": "Mid-Senior level",
            "department": "LinkedIn import",
            "match": 50,
            "logo": "linkedin",
            "overview": "Work on machine learning systems using Python and PyTorch.",
            "responsibilities": ["Build ML systems"],
            "requirements": ["Python", "Machine Learning"],
            "skills": ["Python", "Machine Learning"],
        }

        persist_accepted_jobs(testing_session_local, [job])
        response = client.post("/jobs/ai-match", json={"jobs": [{"id": job["id"], "data": job}]})

        assert response.status_code == 502
        assert response.json()["detail"] == "snapshot failed"
        with testing_session_local() as db:
            assert db.query(CandidateMatchSnapshotRecord).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_ai_match_endpoint_ignores_cached_local_candidate_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_calls = 0
    fallback_roles_seen: list[list[str]] = []

    def fake_build_snapshot_with_openclaw(*, fallback_snapshot: dict, **_: object) -> dict:
        nonlocal snapshot_calls
        snapshot_calls += 1
        fallback_roles_seen.append(fallback_snapshot.get("roles", []))
        return {**fallback_snapshot, "roles": ["openclaw normalized role"]}

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fake_build_snapshot_with_openclaw,
    )

    def fake_score_with_openclaw(*, jobs: list[dict], **_: object) -> list[dict]:
        return [
            {
                "id": job["id"],
                "score": 87,
            }
            for job in jobs
        ]

    monkeypatch.setattr(ai_match_service, "score_with_openclaw", fake_score_with_openclaw)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_ai_match_enabled=True)
    client = TestClient(app)

    try:
        profile = ProfilePayload(
            current_role="Machine Learning Engineer",
            desired_role="ML Software Engineer",
            location="Zurich",
            skills="Python\nMachine Learning\nPyTorch",
        )
        with testing_session_local() as db:
            db.add(ProfileRecord(id="default", data=profile.model_dump()))
            db.add(
                CandidateMatchSnapshotRecord(
                    id="cached-local-snapshot",
                    profile_input_hash=build_profile_input_hash(profile),
                    profile_hash="cached-local-profile-hash",
                    matcher_version="ai-match-v1",
                    source="local",
                    data={"roles": ["cached local role"], "skills": []},
                    provider_error="previous fallback",
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()

        job = {
            "id": "linkedin-ignore-local-snapshot",
            "company": "Google",
            "title": "Machine Learning Engineer",
            "location": "Zurich",
            "type": "Full-Time",
            "salary": "Not specified",
            "posted": "LinkedIn",
            "experience": "Mid-Senior level",
            "department": "LinkedIn import",
            "match": 50,
            "logo": "linkedin",
            "overview": "Work on machine learning systems using Python and PyTorch.",
            "responsibilities": ["Build ML systems"],
            "requirements": ["Python", "Machine Learning"],
            "skills": ["Python", "Machine Learning"],
        }

        persist_accepted_jobs(testing_session_local, [job])
        response = client.post("/jobs/ai-match", json={"jobs": [{"id": job["id"], "data": job}]})

        assert response.status_code == 200
        assert snapshot_calls == 1
        assert fallback_roles_seen == [[]]
        with testing_session_local() as db:
            snapshot_sources = [
                record.source for record in db.query(CandidateMatchSnapshotRecord).all()
            ]
            assert snapshot_sources.count("local") == 1
            assert snapshot_sources.count("openclaw_codex") == 1
    finally:
        app.dependency_overrides.clear()


def test_ai_match_endpoint_rejects_out_of_range_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score_calls = 0

    def fake_build_snapshot_with_openclaw(*, fallback_snapshot: dict, **_: object) -> dict:
        return {**fallback_snapshot, "roles": ["openclaw normalized role"]}

    def fake_score_with_openclaw(*, jobs: list[dict], **_: object) -> list[dict]:
        nonlocal score_calls
        score_calls += 1
        return [
            {
                "id": jobs[0]["id"],
                "score": 101,
            }
        ]

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fake_build_snapshot_with_openclaw,
    )
    monkeypatch.setattr(ai_match_service, "score_with_openclaw", fake_score_with_openclaw)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_ai_match_enabled=True)
    client = TestClient(app)

    try:
        with testing_session_local() as db:
            db.add(
                ProfileRecord(
                    id="default",
                    data=ProfilePayload(
                        current_role="Machine Learning Engineer",
                        desired_role="ML Software Engineer",
                        location="Zurich",
                        skills="Python\nMachine Learning\nPyTorch",
                    ).model_dump(),
                )
            )
            db.commit()

        job = {
            "id": "linkedin-invalid-openclaw-score",
            "company": "Google",
            "title": "Machine Learning Engineer",
            "location": "Zurich",
            "type": "Full-Time",
            "salary": "Not specified",
            "posted": "LinkedIn",
            "experience": "Mid-Senior level",
            "department": "LinkedIn import",
            "match": 50,
            "logo": "linkedin",
            "overview": "Work on machine learning systems using Python and PyTorch.",
            "responsibilities": ["Build ML systems"],
            "requirements": ["Python", "Machine Learning"],
            "skills": ["Python", "Machine Learning"],
        }

        persist_accepted_jobs(testing_session_local, [job])
        response = client.post("/jobs/ai-match", json={"jobs": [{"id": job["id"], "data": job}]})

        assert response.status_code == 502
        assert "score: Input should be less than or equal to 100" in response.json()["detail"]
        assert score_calls == 2
        assert "score" in response.json()["detail"]
        with testing_session_local() as db:
            assert db.query(JobMatchRecord).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_ai_match_endpoint_updates_and_persists_job_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    install_openclaw_fakes(monkeypatch)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_ai_match_enabled=True)
    client = TestClient(app)

    try:
        with testing_session_local() as db:
            db.add(
                ProfileRecord(
                    id="default",
                    data=ProfilePayload(
                        current_role="Machine Learning Engineer",
                        desired_role="ML Software Engineer",
                        location="Zurich",
                        skills="Python\nMachine Learning\nPyTorch",
                        job_preferences=json.dumps(
                            {"locations": ["Zurich"], "work_formats": ["Hybrid"]}
                        ),
                    ).model_dump(),
                )
            )
            db.commit()

        job = {
            "id": "linkedin-ml-engineer",
            "company": "Google",
            "title": "XR Audio Face Tracking ML Software Engineer",
            "location": "Zurich",
            "type": "Full-Time",
            "salary": "Not specified",
            "posted": "LinkedIn",
            "experience": "Mid-Senior level",
            "department": "LinkedIn import",
            "match": 50,
            "logo": "linkedin",
            "overview": "Work on machine learning systems using Python and PyTorch.",
            "responsibilities": ["Build ML systems"],
            "requirements": ["Python", "Machine Learning"],
            "skills": ["Python", "Machine Learning"],
        }

        persist_accepted_jobs(testing_session_local, [job])
        response = client.post("/jobs/ai-match", json={"jobs": [{"id": job["id"], "data": job}]})
        read_response = client.get("/jobs")

        assert response.status_code == 200
        payload = response.json()[0]["data"]
        assert payload["match"] != 50
        assert payload["aiMatch"]["source"] == "openclaw_codex"
        assert payload["aiMatch"]["backend"] == "openclaw_codex"
        assert payload["aiMatch"]["cacheKey"]
        assert payload["aiMatch"]["score"] == payload["match"]
        assert set(payload["aiMatch"]) == {
            "version", "profileHash", "vacancyHash", "model", "backend", "promptVersion",
            "cacheKey", "source", "score", "updatedAt", "revision", "fingerprint",
        }
        assert payload["aiMatch"] == read_response.json()[0]["data"]["aiMatch"]
        cached_response = client.post(
            "/jobs/ai-match", json={"jobs": [{"id": job["id"], "data": payload}]}
        )
        assert cached_response.status_code == 200
        assert cached_response.json()[0]["data"]["aiMatch"] == payload["aiMatch"]
        assert "applicationGuide" not in payload["aiMatch"]
        assert read_response.json()[0]["data"]["aiMatch"] == payload["aiMatch"]

        with testing_session_local() as db:
            stored_job = db.get(StoredJobRecord, ("local-owner", job["id"]))
            match_records = (
                db.query(JobMatchRecord).filter(JobMatchRecord.job_id == job["id"]).all()
            )
            snapshot_records = db.query(CandidateMatchSnapshotRecord).all()
            assert stored_job is not None
            assert "aiMatch" not in stored_job.data
            assert len(snapshot_records) == 1
            assert snapshot_records[0].source == "openclaw_codex"
            assert len(match_records) == 1
            assert {record.profile_hash for record in match_records} == {
                snapshot_records[0].profile_hash
            }
            assert payload["match"] in {record.score for record in match_records}
            assert all(record.source == "openclaw_codex" for record in match_records)
            assert all(record.backend == "openclaw_codex" for record in match_records)
            assert payload["aiMatch"]["revision"] == match_records[0].id
    finally:
        app.dependency_overrides.clear()


def test_ai_match_endpoint_force_reruns_cached_openclaw_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_openclaw_fakes(monkeypatch)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_ai_match_enabled=True)
    client = TestClient(app)

    try:
        with testing_session_local() as db:
            db.add(
                ProfileRecord(
                    id="default",
                    data=ProfilePayload(
                        current_role="Machine Learning Engineer",
                        desired_role="ML Software Engineer",
                        location="Zurich",
                        skills="Python\nMachine Learning\nPyTorch",
                        job_preferences=json.dumps(
                            {"locations": ["Zurich"], "work_formats": ["Hybrid"]}
                        ),
                    ).model_dump(),
                )
            )
            db.commit()

        def build_job(job_id: str, added_at: str) -> dict[str, object]:
            return {
                "id": job_id,
                "company": "Google",
                "title": "XR Audio Face Tracking ML Software Engineer",
                "location": "Zurich",
                "type": "Full-Time",
                "salary": "Not specified",
                "posted": "LinkedIn",
                "experience": "Mid-Senior level",
                "department": "LinkedIn import",
                "match": 50,
                "logo": "linkedin",
                "overview": "Work on machine learning systems using Python and PyTorch.",
                "responsibilities": ["Build ML systems"],
                "requirements": ["Python", "Machine Learning"],
                "skills": ["Python", "Machine Learning"],
                "addedAt": added_at,
            }

        now = datetime.now(UTC)
        recent_job = build_job("linkedin-recent-force-ml-engineer", now.isoformat())
        old_job = build_job("linkedin-old-force-ml-engineer", (now - timedelta(days=3)).isoformat())

        persist_accepted_jobs(
            testing_session_local,
            [recent_job, old_job],
        )
        first_response = client.post(
            "/jobs/ai-match",
            json={
                "jobs": [
                    {"id": recent_job["id"], "data": recent_job},
                    {"id": old_job["id"], "data": old_job},
                ]
            },
        )
        assert first_response.status_code == 200
        cached_jobs = {job["id"]: job["data"] for job in first_response.json()}
        time.sleep(0.01)

        force_response = client.post(
            "/jobs/ai-match?force=true",
            json={
                "jobs": [
                    {"id": recent_job["id"], "data": cached_jobs[recent_job["id"]]},
                    {"id": old_job["id"], "data": cached_jobs[old_job["id"]]},
                ]
            },
        )

        assert force_response.status_code == 200
        forced_jobs = {job["id"]: job["data"] for job in force_response.json()}
        assert (
            forced_jobs[recent_job["id"]]["aiMatch"]["updatedAt"]
            != cached_jobs[recent_job["id"]]["aiMatch"]["updatedAt"]
        )
        assert (
            forced_jobs[old_job["id"]]["aiMatch"]["updatedAt"]
            != cached_jobs[old_job["id"]]["aiMatch"]["updatedAt"]
        )
    finally:
        app.dependency_overrides.clear()


def test_ai_match_run_endpoint_updates_status_and_persists_job_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_openclaw_fakes(monkeypatch)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_ai_match_enabled=True)
    client = TestClient(app)

    try:
        with testing_session_local() as db:
            db.add(
                ProfileRecord(
                    id="default",
                    data=ProfilePayload(
                        current_role="Machine Learning Engineer",
                        desired_role="ML Software Engineer",
                        location="Zurich",
                        skills="Python\nMachine Learning\nPyTorch",
                        job_preferences=json.dumps(
                            {"locations": ["Zurich"], "work_formats": ["Hybrid"]}
                        ),
                    ).model_dump(),
                )
            )
            db.commit()

        job = {
            "id": "linkedin-async-ml-engineer",
            "company": "Google",
            "title": "XR Audio Face Tracking ML Software Engineer",
            "location": "Zurich",
            "type": "Full-Time",
            "salary": "Not specified",
            "posted": "LinkedIn",
            "experience": "Mid-Senior level",
            "department": "LinkedIn import",
            "match": 50,
            "logo": "linkedin",
            "overview": "Work on machine learning systems using Python and PyTorch.",
            "responsibilities": ["Build ML systems"],
            "requirements": ["Python", "Machine Learning"],
            "skills": ["Python", "Machine Learning"],
        }

        persist_accepted_jobs(testing_session_local, [job])
        run_response = client.post(
            "/jobs/ai-match/run",
            json={"jobs": [{"id": job["id"], "data": job}]},
        )

        assert run_response.status_code == 202
        # The background worker may finish before TestClient returns when the scorer is mocked.
        assert run_response.json()["status"] in {"queued", "running", "completed"}

        status_payload = {}
        for _ in range(20):
            status_response = client.get("/jobs/ai-match/status")
            assert status_response.status_code == 200
            status_payload = status_response.json()
            if status_payload["status"] == "completed":
                break
            time.sleep(0.05)

        assert status_payload["status"] == "completed"
        assert status_payload["processed"] == status_payload["total"] == 1
        payload = status_payload["updatedJobs"][0]["data"]
        assert payload["match"] != 50
        assert payload["aiMatch"]["source"] == "openclaw_codex"

        read_response = client.get("/jobs")
        assert read_response.json()[0]["data"]["aiMatch"] == payload["aiMatch"]
    finally:
        app.dependency_overrides.clear()


def test_ai_match_run_endpoint_batches_openclaw_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_snapshot_with_openclaw(*, fallback_snapshot: dict, **_: object) -> dict:
        return {**fallback_snapshot, "roles": ["openclaw normalized role"]}

    batch_sizes: list[int] = []

    def fake_score_with_openclaw(*, jobs: list[dict], **_: object) -> list[dict]:
        batch_sizes.append(len(jobs))
        return [
            {
                "id": job["id"],
                "score": 82,
            }
            for job in jobs
        ]

    monkeypatch.setattr(
        "app.services.candidate_snapshot.build_snapshot_with_ai",
        fake_build_snapshot_with_openclaw,
    )
    monkeypatch.setattr(ai_match_service, "score_with_openclaw", fake_score_with_openclaw)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_ai_match_enabled=True,
        openclaw_ai_match_max_jobs=2,
    )
    client = TestClient(app)

    try:
        with testing_session_local() as db:
            db.add(
                ProfileRecord(
                    id="default",
                    data=ProfilePayload(
                        current_role="Machine Learning Engineer",
                        desired_role="ML Software Engineer",
                        location="Zurich",
                        skills="Python\nMachine Learning\nPyTorch",
                    ).model_dump(),
                )
            )
            db.commit()

        def build_job(index: int) -> dict[str, object]:
            return {
                "id": f"linkedin-async-batch-ml-engineer-{index}",
                "company": "Google",
                "title": f"Machine Learning Engineer {index}",
                "location": "Zurich",
                "type": "Full-Time",
                "salary": "Not specified",
                "posted": "LinkedIn",
                "experience": "Mid-Senior level",
                "department": "LinkedIn import",
                "match": 50,
                "logo": "linkedin",
                "overview": "Work on machine learning systems using Python and PyTorch.",
                "responsibilities": ["Build ML systems"],
                "requirements": ["Python", "Machine Learning"],
                "skills": ["Python", "Machine Learning"],
            }

        jobs = [build_job(index) for index in range(5)]
        persist_accepted_jobs(testing_session_local, jobs)
        run_response = client.post(
            "/jobs/ai-match/run",
            json={"jobs": [{"id": job["id"], "data": job} for job in jobs]},
        )

        assert run_response.status_code == 202

        status_payload = {}
        for _ in range(20):
            status_response = client.get("/jobs/ai-match/status")
            assert status_response.status_code == 200
            status_payload = status_response.json()
            if status_payload["status"] == "completed":
                break
            time.sleep(0.05)

        assert status_payload["status"] == "completed"
        assert status_payload["processed"] == status_payload["total"] == 5
        assert len(status_payload["updatedJobs"]) == 5
        assert batch_sizes == [2, 2, 1]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "score,valid",
    [(0, True), (100, True), (-1, False), (101, False), (True, False), (1.5, False)],
)
def test_match_cache_accepts_only_valid_scores(score: object, valid: bool) -> None:
    match = {"version": ai_match_service.MATCHER_VERSION, "cacheKey": "cache", "score": score}
    assert ai_match_service.is_cached_match_valid(match, "cache") is valid
    assert not ai_match_service.is_cached_match_valid(match, "different-cache")
    assert not ai_match_service.is_cached_match_valid({**match, "version": "ai-match-v4"}, "cache")


def test_match_cache_identity_tracks_all_scoring_inputs() -> None:
    candidate = {"skills": ["Python"]}
    job = build_job_snapshot({"id": "job-1", "title": "Engineer"})
    original = build_cache_key(candidate, job)
    assert original != build_cache_key({"skills": ["Java"]}, job)
    assert original != build_cache_key(candidate, {**job, "title": "Senior Engineer"})
    assert original != build_cache_key(candidate, job, model="different-model")
    assert original != build_cache_key(candidate, job, prompt_version="different-prompt")
