from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models.applications  # noqa: F401
from app.core.database import Base
from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.job_search import JobSearchRunRecord, ScreeningConfig
from app.models.jobs import StoredJobRecord
from app.models.parsers import ParsedJob, ParserSearchResponse
from app.services import job_search_execution
from app.services.job_screening_store import build_screening_config_hash
from app.services.job_search_execution import JobSearchExecutionError, execute_job_search
from app.services.vacancy_search import VacancySearchRunResult

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
ENTRY_LEVELS = ["intern", "entry", "junior"]


class FakeRunner:
    def __init__(
        self,
        jobs: list[ParsedJob],
        *,
        sources: tuple[str, ...] = ("jobs_ch",),
        warnings: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = VacancySearchRunResult(
            jobs=jobs,
            source_results={
                source: ParserSearchResponse(
                    parser=source,
                    status="completed",
                    search_url=f"https://example.test/{source}",
                    jobs=[job for job in jobs if job.source == source],
                    warnings=(warnings or []) if source == "jobs_ch" else [],
                    message=message if source == "jobs_ch" else None,
                )
                for source in sources
            },
            source_errors={},
        )

    def run(self, **kwargs: Any) -> VacancySearchRunResult:
        self.calls.append(kwargs)
        return self.result


class KeepScreeningFacade:
    def __init__(self) -> None:
        self.calls: list[tuple[ScreeningConfig, list[dict[str, Any]]]] = []

    def screen(self, config: ScreeningConfig, jobs: list[dict[str, Any]]):
        self.calls.append((config, jobs))
        return [
            {
                "id": job["id"],
                "decision": "keep",
                "reasonCode": "target_role_match",
                "matchedRuleIds": [],
                "reason": "The remaining vacancy matches the configured role and seniority",
            }
            for job in jobs
        ]


@pytest.fixture
def db(tmp_path) -> Generator[Session, None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs-ch-execution.sqlite'}")
    Base.metadata.create_all(engine)
    owner_token = current_owner_id.set("jobs-ch-execution-owner")
    try:
        with Session(engine, autoflush=False) as session:
            yield session
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


@pytest.fixture
def screening(monkeypatch) -> KeepScreeningFacade:
    facade = KeepScreeningFacade()
    monkeypatch.setattr(
        job_search_execution, "create_job_screening_ai_facade", lambda _settings: facade
    )
    return facade


def vacancy(source: str, *, seniority: str) -> ParsedJob:
    return ParsedJob(
        source=source,
        title=f"{seniority.title()} Support Engineer",
        company=f"{source} AG",
        location="Zurich",
        url=f"https://example.test/{source}/{seniority}",
        seniority=seniority,
        description="Provide technical support for Python services.",
        posted_at="2026-09-13T08:00:00+00:00",
    )


def search_snapshot(
    *,
    experience: str = "Entry level",
    base_experience: str = "Any",
    remote: str = "Any",
    screening: dict[str, Any] | None = None,
    job_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "jobs-ch-test-config",
        "name": "Source-specific support search",
        "updatedAt": "2026-09-14T09:00:00+00:00",
        "filters": {
            "schemaVersion": 2,
            "search": {
                "keywords": "Support Engineer",
                "experienceLevel": base_experience,
            },
            "screening": screening or {"enabled": False},
        },
        "sourceConfigs": {
            "jobs_ch": {
                "source": "jobs_ch",
                "filters": {
                    "keywords": "IT Support",
                    "experienceLevel": experience,
                    "remote": remote,
                },
            },
        },
        "jobFilter": job_filter or {"schemaVersion": 1, "enabled": False},
    }


def execute(db: Session, runner: FakeRunner, snapshot: dict[str, Any], **kwargs: Any):
    return execute_job_search(
        db,
        schedule=None,
        config=None,
        config_snapshot=snapshot,
        runner=runner,
        settings=Settings(
            app_env="local",
            database_url="sqlite://",
            auto_ai_match_enabled=False,
        ),
        run_type=kwargs.pop("run_type", "manual"),
        sources=list(runner.result.source_results),
        now=NOW,
        **kwargs,
    )


@pytest.mark.parametrize("run_type", ["manual", "automatic"])
def test_jobs_ch_source_experience_rejects_senior_without_restricting_linkedin(
    db: Session, screening: KeepScreeningFacade, run_type: str
) -> None:
    runner = FakeRunner(
        [
            vacancy("jobs_ch", seniority="senior"),
            vacancy("jobs_ch", seniority="junior"),
            vacancy("linkedin", seniority="senior"),
        ],
        sources=("jobs_ch", "linkedin"),
    )

    result = execute(db, runner, search_snapshot(), run_type=run_type)

    assert result.run.status == "completed"
    assert result.run.jobs_found == 3
    assert result.run.jobs_screened == 2
    assert result.run.jobs_rejected == 1
    assert result.run.jobs_passed == 1
    assert result.run.jobs_added == 2
    assert result.run.warning is None
    assert result.run.config_snapshot["filters"]["screening"]["allowedSeniority"] == []
    source_policy = result.run.config_snapshot["sourceScreening"]["jobs_ch"]
    assert source_policy["allowedSeniority"] == ENTRY_LEVELS
    assert runner.calls[0]["source_requests"]["jobs_ch"].experience_level == "Entry level"
    assert runner.calls[0]["request"].experience_level == "Any"
    assert len(screening.calls) == 1
    ai_policy, ai_jobs = screening.calls[0]
    assert ai_policy.allowed_seniority == ENTRY_LEVELS
    assert [job["title"] for job in ai_jobs] == ["Junior Support Engineer"]

    records = {record.data["company"]: record for record in db.scalars(select(StoredJobRecord))}
    assert set(records) == {"jobs_ch AG", "linkedin AG"}
    jobs_ch_record = records["jobs_ch AG"]
    assert jobs_ch_record.data["title"] == "Junior Support Engineer"
    assert jobs_ch_record.screening_config_snapshot == source_policy
    assert jobs_ch_record.data["screeningConfigSnapshot"] == source_policy
    assert jobs_ch_record.search_config_id == "jobs-ch-test-config"
    assert jobs_ch_record.screening_config_hash == build_screening_config_hash(
        ScreeningConfig.model_validate(source_policy)
    )
    assert records["linkedin AG"].screening_config_snapshot["allowedSeniority"] == []
    decisions = db.scalars(select(JobScreeningDecisionRecord)).all()
    assert sorted(decision.decision for decision in decisions) == ["keep", "reject"]
    assert next(decision for decision in decisions if decision.decision == "reject").reason_code == (
        "seniority_mismatch"
    )


def test_jobs_ch_source_experience_conflict_fails_before_parser(db: Session) -> None:
    runner = FakeRunner([])
    snapshot = search_snapshot(
        job_filter={
            "schemaVersion": 1,
            "enabled": True,
            "allowedSeniority": ["senior"],
        }
    )

    with pytest.raises(JobSearchExecutionError, match="incompatible allowed seniority"):
        execute(db, runner, snapshot)

    assert runner.calls == []
    run = db.scalar(select(JobSearchRunRecord))
    assert run is not None
    assert run.status == "failed"
    assert "incompatible allowed seniority" in run.source_errors["config"]
    assert list(db.scalars(select(StoredJobRecord))) == []


def test_jobs_ch_override_replaces_unused_base_experience_before_global_conflict_check(
    db: Session, screening: KeepScreeningFacade
) -> None:
    runner = FakeRunner([vacancy("jobs_ch", seniority="senior")])
    snapshot = search_snapshot(
        experience="Mid-Senior level",
        base_experience="Entry level",
        job_filter={
            "schemaVersion": 1,
            "enabled": True,
            "allowedSeniority": ["senior"],
        },
    )

    result = execute(db, runner, snapshot)

    assert len(runner.calls) == 1
    assert runner.calls[0]["source_requests"]["jobs_ch"].experience_level == "Mid-Senior level"
    assert result.run.status == "completed"
    assert result.run.source_errors == {}
    assert result.run.jobs_added == 1
    assert result.run.jobs_rejected == 0
    assert len(screening.calls) == 1
    assert screening.calls[0][0].allowed_seniority == ["senior"]
    assert result.run.config_snapshot["sourceScreening"]["jobs_ch"]["allowedSeniority"] == ["senior"]
    record = db.scalar(select(StoredJobRecord))
    assert record is not None
    assert record.screening_config_snapshot["allowedSeniority"] == ["senior"]


def test_jobs_ch_any_overrides_only_the_base_search_experience(
    db: Session, screening: KeepScreeningFacade
) -> None:
    runner = FakeRunner(
        [
            vacancy("jobs_ch", seniority="senior"),
            vacancy("linkedin", seniority="senior"),
            vacancy("linkedin", seniority="junior"),
        ],
        sources=("jobs_ch", "linkedin"),
    )

    result = execute(db, runner, search_snapshot(experience="Any", base_experience="Entry level"))

    assert result.run.status == "completed"
    assert result.run.jobs_added == 2
    assert result.run.jobs_rejected == 1
    assert result.run.config_snapshot["sourceScreening"]["jobs_ch"]["allowedSeniority"] == []
    assert result.run.config_snapshot["filters"]["screening"]["allowedSeniority"] == ENTRY_LEVELS
    assert len(screening.calls) == 1
    assert [job["title"] for job in screening.calls[0][1]] == ["Junior Support Engineer"]
    records = {record.data["company"]: record for record in db.scalars(select(StoredJobRecord))}
    assert records["jobs_ch AG"].data["title"] == "Senior Support Engineer"
    assert records["jobs_ch AG"].screening_config_snapshot["enabled"] is False
    assert records["linkedin AG"].screening_config_snapshot["allowedSeniority"] == ENTRY_LEVELS


def test_jobs_ch_and_linkedin_share_one_ai_batch_for_identical_policies(
    db: Session, screening: KeepScreeningFacade
) -> None:
    runner = FakeRunner(
        [vacancy("jobs_ch", seniority="junior"), vacancy("linkedin", seniority="junior")],
        sources=("jobs_ch", "linkedin"),
    )

    result = execute(
        db,
        runner,
        search_snapshot(
            experience="Any",
            screening={"enabled": True, "targetRoles": ["Support Engineer"]},
        ),
    )

    assert result.run.jobs_added == 2
    assert result.run.jobs_screened == 2
    assert result.run.jobs_screening_ai_calls == 1
    assert len(screening.calls) == 1
    assert {job["company"] for job in screening.calls[0][1]} == {"jobs_ch AG", "linkedin AG"}
    records = list(db.scalars(select(StoredJobRecord)))
    assert len({record.screening_config_hash for record in records}) == 1


@pytest.mark.parametrize("other_source", ["linkedin", "sbb"])
@pytest.mark.parametrize("jobs_ch_first", [True, False])
@pytest.mark.parametrize("global_junior_only", [False, True])
def test_cross_source_duplicate_uses_all_source_policies_after_early_deduplication(
    db: Session,
    screening: KeepScreeningFacade,
    other_source: str,
    jobs_ch_first: bool,
    global_junior_only: bool,
) -> None:
    sources = ("jobs_ch", other_source) if jobs_ch_first else (other_source, "jobs_ch")
    jobs = [
        vacancy(source, seniority="senior").model_copy(update={"company": "Shared Employer AG"})
        for source in sources
    ]
    assert jobs[0].url != jobs[1].url
    runner = FakeRunner(jobs, sources=sources)
    # VacancySearchRunner deduplicates by title/company/location before execution.
    # Keep the first representative plus both original source responses, as it does.
    runner.result = VacancySearchRunResult(
        jobs=[jobs[0]],
        source_results=runner.result.source_results,
        source_errors={},
    )
    snapshot = search_snapshot(
        job_filter={
            "schemaVersion": 1,
            "enabled": True,
            "allowedSeniority": ["junior"],
        }
        if global_junior_only
        else None
    )

    result = execute(db, runner, snapshot)

    assert result.run.status == "completed"
    assert result.run.jobs_found == 1
    assert result.run.jobs_discovered_new == 1
    assert result.run.screening_errors == 0
    assert screening.calls == []
    records = list(db.scalars(select(StoredJobRecord)))
    if global_junior_only:
        assert result.run.jobs_rejected == 1
        assert result.run.jobs_added == 0
        assert records == []
        decision = db.scalar(select(JobScreeningDecisionRecord))
        assert decision is not None
        assert decision.reason_code == "seniority_mismatch"
    else:
        assert result.run.jobs_rejected == 0
        assert result.run.jobs_added == 1
        assert len(records) == 1
        assert records[0].data["title"] == "Senior Support Engineer"
        # Import provenance must record the permissive merged policy even when
        # the representative itself came from the narrower jobs.ch search.
        assert records[0].screening_config_snapshot["allowedSeniority"] == []
        assert records[0].screening_config_snapshot["enabled"] is False
        assert records[0].data["screeningConfigSnapshot"] == records[0].screening_config_snapshot


def test_jobs_ch_any_preserves_explicit_and_global_screening_rules(
    db: Session, screening: KeepScreeningFacade
) -> None:
    runner = FakeRunner(
        [vacancy("jobs_ch", seniority="senior"), vacancy("jobs_ch", seniority="junior")]
    )
    snapshot = search_snapshot(
        experience="Any",
        base_experience="Entry level",
        screening={
            "enabled": True,
            "targetRoles": ["Support Engineer"],
            "excludedRoles": ["Sales Manager"],
            "allowedSeniority": ["mid", "senior"],
            "excludedSeniority": ["director"],
            "hardRules": [{"field": "location", "operator": "equals", "value": "Zurich"}],
        },
        job_filter={
            "schemaVersion": 1,
            "enabled": True,
            "allowedSeniority": ["senior", "lead"],
            "targetTechnologies": ["Python"],
        },
    )

    result = execute(db, runner, snapshot)

    assert result.run.status == "completed"
    assert result.run.jobs_rejected == 1
    assert result.run.jobs_added == 1
    assert len(screening.calls) == 1
    policy, jobs = screening.calls[0]
    assert policy.allowed_seniority == ["senior"]
    assert policy.excluded_seniority == ["director"]
    assert policy.target_roles == ["Support Engineer"]
    assert policy.excluded_roles == ["Sales Manager"]
    assert policy.target_technologies == ["Python"]
    assert policy.hard_rules[0].value == "Zurich"
    assert [job["title"] for job in jobs] == ["Senior Support Engineer"]
    record = db.scalar(select(StoredJobRecord))
    assert record is not None
    assert record.screening_config_snapshot["allowedSeniority"] == ["senior"]
    assert record.screening_config_snapshot["targetTechnologies"] == ["Python"]


@pytest.mark.parametrize(
    ("warnings", "remote", "status"),
    [
        (["jobs.ch: page 2 could not be loaded; results are incomplete"], "Any", "partial"),
        (["jobs.ch: 1 description could not be loaded"], "Hybrid", "partial"),
        ([], "Hybrid", "completed"),
        ([], "Any", "completed"),
    ],
)
def test_parser_warnings_and_unsupported_filters_survive_run_persistence(
    db: Session, warnings: list[str], remote: str, status: str
) -> None:
    runner = FakeRunner(
        [],
        warnings=warnings,
        message="jobs.ch does not apply these filters: remote, experience level"
        if remote != "Any"
        else "jobs.ch does not apply these filters: experience level",
    )

    result = execute(db, runner, search_snapshot(remote=remote))
    db.expire_all()
    run = db.get(JobSearchRunRecord, result.run.id)

    assert run is not None
    assert run.status == status
    assert run.warning == result.warning
    assert run.source_errors == {}
    for warning in warnings:
        assert warning in (run.warning or "")
    if remote != "Any":
        assert "jobs.ch does not apply these filters: remote" in (run.warning or "")
    assert "experience level" not in (run.warning or "")
    if not warnings and remote == "Any":
        assert run.warning is None
