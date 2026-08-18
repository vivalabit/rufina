from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time
from threading import Event, Lock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.core.settings import Settings
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.job_search import (
    JobSearchConfigRecord,
    JobSearchRunRecord,
    JobSearchScheduleRecord,
)
from app.models.jobs import StoredJobRecord
from app.models.parsers import ParsedJob, ParserSearchResponse
from app.models.privacy import AiPrivacySettingsRecord
from app.services import job_search_execution
from app.services.job_search_execution import build_config_snapshot
from app.services.job_search_worker import run_job_search_cycle
from app.services.vacancy_search import VacancySearchRunResult


class RecordingRunner:
    def __init__(
        self,
        *,
        started: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self.started = started
        self.release = release
        self._calls = 0
        self._lock = Lock()

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def run(self, **_kwargs) -> VacancySearchRunResult:
        with self._lock:
            self._calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=3)
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


class FailingRunner:
    def run(self, **_kwargs) -> VacancySearchRunResult:
        raise RuntimeError("source exploded")


class JobRunner:
    def __init__(self, jobs: list[ParsedJob]) -> None:
        self.jobs = jobs

    def run(self, **_kwargs) -> VacancySearchRunResult:
        return VacancySearchRunResult(
            jobs=self.jobs,
            source_results={
                "linkedin": ParserSearchResponse(
                    parser="linkedin",
                    status="completed",
                    search_url="https://example.test/linkedin",
                    jobs=self.jobs,
                )
            },
            source_errors={},
        )


def test_two_competing_workers_execute_a_due_schedule_once(tmp_path) -> None:
    sessions = create_sessions(tmp_path / "competing-workers.sqlite")
    due_at = datetime(2026, 7, 23, 6, 0, tzinfo=UTC)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    schedule_id = seed_schedule(sessions, next_run_at=due_at)
    started = Event()
    release = Event()
    runner = RecordingRunner(started=started, release=release)
    settings = worker_settings()

    def cycle() -> list[str]:
        return run_job_search_cycle(
            settings=settings,
            session_factory=sessions,
            runner_factory=lambda _settings: runner,
            now=now,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cycle)
        assert started.wait(timeout=3)
        second = executor.submit(cycle)
        assert second.result(timeout=3) == []
        release.set()
        assert len(first.result(timeout=3)) == 1

    assert runner.calls == 1
    with sessions() as db:
        runs = list(db.scalars(select(JobSearchRunRecord)).all())
        schedule = db.get(JobSearchScheduleRecord, schedule_id)
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].scheduled_for == due_at.replace(tzinfo=None)
        assert schedule is not None
        assert schedule.next_run_at == datetime(2026, 7, 24, 6, 0)


def test_failed_search_keeps_the_reserved_next_run(tmp_path) -> None:
    sessions = create_sessions(tmp_path / "failed-search.sqlite")
    due_at = datetime(2026, 7, 23, 6, 0, tzinfo=UTC)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    schedule_id = seed_schedule(sessions, next_run_at=due_at)

    executed = run_job_search_cycle(
        settings=worker_settings(),
        session_factory=sessions,
        runner_factory=lambda _settings: FailingRunner(),
        now=now,
    )

    assert len(executed) == 1
    with sessions() as db:
        run = db.scalar(select(JobSearchRunRecord))
        schedule = db.get(JobSearchScheduleRecord, schedule_id)
        assert run is not None
        assert run.status == "failed"
        assert run.source_errors == {"runner": "source exploded"}
        assert schedule is not None
        assert schedule.next_run_at == datetime(2026, 7, 24, 6, 0)


def test_restart_collapses_missed_intervals_into_one_run(tmp_path) -> None:
    sessions = create_sessions(tmp_path / "restart.sqlite")
    missed_at = datetime(2026, 7, 19, 6, 0, tzinfo=UTC)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    schedule_id = seed_schedule(sessions, next_run_at=missed_at)
    runner = RecordingRunner()
    settings = worker_settings()

    first_cycle = run_job_search_cycle(
        settings=settings,
        session_factory=sessions,
        runner_factory=lambda _settings: runner,
        now=now,
    )
    second_cycle = run_job_search_cycle(
        settings=settings,
        session_factory=sessions,
        runner_factory=lambda _settings: runner,
        now=now,
    )

    assert len(first_cycle) == 1
    assert second_cycle == []
    assert runner.calls == 1
    with sessions() as db:
        runs = list(db.scalars(select(JobSearchRunRecord)).all())
        schedule = db.get(JobSearchScheduleRecord, schedule_id)
        assert len(runs) == 1
        assert runs[0].scheduled_for == missed_at.replace(tzinfo=None)
        assert schedule is not None
        assert schedule.next_run_at == datetime(2026, 7, 24, 6, 0)


def test_restart_resumes_an_incomplete_reserved_run(tmp_path) -> None:
    sessions = create_sessions(tmp_path / "incomplete-run.sqlite")
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    overdue_next_at = datetime(2026, 7, 22, 6, 0, tzinfo=UTC)
    schedule_id = seed_schedule(sessions, next_run_at=overdue_next_at)
    with sessions() as db:
        schedule = db.get(JobSearchScheduleRecord, schedule_id)
        assert schedule is not None
        config = db.get(JobSearchConfigRecord, schedule.config_id)
        assert config is not None
        run = JobSearchRunRecord(
            owner_id=schedule.owner_id,
            schedule_id=schedule.id,
            run_type="automatic",
            scheduled_for=datetime(2026, 7, 23, 6, 0, tzinfo=UTC),
            config_snapshot=build_config_snapshot(config),
            sources=list(schedule.sources),
            status="running",
            jobs_found=0,
            jobs_added=0,
            source_errors={},
            started_at=datetime(2026, 7, 23, 6, 0, tzinfo=UTC),
        )
        db.add(run)
        db.commit()
        run_id = run.id

    runner = RecordingRunner()
    executed = run_job_search_cycle(
        settings=worker_settings(),
        session_factory=sessions,
        runner_factory=lambda _settings: runner,
        now=now,
    )

    assert executed == [run_id]
    assert runner.calls == 1
    with sessions() as db:
        resumed = db.get(JobSearchRunRecord, run_id)
        schedule = db.get(JobSearchScheduleRecord, schedule_id)
        assert resumed is not None
        assert resumed.status == "completed"
        assert resumed.completed_at is not None
        assert schedule is not None
        assert schedule.next_run_at == datetime(2026, 7, 24, 6, 0)


def test_automatic_screening_error_is_persisted_and_fail_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = create_sessions(tmp_path / "automatic-screening-error.sqlite")
    due_at = datetime(2026, 7, 23, 6, 0, tzinfo=UTC)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    settings = worker_settings()
    seed_schedule(
        sessions,
        next_run_at=due_at,
        filters=screening_filters(),
    )
    seed_ai_privacy_settings(sessions, settings=settings)
    job = ParsedJob(
        source="linkedin",
        title="Automatic Unchecked Engineer",
        company="Worker Test AG",
        location="Zurich",
        url="https://www.linkedin.com/jobs/view/automatic-screening-error",
        description="A vacancy that must never bypass screening",
    )

    class FailingScreeningFacade:
        def screen(self, _config, _jobs):
            raise RuntimeError("cheap model timed out")

    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: FailingScreeningFacade(),
    )

    executed = run_job_search_cycle(
        settings=settings,
        session_factory=sessions,
        runner_factory=lambda _settings: JobRunner([job]),
        now=now,
    )

    assert len(executed) == 1
    with sessions() as db:
        run = db.scalar(select(JobSearchRunRecord))
        stored = list(db.scalars(select(StoredJobRecord)).all())
        decision = db.scalar(select(JobScreeningDecisionRecord))
    assert run is not None
    assert run.status == "partial"
    assert run.jobs_found == 1
    assert run.jobs_screened == 1
    assert run.jobs_uncertain == 1
    assert run.jobs_added == 0
    assert run.jobs_analyzed == 0
    assert run.screening_errors == 1
    assert run.warning is not None
    assert "unverified vacancies were skipped" in run.warning
    assert stored == []
    assert decision is not None
    assert decision.decision == "uncertain"
    assert decision.reason_code == "screening_error"


def test_automatic_screening_persists_only_keep(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = create_sessions(tmp_path / "automatic-screening-success.sqlite")
    due_at = datetime(2026, 7, 23, 6, 0, tzinfo=UTC)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    settings = worker_settings()
    seed_schedule(
        sessions,
        next_run_at=due_at,
        filters=screening_filters(),
    )
    seed_ai_privacy_settings(sessions, settings=settings)
    keep = worker_job("Automatic Software Engineer", "automatic-keep")
    reject = worker_job("Automatic Sales Manager", "automatic-reject")

    class ScreeningFacade:
        def screen(self, _config, jobs):
            return [
                {
                    "id": job["id"],
                    "decision": (
                        "keep" if "Software Engineer" in job["title"] else "reject"
                    ),
                    "reasonCode": (
                        "target_role_match"
                        if "Software Engineer" in job["title"]
                        else "excluded_role"
                    ),
                    "matchedRuleIds": [],
                    "reason": f"Screened {job['title']}",
                }
                for job in jobs
            ]

    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: ScreeningFacade(),
    )

    executed = run_job_search_cycle(
        settings=settings,
        session_factory=sessions,
        runner_factory=lambda _settings: JobRunner([keep, reject]),
        now=now,
    )

    assert len(executed) == 1
    with sessions() as db:
        run = db.scalar(select(JobSearchRunRecord))
        stored = list(db.scalars(select(StoredJobRecord)).all())
        decisions = list(db.scalars(select(JobScreeningDecisionRecord)).all())
    assert run is not None
    assert run.status == "completed"
    assert run.jobs_screened == 2
    assert run.jobs_passed == 1
    assert run.jobs_rejected == 1
    assert run.jobs_uncertain == 0
    assert run.jobs_added == 1
    assert run.screening_errors == 0
    assert run.warning is None
    assert [record.data["title"] for record in stored] == [keep.title]
    assert {decision.decision for decision in decisions} == {"keep", "reject"}


def create_sessions(database_path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 3},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_schedule(
    sessions: sessionmaker[Session],
    *,
    next_run_at: datetime,
    filters: dict[str, object] | None = None,
) -> str:
    with sessions() as db:
        config = JobSearchConfigRecord(
            owner_id="worker-owner",
            name="Background search",
            filters=filters
            or {"keywords": "Platform Engineer", "location": "Zurich"},
        )
        schedule = JobSearchScheduleRecord(
            owner_id="worker-owner",
            name="Daily background search",
            config=config,
            sources=["linkedin"],
            frequency="daily",
            weekdays=[],
            local_time=time(6, 0),
            timezone="UTC",
            ai_analysis_enabled=False,
            enabled=True,
            next_run_at=next_run_at,
        )
        db.add(schedule)
        db.commit()
        return schedule.id


def screening_filters() -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "search": {
            "keywords": "Software Engineer",
            "location": "Zurich",
        },
        "screening": {
            "enabled": True,
            "targetRoles": ["Software Engineer"],
            "allowedSeniority": [],
            "excludedSeniority": [],
            "hardRules": [],
        },
    }


def seed_ai_privacy_settings(
    sessions: sessionmaker[Session],
    *,
    settings: Settings,
) -> None:
    now = datetime.now(UTC)
    with sessions() as db:
        db.add(
            AiPrivacySettingsRecord(
                owner_id="worker-owner",
                retention_days=30,
                updated_at=now,
            )
        )
        db.commit()


def worker_job(title: str, slug: str) -> ParsedJob:
    return ParsedJob(
        source="linkedin",
        title=title,
        company="Worker Test AG",
        location="Zurich",
        url=f"https://www.linkedin.com/jobs/view/{slug}",
        description=f"{title} vacancy",
    )


def worker_settings() -> Settings:
    return Settings(
        app_env="local",
        database_url="sqlite://",
        job_search_poll_interval_seconds=30,
    )
