from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models.applications  # noqa: F401
from app.core.database import Base
from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.models.job_filter import JobFilterSettings
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.job_search import ScreeningConfig, normalize_job_search_config
from app.models.parsers import ParsedJob
from app.services import job_screening, job_search_execution
from app.services.job_screening import CompactScreeningJob, build_job_screening_prompt
from app.services.job_screening_store import build_screening_config_hash
from app.services.job_search_execution import (
    NewJobCandidate,
    effective_screening_config,
    screen_new_job_candidates,
)


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    owner_token = current_owner_id.set("canton-test")
    try:
        with Session(engine) as session:
            yield session
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


def candidate(location: str, *, title: str = "Engineer", posted_at: str | None = None):
    return NewJobCandidate(
        job_id="canton-job",
        job=ParsedJob(
            source="jobs_ch",
            title=title,
            company="Example AG",
            location=location,
            posted_at=posted_at,
            url="https://example.test/canton-job",
        ),
    )


def screen(db: Session, job: NewJobCandidate, config: ScreeningConfig):
    return screen_new_job_candidates(
        db,
        candidates=[job],
        screening_config=config,
        settings=Settings(app_env="local", database_url="sqlite://", auto_ai_match_enabled=False),
    )


@pytest.mark.parametrize(
    ("location", "decision", "reason"),
    [
        ("Stäfa", "keep", "canton_match"),
        ("Staefa, Switzerland", "keep", "canton_match"),
        ("Stafa", "keep", "canton_match"),
        ("8712 Stäfa", "keep", "canton_match"),
        ("Bern", "reject", "canton_mismatch"),
        ("Bern / Stäfa", "keep", "canton_match"),
        ("Switzerland", "keep", "canton_unknown"),
        ("Remote", "keep", "canton_unknown"),
        ("Unknown location", "keep", "canton_unknown"),
        ("", "keep", "canton_unknown"),
    ],
)
def test_canton_filter_resolves_places_and_keeps_unknown_without_ai(
    db: Session, monkeypatch: pytest.MonkeyPatch, location: str, decision: str, reason: str,
) -> None:
    def unexpected_ai(_settings):
        pytest.fail("A canton-only filter must not need AI")

    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", unexpected_ai)
    result = screen(db, candidate(location), ScreeningConfig(enabled=True, allowedCantons=["ZH"]))

    assert result.decisions[0].decision == decision
    assert result.decisions[0].reason_code == reason
    assert result.jobs_screening_ai_calls == 0
    assert len(result.keep) == (decision == "keep")
    assert db.scalar(select(JobScreeningDecisionRecord)).reason_code == reason


@pytest.mark.parametrize(
    ("enabled", "canton_enabled", "cantons", "active"),
    [(True, True, ["ZH"], True), (False, True, ["ZH"], False),
     (True, False, ["ZH"], False), (True, True, [], False)],
)
def test_global_and_canton_switches_preserve_legacy_screening(
    enabled: bool, canton_enabled: bool, cantons: list[str], active: bool,
) -> None:
    search = normalize_job_search_config({"schemaVersion": 2, "search": {}, "screening": {}})
    legacy = effective_screening_config(search, screening_required=False)
    effective = effective_screening_config(
        search,
        screening_required=False,
        job_filter=JobFilterSettings(
            enabled=enabled, cantonEnabled=canton_enabled, allowedCantons=cantons,
        ),
    )

    assert effective.enabled is active
    assert effective.allowed_cantons == (["ZH"] if active else None)
    assert (build_screening_config_hash(effective) != build_screening_config_hash(legacy)) is active


@pytest.mark.parametrize(
    ("location", "posted_at", "expected_reason"),
    [("Bern", "2026-10-28", "canton_mismatch"),
     ("Stäfa", "2026-10-01", "posting_too_old"),
     ("Stäfa", "2026-10-28", "posting_age_match"),
     ("Unknown location", "2026-10-28", "posting_age_match")],
)
def test_canton_and_posting_age_both_apply(
    db: Session, location: str, posted_at: str, expected_reason: str,
) -> None:
    result = screen(
        db, candidate(location, posted_at=posted_at),
        ScreeningConfig(
            enabled=True, allowedCantons=["ZH"],
            postedAfter="2026-10-22T12:00:00+00:00", maxPostingAgeDays=7,
        ),
    )

    assert result.decisions[0].reason_code == expected_reason
    assert result.jobs_screening_ai_calls == 0


def test_matching_canton_still_applies_seniority(db: Session) -> None:
    result = screen(
        db, candidate("Stäfa", title="Senior Engineer"),
        ScreeningConfig(enabled=True, allowedCantons=["ZH"], excludedSeniority=["senior"]),
    )

    assert result.decisions[0].reason_code == "seniority_mismatch"
    assert result.keep == []


@pytest.mark.parametrize("location", ["Stäfa", "Unknown location"])
def test_other_criteria_continue_without_canton_in_ai_config(
    db: Session, monkeypatch: pytest.MonkeyPatch, location: str,
) -> None:
    class Facade:
        def screen(self, config, jobs):
            assert config.allowed_cantons is None
            assert config.target_technologies == ["Python"]
            return [{
                "id": jobs[0]["id"], "decision": "reject", "reasonCode": "technology_mismatch",
                "reason": "Python is not used", "matchedRuleIds": [],
            }]

    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: Facade())
    config = ScreeningConfig(enabled=True, allowedCantons=["ZH"], targetTechnologies=["Python"])
    result = screen(db, candidate(location), config)

    assert result.decisions[0].reason_code == "technology_mismatch"
    assert result.jobs_screening_ai_calls == 1
    assert "allowedCantons" not in build_job_screening_prompt(
        config, [CompactScreeningJob(id="canton-job", location=location)],
    )


def test_changed_location_evidence_does_not_reuse_old_canton_rejection(
    db: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ScreeningConfig(enabled=True, allowedCantons=["ZH"], targetTechnologies=["Python"])
    job = candidate("Bern")
    rejected = screen(db, job, config)
    db.commit()
    assert rejected.decisions[0].reason_code == "canton_mismatch"

    monkeypatch.setattr(job_screening, "resolve_swiss_cantons", lambda _location: set())

    class Facade:
        def screen(self, _config, jobs):
            return [{
                "id": jobs[0]["id"], "decision": "keep", "reasonCode": "technology_match",
                "reason": "Python is used", "matchedRuleIds": [],
            }]

    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: Facade())
    reconsidered = screen(db, job, config)

    assert reconsidered.decisions[0].decision == "keep"
    assert reconsidered.jobs_screening_ai_calls == 1
