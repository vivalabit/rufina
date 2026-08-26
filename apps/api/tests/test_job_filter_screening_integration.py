import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.models.applications  # noqa: F401
from app.core.database import Base
from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.models.job_filter import JobFilterSettings, JobFilterSettingsRecord
from app.models.job_search import (
    JobSearchConfigRecord,
    JobSearchRunRecord,
    ScreeningConfig,
    normalize_job_search_config,
)
from app.models.parsers import ParserSearchResponse
from app.services.job_screening import (
    CompactScreeningJob,
    build_job_screening_prompt,
    deterministic_posting_age_decision,
)
from app.services.job_screening_store import build_screening_config_hash
from app.services.job_search_execution import (
    JobSearchExecutionError,
    ScreeningConfigConflict,
    effective_screening_config,
    execute_job_search,
)
from app.services.vacancy_search import VacancySearchRunResult


class EmptyRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, **_kwargs) -> VacancySearchRunResult:
        self.calls += 1
        return VacancySearchRunResult(
            jobs=[],
            source_results={
                "linkedin": ParserSearchResponse(
                    parser="linkedin",
                    status="completed",
                    search_url="https://example.test/linkedin",
                    jobs=[],
                )
            },
            source_errors={},
        )


def test_disabled_and_enabled_empty_filter_preserve_legacy_policy_and_hash() -> None:
    config = search_config(
        screening={
            "enabled": False,
            "targetRoles": [],
            "allowedSeniority": [],
            "excludedSeniority": [],
            "hardRules": [],
        }
    )
    legacy = effective_screening_config(config, screening_required=False)

    disabled = effective_screening_config(
        config,
        screening_required=False,
        job_filter=JobFilterSettings(
            enabled=False,
            targetTechnologies=["Python"],
        ),
    )
    enabled_empty = effective_screening_config(
        config,
        screening_required=False,
        job_filter=JobFilterSettings(enabled=True),
    )

    legacy_snapshot = legacy.model_dump(by_alias=True, exclude_none=True)
    assert disabled.model_dump(by_alias=True, exclude_none=True) == legacy_snapshot
    assert enabled_empty.model_dump(by_alias=True, exclude_none=True) == legacy_snapshot
    assert build_screening_config_hash(disabled) == build_screening_config_hash(legacy)
    assert build_screening_config_hash(enabled_empty) == build_screening_config_hash(legacy)
    assert legacy.enabled is False
    assert enabled_empty.enabled is False
    assert "targetTechnologies" not in legacy_snapshot
    assert "excludedTechnologies" not in legacy_snapshot


def test_enabled_filter_merges_seniority_and_adds_user_technologies() -> None:
    config = search_config(
        screening={
            "enabled": True,
            "targetRoles": ["Backend Engineer"],
            "allowedSeniority": ["mid", "senior"],
            "excludedSeniority": ["director"],
            "hardRules": [],
        }
    )

    effective = effective_screening_config(
        config,
        screening_required=False,
        job_filter=JobFilterSettings(
            enabled=True,
            allowedSeniority=["senior", "lead"],
            excludedSeniority=["junior"],
            targetTechnologies=["Python", "FastAPI"],
            excludedTechnologies=["C#", ".NET"],
        ),
    )

    assert effective.enabled is True
    assert effective.allowed_seniority == ["senior"]
    assert effective.excluded_seniority == ["director", "junior"]
    assert effective.target_technologies == ["Python", "FastAPI"]
    assert effective.excluded_technologies == ["C#", ".NET"]


def test_disabled_criteria_are_preserved_but_not_applied() -> None:
    config = search_config()
    effective = effective_screening_config(
        config,
        screening_required=False,
        job_filter=JobFilterSettings(
            enabled=True,
            seniorityEnabled=False,
            allowedSeniority=["senior"],
            technologyStackEnabled=False,
            targetTechnologies=["Python"],
            postingAgeEnabled=True,
            maxPostingAgeDays=7,
        ),
        now=datetime(2026, 8, 27, 12, tzinfo=UTC),
    )

    assert effective.enabled is True
    assert effective.allowed_seniority == []
    assert effective.target_technologies is None
    assert effective.posted_after == "2026-08-20T12:00:00+00:00"
    assert effective.max_posting_age_days == 7


def test_posting_age_filter_rejects_old_vacancies_and_keeps_recent_ones() -> None:
    config = ScreeningConfig(
        enabled=True,
        postedAfter="2026-08-20T12:00:00+00:00",
        maxPostingAgeDays=7,
    )

    old = deterministic_posting_age_decision(
        config,
        CompactScreeningJob(id="old", postedAt="2026-08-19"),
        job_id="old",
    )
    recent = deterministic_posting_age_decision(
        config,
        CompactScreeningJob(id="recent", postedAt="2 days ago"),
        job_id="recent",
    )

    assert old is not None and old.decision == "reject"
    assert old.reason_code == "posting_too_old"
    assert recent is not None and recent.decision == "keep"
    assert recent.reason_code == "posting_age_match"


def test_non_overlapping_allowed_seniority_is_an_explicit_conflict() -> None:
    config = search_config(
        screening={
            "enabled": True,
            "allowedSeniority": ["junior"],
        }
    )

    with pytest.raises(
        ScreeningConfigConflict,
        match="incompatible allowed seniority levels",
    ):
        effective_screening_config(
            config,
            screening_required=False,
            job_filter=JobFilterSettings(
                enabled=True,
                allowedSeniority=["senior"],
            ),
        )


def test_prompt_defines_primary_or_required_technology_semantics() -> None:
    prompt = build_job_screening_prompt(
        ScreeningConfig(
            enabled=True,
            targetTechnologies=["Python", "FastAPI"],
            excludedTechnologies=["C#"],
        ),
        [
            CompactScreeningJob(
                id="job-1",
                title="Backend Engineer",
                description="Build services with Python and FastAPI",
            )
        ],
    )
    payload = json.loads(prompt.split("Input JSON:\n", 1)[1])

    assert payload["screeningConfig"]["targetTechnologies"] == [
        "Python",
        "FastAPI",
    ]
    assert payload["screeningConfig"]["excludedTechnologies"] == ["C#"]
    assert "targetTechnologies is an ANY-match allow-list" in prompt
    assert "primary to the role or explicitly required" in prompt
    assert "incidental, optional, nice-to-have, legacy" in prompt
    assert "excluded technology takes precedence" in prompt


def test_manual_run_snapshots_global_filter_and_combined_policy(tmp_path) -> None:
    sessions = create_sessions(tmp_path / "manual-filter-snapshot.sqlite")
    owner_id = "manual-filter-owner"
    runner = EmptyRunner()

    with sessions() as db:
        config = add_search_config(db, owner_id=owner_id)
        db.add(
            JobFilterSettingsRecord(
                owner_id=owner_id,
                data=filter_snapshot(
                    target_technologies=["Python"],
                    excluded_technologies=["C#"],
                ),
            )
        )
        db.commit()

        owner_token = current_owner_id.set(owner_id)
        try:
            result = execute_job_search(
                db,
                schedule=None,
                config=config,
                runner=runner,
                settings=filter_test_settings(),
                run_type="manual",
                sources=["linkedin"],
            )
            snapshot = result.run.config_snapshot
        finally:
            current_owner_id.reset(owner_token)

    assert runner.calls == 1
    assert snapshot["jobFilter"] == filter_snapshot(
        target_technologies=["Python"],
        excluded_technologies=["C#"],
    )
    effective = snapshot["filters"]["screening"]
    assert effective["enabled"] is True
    assert effective["targetTechnologies"] == ["Python"]
    assert effective["excludedTechnologies"] == ["C#"]


def test_conflicting_filter_fails_before_parser_with_clear_detail(tmp_path) -> None:
    sessions = create_sessions(tmp_path / "filter-conflict.sqlite")
    owner_id = "filter-conflict-owner"
    runner = EmptyRunner()

    with sessions() as db:
        config = add_search_config(
            db,
            owner_id=owner_id,
            screening={
                "enabled": True,
                "allowedSeniority": ["junior"],
            },
        )
        db.add(
            JobFilterSettingsRecord(
                owner_id=owner_id,
                data=filter_snapshot(allowed_seniority=["senior"]),
            )
        )
        db.commit()

        owner_token = current_owner_id.set(owner_id)
        try:
            with pytest.raises(
                JobSearchExecutionError,
                match="incompatible allowed seniority levels",
            ):
                execute_job_search(
                    db,
                    schedule=None,
                    config=config,
                    runner=runner,
                    settings=filter_test_settings(),
                    run_type="manual",
                    sources=["linkedin"],
                )
            run = db.scalar(select(JobSearchRunRecord))
        finally:
            current_owner_id.reset(owner_token)

    assert runner.calls == 0
    assert run is not None
    assert run.status == "failed"
    assert "incompatible allowed seniority levels" in run.source_errors["config"]


def search_config(
    *,
    screening: dict[str, object] | None = None,
):
    return normalize_job_search_config(
        {
            "schemaVersion": 2,
            "search": {
                "keywords": "Backend Engineer",
                "location": "Zurich",
            },
            "screening": screening or {},
        }
    )


def create_sessions(database_path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def add_search_config(
    db: Session,
    *,
    owner_id: str,
    screening: dict[str, object] | None = None,
) -> JobSearchConfigRecord:
    config = JobSearchConfigRecord(
        owner_id=owner_id,
        name="Filter integration search",
        filters={
            "schemaVersion": 2,
            "search": {
                "keywords": "Backend Engineer",
                "location": "Zurich",
            },
            "screening": screening or {"enabled": False},
        },
    )
    db.add(config)
    db.flush()
    return config


def filter_snapshot(
    *,
    allowed_seniority: list[str] | None = None,
    target_technologies: list[str] | None = None,
    excluded_technologies: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "enabled": True,
        "allowedSeniority": allowed_seniority or [],
        "excludedSeniority": [],
        "targetTechnologies": target_technologies or [],
        "excludedTechnologies": excluded_technologies or [],
    }


def filter_test_settings() -> Settings:
    return Settings(app_env="local", database_url="sqlite://")
