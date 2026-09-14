from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.identity import current_owner_id
from app.models.jobs import StoredJobRecord
from app.services.job_screening import JOB_SCREENING_PROMPT_VERSION
from app.services.job_screening_store import (
    build_screening_cache_config_hash,
    build_screening_config_hash,
    build_screening_vacancy_hash,
    latest_screening_decision,
    persist_screening_decision,
)


def screening_config() -> dict[str, object]:
    return {
        "enabled": True,
        "targetRoles": ["Software Engineer"],
        "allowedSeniority": ["mid", "senior"],
        "excludedSeniority": ["director"],
        "hardRules": [
            {
                "field": "location",
                "operator": "equals",
                "value": "Zurich",
                "enabled": True,
            }
        ],
    }


def vacancy(**overrides: object) -> dict[str, object]:
    return {
        "id": "job-1",
        "title": "Backend Engineer",
        "company": "Example AG",
        "location": "Zurich",
        "description": "Build APIs",
        "source": "linkedin",
        **overrides,
    }


def rejected_decision() -> dict[str, object]:
    return {
        "id": "job-1",
        "decision": "reject",
        "reasonCode": "hard_rule_mismatch",
        "matchedRuleIds": ["rule-1"],
        "reason": "The vacancy is outside the configured location",
    }


def test_persist_rejected_decision_does_not_create_stored_job() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    owner_token = current_owner_id.set("screening-owner")
    try:
        with Session(engine) as db:
            record = persist_screening_decision(
                db,
                vacancy_hash=build_screening_vacancy_hash(vacancy()),
                config_hash=build_screening_config_hash(screening_config()),
                decision=rejected_decision(),
                model="openai/gpt-5-mini",
                prompt_version=JOB_SCREENING_PROMPT_VERSION,
                title="Backend Engineer",
                company="Example AG",
                source_url="https://example.test/jobs/1",
                created_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
            )
            db.commit()
            db.refresh(record)

            assert record.owner_id == "screening-owner"
            assert record.decision == "reject"
            assert record.reason_code == "hard_rule_mismatch"
            assert record.matched_rule_ids == ["rule-1"]
            assert record.model == "openai/gpt-5-mini"
            assert record.prompt_version == JOB_SCREENING_PROMPT_VERSION
            assert record.title == "Backend Engineer"
            assert record.company == "Example AG"
            assert record.source_url == "https://example.test/jobs/1"
            assert db.scalars(select(StoredJobRecord)).all() == []
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


def test_latest_screening_decision_uses_full_cache_identity_and_owner() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    vacancy_hash = build_screening_vacancy_hash(vacancy())
    config_hash = build_screening_config_hash(screening_config())
    older = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)
    newer = older + timedelta(minutes=5)

    owner_token = current_owner_id.set("owner-a")
    try:
        with Session(engine) as db:
            for created_at, reason in (
                (older, "Older decision"),
                (newer, "Newer decision"),
            ):
                persist_screening_decision(
                    db,
                    vacancy_hash=vacancy_hash,
                    config_hash=config_hash,
                    decision={
                        **rejected_decision(),
                        "reason": reason,
                    },
                    model="openai/gpt-5-mini",
                    prompt_version=JOB_SCREENING_PROMPT_VERSION,
                    title="Backend Engineer",
                    company="Example AG",
                    source_url="https://example.test/jobs/1",
                    created_at=created_at,
                )
            db.commit()
            cached = latest_screening_decision(
                db,
                vacancy_hash=vacancy_hash,
                config_hash=config_hash,
                model="openai/gpt-5-mini",
                prompt_version=JOB_SCREENING_PROMPT_VERSION,
            )
            assert cached is not None
            assert cached.reason == "Newer decision"

        current_owner_id.reset(owner_token)
        owner_token = current_owner_id.set("owner-b")
        with Session(engine) as db:
            assert latest_screening_decision(
                db,
                vacancy_hash=vacancy_hash,
                config_hash=config_hash,
                model="openai/gpt-5-mini",
                prompt_version=JOB_SCREENING_PROMPT_VERSION,
            ) is None
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


def test_screening_hashes_are_deterministic_and_input_sensitive() -> None:
    assert build_screening_config_hash(screening_config()) == (
        build_screening_config_hash(screening_config())
    )
    assert build_screening_vacancy_hash(vacancy()) == (
        build_screening_vacancy_hash(vacancy())
    )
    assert build_screening_config_hash(screening_config()) != (
        build_screening_config_hash(
            {
                **screening_config(),
                "targetRoles": ["Product Manager"],
            }
        )
    )
    assert build_screening_vacancy_hash(vacancy()) != (
        build_screening_vacancy_hash(
            vacancy(description="Different description")
        )
    )


def test_rolling_posting_age_hash_reuses_unchanged_rules_across_runs() -> None:
    earlier = {
        **screening_config(),
        "postedAfter": "2026-09-07T12:00:00+00:00",
        "maxPostingAgeDays": 7,
    }
    later = {**earlier, "postedAfter": "2026-09-07T12:01:00+00:00"}

    assert build_screening_config_hash(earlier, rolling_posting_age=True) == (
        build_screening_config_hash(later, rolling_posting_age=True)
    )
    # Manual absolute cutoffs remain sensitive to their precise timestamp.
    assert build_screening_config_hash(earlier) != build_screening_config_hash(later)
    assert build_screening_config_hash(earlier, rolling_posting_age=True) != (
        build_screening_config_hash(earlier)
    )
    assert earlier["postedAfter"] == "2026-09-07T12:00:00+00:00"


@pytest.mark.parametrize(
    "overrides",
    [
        {"maxPostingAgeDays": 30},
        {"targetRoles": ["Product Manager"]},
        {"excludedRoles": ["Support Engineer"]},
        {"allowedSeniority": ["senior"]},
        {"targetTechnologies": ["Python"]},
        {"excludedTechnologies": ["Java"]},
        {"hardRules": []},
        {"enabled": False},
    ],
)
def test_rolling_posting_age_hash_keeps_other_rules_sensitive(
    overrides: dict[str, object],
) -> None:
    config = {
        **screening_config(),
        "postedAfter": "2026-09-07T12:00:00+00:00",
        "maxPostingAgeDays": 7,
    }
    assert build_screening_config_hash(config, rolling_posting_age=True) != (
        build_screening_config_hash(
            {**config, **overrides},
            rolling_posting_age=True,
        )
    )


def test_rolling_posting_age_opt_in_does_not_change_configs_without_age() -> None:
    assert build_screening_config_hash(screening_config(), rolling_posting_age=True) == (
        build_screening_config_hash(screening_config())
    )


@pytest.mark.parametrize("posted_at", ["2026-09-14T10:00:00+00:00", "2026-09-14"])
def test_parseable_dates_can_use_rolling_cache_identity(posted_at: str) -> None:
    earlier = {
        **screening_config(),
        "postedAfter": "2026-09-07T12:00:00+00:00",
        "maxPostingAgeDays": 7,
    }
    later = {**earlier, "postedAfter": "2026-09-07T12:01:00+00:00"}
    job = vacancy(postedAt=posted_at)
    assert build_screening_cache_config_hash(earlier, job, rolling_posting_age=True) == (
        build_screening_cache_config_hash(later, job, rolling_posting_age=True)
    )
    assert build_screening_cache_config_hash(earlier, job) != (
        build_screening_cache_config_hash(later, job)
    )


@pytest.mark.parametrize("posted_at", [None, "", "published recently", "today", "2 days ago"])
def test_unknown_dates_keep_exact_cutoff_cache_identity(posted_at: str | None) -> None:
    earlier = {
        **screening_config(),
        "postedAfter": "2026-09-07T12:00:00+00:00",
        "maxPostingAgeDays": 7,
    }
    later = {**earlier, "postedAfter": "2026-09-07T12:01:00+00:00"}
    job = vacancy(postedAt=posted_at)
    assert build_screening_cache_config_hash(earlier, job, rolling_posting_age=True) == (
        build_screening_config_hash(earlier)
    )
    assert build_screening_cache_config_hash(earlier, job, rolling_posting_age=True) != (
        build_screening_cache_config_hash(later, job, rolling_posting_age=True)
    )


@pytest.mark.parametrize(
    ("vacancy_hash", "config_hash"),
    [
        ("not-a-hash", "a" * 64),
        ("a" * 64, "A" * 64),
    ],
)
def test_persistence_rejects_invalid_hashes(
    vacancy_hash: str,
    config_hash: str,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db, pytest.raises(ValueError, match="SHA-256"):
            persist_screening_decision(
                db,
                vacancy_hash=vacancy_hash,
                config_hash=config_hash,
                decision=rejected_decision(),
                model="openai/gpt-5-mini",
                prompt_version=JOB_SCREENING_PROMPT_VERSION,
                title="Backend Engineer",
                company="Example AG",
                source_url="https://example.test/jobs/1",
            )
    finally:
        engine.dispose()
