from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models.applications  # noqa: F401
from app.core.database import Base
from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.job_search import ScreeningConfig
from app.models.parsers import ParsedJob, ParserSearchResponse
from app.services import job_search_execution
from app.services.job_screening_store import (
    build_screening_cache_config_hash,
    build_screening_config_hash,
)
from app.services.job_search_execution import (
    NewJobCandidate,
    execute_job_search,
    screen_new_job_candidates,
)
from app.services.vacancy_search import VacancySearchRunResult

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


class FakeScreeningFacade:
    def __init__(self) -> None:
        self.decision = "keep"
        self.calls: list[tuple[ScreeningConfig, list[str]]] = []

    def screen(self, config: ScreeningConfig, jobs: list[dict[str, object]]):
        self.calls.append((config, [str(job["id"]) for job in jobs]))
        return [
            {
                "id": job["id"],
                "decision": self.decision,
                "reasonCode": "target_role_match" if self.decision == "keep" else "role_mismatch",
                "matchedRuleIds": [],
                "reason": "Evaluated the configured role",
            }
            for job in jobs
        ]


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    owner_token = current_owner_id.set("jobs-ch-cache-test")
    try:
        with Session(engine) as session:
            yield session
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


@pytest.fixture
def facade(monkeypatch: pytest.MonkeyPatch) -> FakeScreeningFacade:
    result = FakeScreeningFacade()
    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: result)
    return result


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="local", database_url="sqlite://", auto_ai_match_enabled=False)


def config(
    now: datetime = NOW,
    *,
    days: int = 7,
    role: str = "Backend Engineer",
) -> ScreeningConfig:
    return ScreeningConfig.model_validate(
        {
            "enabled": True,
            "targetRoles": [role],
            "maxPostingAgeDays": days,
            "postedAfter": (now - timedelta(days=days)).isoformat(),
        }
    )


def candidate(
    *,
    job_id: str = "jobs-ch-1",
    posted_at: str | None = "2026-09-14T10:00:00+00:00",
) -> NewJobCandidate:
    return NewJobCandidate(
        job_id=job_id,
        job=ParsedJob(
            source="jobs_ch",
            title="Backend Engineer",
            company="Example AG",
            description="Build Python APIs",
            url=f"https://example.test/{job_id}",
            posted_at=posted_at,
        ),
    )


@pytest.mark.parametrize("decision", ["keep", "reject", "uncertain"])
def test_repeated_run_reuses_ai_decisions_for_same_rolling_rules(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
    decision: str,
) -> None:
    facade.decision = decision
    original_config = config()
    first = screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=original_config,
        settings=settings,
        rolling_posting_age=True,
    )
    db.commit()
    second = screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=config(NOW + timedelta(hours=1)),
        settings=settings,
        rolling_posting_age=True,
    )

    assert first.jobs_screening_ai_calls == 1
    assert second.jobs_screening_ai_calls == 0
    assert second.decisions[0].decision == decision
    assert len(facade.calls) == 1
    # Time-dependent rules are checked locally, never delegated to cached AI.
    assert facade.calls[0][0].posted_after is None
    assert facade.calls[0][0].max_posting_age_days is None
    assert facade.calls[0][0].target_roles == original_config.target_roles
    assert original_config.posted_after == "2026-09-07T12:00:00+00:00"
    records = db.scalars(select(JobScreeningDecisionRecord)).all()
    assert len(records) == 1
    assert records[0].config_hash == build_screening_config_hash(
        original_config,
        rolling_posting_age=True,
    )


def test_vacancy_expiring_after_cached_keep_is_rejected_without_ai(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
) -> None:
    screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=config(),
        settings=settings,
        rolling_posting_age=True,
    )
    db.commit()
    expired_config = config(NOW + timedelta(days=8))
    expired = screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=expired_config,
        settings=settings,
        rolling_posting_age=True,
    )
    db.commit()

    assert expired.keep == []
    assert expired.jobs_screening_ai_calls == 0
    assert expired.decisions[0].reason_code == "posting_too_old"
    assert len(facade.calls) == 1
    old_date_record = db.scalar(
        select(JobScreeningDecisionRecord).where(
            JobScreeningDecisionRecord.reason_code == "posting_too_old",
        )
    )
    assert old_date_record is not None
    assert old_date_record.config_hash == build_screening_config_hash(expired_config)


def test_moving_cutoff_backwards_does_not_reuse_previous_age_rejection(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
) -> None:
    expired = screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=config(NOW + timedelta(days=8)),
        settings=settings,
        rolling_posting_age=True,
    )
    db.commit()
    earlier = screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=config(),
        settings=settings,
        rolling_posting_age=True,
    )

    assert expired.decisions[0].reason_code == "posting_too_old"
    assert earlier.jobs_passed == 1
    assert earlier.jobs_screening_ai_calls == 1
    assert len(facade.calls) == 1


@pytest.mark.parametrize("posted_at", [None, "published recently", "2 days ago"])
def test_unknown_or_relative_dates_are_reassessed_against_new_cutoff(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
    posted_at: str | None,
) -> None:
    configs = [config(), config(NOW + timedelta(hours=1))]
    for current in configs:
        result = screen_new_job_candidates(
            db,
            candidates=[candidate(posted_at=posted_at)],
            screening_config=current,
            settings=settings,
            rolling_posting_age=True,
        )
        db.commit()
        assert result.jobs_screening_ai_calls == 1

    assert len(facade.calls) == 2
    assert [call[0].posted_after for call in facade.calls] == [
        current.posted_after for current in configs
    ]


def test_manually_specified_absolute_cutoff_stays_in_cache_identity(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
) -> None:
    for current in (config(), config(NOW + timedelta(hours=1))):
        result = screen_new_job_candidates(
            db,
            candidates=[candidate()],
            screening_config=current,
            settings=settings,
        )
        db.commit()
        assert result.jobs_screening_ai_calls == 1

    assert len(facade.calls) == 2
    assert all(current.posted_after is not None for current, _ in facade.calls)


@pytest.mark.parametrize("change", ["window", "role", "model", "prompt"])
def test_semantic_rule_model_and_prompt_changes_invalidate_rolling_cache(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=config(),
        settings=settings,
        rolling_posting_age=True,
    )
    db.commit()
    next_config = config(NOW + timedelta(hours=1))
    if change == "window":
        next_config = config(NOW + timedelta(hours=1), days=30)
    elif change == "role":
        next_config = config(NOW + timedelta(hours=1), role="Product Manager")
    elif change == "model":
        settings = settings.model_copy(update={"job_screening_model": "test-changed-model"})
    else:
        monkeypatch.setattr(job_search_execution, "JOB_SCREENING_PROMPT_VERSION", "test-changed")
    changed = screen_new_job_candidates(
        db,
        candidates=[candidate()],
        screening_config=next_config,
        settings=settings,
        rolling_posting_age=True,
    )

    assert changed.jobs_screening_ai_calls == 1
    assert len(facade.calls) == 2


def test_known_and_unknown_dates_use_separate_ai_batches_and_cache_keys(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
) -> None:
    jobs = [candidate(), candidate(job_id="unknown-date", posted_at=None)]
    result = screen_new_job_candidates(
        db,
        candidates=jobs,
        screening_config=config(),
        settings=settings,
        rolling_posting_age=True,
    )
    db.commit()
    second = screen_new_job_candidates(
        db,
        candidates=jobs,
        screening_config=config(NOW + timedelta(hours=1)),
        settings=settings,
        rolling_posting_age=True,
    )

    assert result.jobs_screening_ai_calls == 2
    assert second.jobs_screening_ai_calls == 1
    assert [item.job_id for item in second.keep] == ["jobs-ch-1", "unknown-date"]
    assert facade.calls[0][0].posted_after is None
    assert facade.calls[1][0].posted_after is not None
    assert facade.calls[2][1] == ["unknown-date"]
    assert build_screening_cache_config_hash(
        config(), {"postedAt": None}, rolling_posting_age=True
    ) != (
        build_screening_cache_config_hash(
            config(), {"postedAt": jobs[0].job.posted_at}, rolling_posting_age=True
        )
    )


@pytest.mark.parametrize("decision", ["reject", "uncertain"])
def test_complete_search_runs_reuse_screening_and_retain_exact_audit_snapshots(
    db: Session,
    facade: FakeScreeningFacade,
    settings: Settings,
    decision: str,
) -> None:
    facade.decision = decision

    class FakeRunner:
        def run(self, **_kwargs) -> VacancySearchRunResult:
            job = candidate().job
            return VacancySearchRunResult(
                jobs=[job],
                source_results={
                    "jobs_ch": ParserSearchResponse(
                        parser="jobs_ch",
                        status="completed",
                        jobs=[job],
                        search_url="https://example.test/jobs",
                    ),
                },
                source_errors={},
            )

    runs = []
    for now in (NOW, NOW + timedelta(hours=1)):
        result = execute_job_search(
            db,
            schedule=None,
            config=None,
            config_snapshot={
                "name": "Recent engineering jobs",
                "filters": {
                    "schemaVersion": 2,
                    "search": {"keywords": "Backend Engineer"},
                    "screening": {"enabled": True, "targetRoles": ["Backend Engineer"]},
                },
                "sourceConfigs": {
                    "jobs_ch": {"filters": {"keywords": "Backend Engineer"}},
                },
                "jobFilter": {
                    "enabled": True,
                    "postingAgeEnabled": True,
                    "maxPostingAgeDays": 7,
                },
            },
            sources=["jobs_ch"],
            runner=FakeRunner(),
            settings=settings,
            run_type="manual",
            now=now,
            screening_required=True,
        )
        runs.append(result.run)

    assert [run.jobs_found for run in runs] == [1, 1]
    assert [run.jobs_added for run in runs] == [0, 0]
    assert [run.jobs_screening_ai_calls for run in runs] == [1, 0]
    assert runs[0].jobs_discovered_new == 1
    assert runs[1].jobs_already_observed == 1
    assert len(facade.calls) == 1
    assert [run.config_snapshot["filters"]["screening"]["postedAfter"] for run in runs] == [
        "2026-09-07T12:00:00+00:00",
        "2026-09-07T13:00:00+00:00",
    ]
