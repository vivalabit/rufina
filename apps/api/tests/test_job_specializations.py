import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.main import app
from app.models.job_filter import JobFilterSettings
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.job_search import ScreeningConfig, normalize_job_search_config
from app.models.parsers import ParsedJob
from app.services import job_search_execution
from app.services.job_screening import CompactScreeningJob, build_job_screening_prompt
from app.services.job_screening_store import build_screening_config_hash
from app.services.job_search_execution import (
    NewJobCandidate,
    effective_screening_config,
    screen_new_job_candidates,
)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    owner = current_owner_id.set("specialization-owner")
    try:
        yield sessionmaker(bind=engine)
    finally:
        current_owner_id.reset(owner)
        engine.dispose()


@pytest.fixture
def client(sessions) -> Iterator[TestClient]:
    def get_test_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_db, None)


def filters(specializations: list[str]) -> dict:
    return {
        "schemaVersion": 2,
        "search": {},
        "screening": {
            "enabled": True,
            "targetRoles": ["Information Technology"],
            "targetSpecializations": specializations,
        },
    }


def test_specializations_normalize_and_preserve_legacy_empty_cache_identity() -> None:
    config = ScreeningConfig(
        enabled=True,
        targetSpecializations=[" Backend ", "backend", "Data   Engineering", "Frontend"],
    )
    assert config.target_specializations == ["Backend", "Data Engineering", "Frontend"]
    assert ScreeningConfig(target_specializations=["QA"]).target_specializations == ["QA"]

    legacy = ScreeningConfig(enabled=True)
    empty = ScreeningConfig(enabled=True, targetSpecializations=[])
    missing = ScreeningConfig(enabled=True, targetSpecializations=None)
    assert empty == missing == legacy
    assert "targetSpecializations" not in empty.model_dump(by_alias=True, exclude_none=True)
    assert build_screening_config_hash(empty) == build_screening_config_hash(legacy)
    assert build_screening_config_hash(config) != build_screening_config_hash(legacy)


@pytest.mark.parametrize(
    "value",
    ["Backend", [1], [" "], ["x" * 161], [f"role-{n}" for n in range(51)]],
)
def test_invalid_specializations_are_rejected(value) -> None:
    with pytest.raises(ValidationError):
        ScreeningConfig(targetSpecializations=value)


def test_specialization_settings_round_trip_and_remain_search_specific(client: TestClient) -> None:
    headers = {"X-Rufina-Owner-Id": "specialization-owner"}
    saved = []
    for specialty in ("Backend", "Frontend"):
        response = client.post(
            "/job-search/configs",
            headers=headers,
            json={"name": specialty, "filters": filters([f" {specialty} ", specialty.lower()])},
        )
        assert response.status_code == 201
        config = response.json()
        assert config["filters"]["screening"]["targetRoles"] == ["Information Technology"]
        assert config["filters"]["screening"]["targetSpecializations"] == [specialty]
        saved.append(config)
        assert client.get(f"/job-search/configs/{config['id']}", headers=headers).json() == config

    cleared = client.patch(
        f"/job-search/configs/{saved[0]['id']}",
        headers=headers,
        json={"filters": filters([])},
    )
    assert cleared.status_code == 200
    assert (
        normalize_job_search_config(cleared.json()["filters"]).screening.target_specializations
        is None
    )
    other = client.get(f"/job-search/configs/{saved[1]['id']}", headers=headers).json()
    assert other["filters"]["screening"]["targetSpecializations"] == ["Frontend"]
    invalid = client.post(
        "/job-search/configs",
        headers=headers,
        json={"name": "Invalid", "filters": filters([" "])},
    )
    assert invalid.status_code == 422


def test_effective_config_keeps_direction_and_specialization_with_global_filters() -> None:
    config = normalize_job_search_config(filters(["Backend", "Frontend"]))
    effective = effective_screening_config(
        config,
        screening_required=True,
        job_filter=JobFilterSettings(
            enabled=True,
            cantonEnabled=True,
            allowedCantons=["ZH"],
            postingAgeEnabled=True,
            maxPostingAgeDays=7,
        ),
        now=datetime(2026, 10, 29, 12, tzinfo=UTC),
    )
    assert effective.target_roles == ["Information Technology"]
    assert effective.target_specializations == ["Backend", "Frontend"]
    assert effective.allowed_cantons == ["ZH"]
    assert effective.posted_after == "2026-10-22T12:00:00+00:00"
    restored = ScreeningConfig.model_validate(
        effective.model_dump(by_alias=True, exclude_none=True)
    )
    assert restored == effective


def test_prompt_requires_direction_and_one_specialization_with_responsibility_evidence() -> None:
    prompt = build_job_screening_prompt(
        ScreeningConfig(
            enabled=True,
            targetRoles=["Information Technology"],
            targetSpecializations=["Backend", "Frontend"],
        ),
        [
            CompactScreeningJob(
                id="generic-title",
                title="Software Engineer",
                description="Entwicklung von serverseitigen APIs und Geschäftslogik.",
            )
        ],
    )
    payload = json.loads(prompt.split("Input JSON:\n", 1)[1])
    assert payload["screeningConfig"]["targetRoles"] == ["Information Technology"]
    assert payload["screeningConfig"]["targetSpecializations"] == ["Backend", "Frontend"]
    assert "targetRoles AND at least one selected specialization" in prompt
    assert "multilingual wording" in prompt
    assert "Technologies alone do not establish a profession" in prompt
    assert payload["vacancies"][0]["description"].startswith("Entwicklung")


def candidate(**overrides) -> NewJobCandidate:
    return NewJobCandidate(
        job_id="specialty-job",
        job=ParsedJob(
            **{
                "source": "swisscom",
                "title": "Software Engineer",
                "company": "Example AG",
                "location": "Stäfa",
                "posted_at": "2026-10-28",
                "url": "https://example.test/specialty-job",
                "description": "Build client-side interfaces and collaborate with the backend team.",
                **overrides,
            }
        ),
    )


def screen(db, config, *, vacancy=None, rolling=False):
    return screen_new_job_candidates(
        db,
        candidates=[vacancy or candidate()],
        screening_config=config,
        rolling_posting_age=rolling,
        settings=Settings(app_env="local", database_url="sqlite://", auto_ai_match_enabled=False),
    )


@pytest.mark.parametrize(
    "local_filter",
    [
        {"allowedCantons": ["ZH"]},
        {"postedAfter": "2026-10-22T12:00:00+00:00", "maxPostingAgeDays": 7},
        {
            "allowedCantons": ["ZH"],
            "postedAfter": "2026-10-22T12:00:00+00:00",
            "maxPostingAgeDays": 7,
        },
    ],
)
def test_local_matches_cannot_bypass_specialization_screening(sessions, monkeypatch, local_filter):
    class Facade:
        def screen(self, config, jobs):
            assert config.target_specializations == ["Backend"]
            assert "client-side interfaces" in jobs[0]["description"]
            return [
                {
                    "id": jobs[0]["id"],
                    "decision": "reject",
                    "reasonCode": "specialization_mismatch",
                    "reason": "Primary responsibilities are frontend; backend is only collaboration.",
                    "matchedRuleIds": [],
                }
            ]

    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: Facade())
    with sessions() as db:
        result = screen(
            db, ScreeningConfig(enabled=True, targetSpecializations=["Backend"], **local_filter)
        )
    assert result.keep == []
    assert result.decisions[0].reason_code == "specialization_mismatch"
    assert result.jobs_screening_ai_calls == 1


def test_changed_specialization_does_not_reuse_another_searchs_cached_decision(
    sessions, monkeypatch
):
    calls = []

    class Facade:
        def screen(self, config, jobs):
            calls.append(config.target_specializations)
            return [
                {
                    "id": jobs[0]["id"],
                    "decision": "keep"
                    if config.target_specializations == ["Frontend"]
                    else "reject",
                    "reasonCode": "specialization_match"
                    if config.target_specializations == ["Frontend"]
                    else "specialization_mismatch",
                    "reason": "The vacancy's primary work is client-side interfaces.",
                    "matchedRuleIds": [],
                }
            ]

    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: Facade())
    with sessions() as db:
        frontend = ScreeningConfig(
            enabled=True, targetRoles=["Information Technology"], targetSpecializations=["Frontend"]
        )
        backend = ScreeningConfig(
            enabled=True, targetRoles=["Information Technology"], targetSpecializations=["Backend"]
        )
        first = screen(db, frontend)
        db.commit()
        second = screen(db, backend)
        db.commit()
        repeated = screen(db, frontend)
        assert len(db.scalars(select(JobScreeningDecisionRecord)).all()) >= 2
    assert first.jobs_passed == repeated.jobs_passed == 1
    assert second.jobs_rejected == 1
    assert repeated.jobs_screening_ai_calls == 0
    assert calls == [["Frontend"], ["Backend"]]
