from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from time import sleep

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from test_job_search_run_api import ApiContext, FakeScreeningFacade, api_context as api_context

from app.core.identity import current_owner_id
from app.core.database import Base
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.job_search import JobSearchRunRecord, normalize_job_search_config
from app.models.jobs import StoredJobRecord
from app.models.parsers import ParsedJob
from app.services import job_search_execution
from app.services import job_screening_recovery
from app.services.discovered_vacancies import upsert_discovered_vacancies, compact_screening_data
from app.services.job_screening import JOB_SCREENING_PROMPT_VERSION
from app.services.job_screening_recovery import recover_failed_screening
from app.services.job_screening_store import (
    build_screening_config_hash,
    persist_screening_decision,
)


def seed_failed_run(db):
    started = datetime.now(UTC) - timedelta(minutes=5)
    config = normalize_job_search_config({
        "schemaVersion": 2, "search": {},
        "screening": {"enabled": True, "targetRoles": ["IT"]},
    })
    run = JobSearchRunRecord(
        id="source-run", owner_id="local-owner", run_type="manual", status="partial",
        started_at=started, completed_at=started + timedelta(minutes=1),
        config_snapshot={"name": "Test", "filters": config.model_dump(by_alias=True)},
        sources=["swisscom"], jobs_found=4, jobs_added=0, screening_errors=4,
    )
    db.add(run)
    jobs = [ParsedJob(
        source="swisscom", title=title, company="Test", location="Bern",
        url=f"https://example.test/{title}", description=f"Original {title} role",
    ) for title in ("Allowed", "Rejected", "Uncertain", "Dismissed")]
    inventory = upsert_discovered_vacancies(db, jobs=jobs, run_id=run.id)
    for index, snapshot in enumerate(inventory.vacancies):
        persist_screening_decision(
            db, vacancy_hash=snapshot.vacancy_hash,
            config_hash=build_screening_config_hash(config.screening),
            decision={"id": snapshot.job_id, "decision": "uncertain",
                      "reasonCode": "screening_error", "matchedRuleIds": [], "reason": "Failed"},
            model="openai/gpt-6-luna", prompt_version=JOB_SCREENING_PROMPT_VERSION,
            title=snapshot.job.title, company=snapshot.job.company, source_url=snapshot.job.url,
            vacancy_data=compact_screening_data(snapshot.job, job_id=snapshot.job_id),
            created_at=started + timedelta(seconds=20 + index),
        )
    dismissed = inventory.vacancies[-1]
    db.add(StoredJobRecord(id=dismissed.job_id, data={"title": "Dismissed"}, status="dismissed"))
    db.commit()
    return run


def test_dry_run_and_resumed_batches_preserve_source_and_only_add_keeps(api_context: ApiContext, monkeypatch):
    facade = FakeScreeningFacade({"Allowed": "keep", "Rejected": "reject", "Uncertain": "uncertain"})
    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: facade)
    settings = api_context.settings.model_copy(update={
        "job_screening_model": "openai/gpt-6.1-sol", "job_screening_batch_size": 1,
    })
    with api_context.sessions() as db:
        original = seed_failed_run(db)
        original_snapshot = dict(original.config_snapshot)
        dry = recover_failed_screening(db, source_run_id=original.id, settings=settings, dry_run=True)
        assert dry == {"sourceRunId": original.id, "model": "openai/gpt-6.1-sol", "total": 4,
                       "eligible": 3, "known": 1, "dryRun": True}
        assert facade.calls == []
        assert len(db.scalars(select(JobSearchRunRecord)).all()) == 1
        first = recover_failed_screening(db, source_run_id=original.id, settings=settings, max_batches=1)
        assert first["added"] == 1
        assert first["pending"] == 2
        run_id = first["runId"]
        assert first["status"] == "partial"
    # Resume from a fresh DB session, so persistence/checkpointing is exercised.
    with api_context.sessions() as db:
        final = recover_failed_screening(db, source_run_id="source-run", recovery_run_id=run_id,
                                         settings=settings)
        assert final == {"runId": run_id, "status": "completed", "total": 4, "screened": 3,
                         "added": 1, "rejected": 1, "uncertain": 1, "errors": 0,
                         "known": 1, "pending": 0, "aiCalls": 3}
        assert len(facade.calls) == 3
        again = recover_failed_screening(db, source_run_id="source-run", recovery_run_id=run_id,
                                         settings=settings)
        assert again == final
        assert len(facade.calls) == 3
        original = db.get(JobSearchRunRecord, "source-run")
        assert original.config_snapshot == original_snapshot
        assert original.screening_errors == 4
        assert original.jobs_added == 0
        records = db.scalars(select(StoredJobRecord)).all()
        assert len(records) == 2
        assert sum(record.status == "dismissed" for record in records) == 1
        recovery = db.get(JobSearchRunRecord, run_id)
        assert recovery.report["sources"][0]["fullCatalog"] is False
        assert "description" not in str(recovery.config_snapshot["screeningRecovery"])


def test_provider_failure_stops_and_same_recovery_retries_error(api_context: ApiContext, monkeypatch):
    class BrokenFacade:
        calls = 0

        def screen(self, _config, _jobs):
            self.calls += 1
            raise RuntimeError("Provider unavailable")

    facade = BrokenFacade()
    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: facade)
    settings = api_context.settings.model_copy(update={"job_screening_batch_size": 1})
    with api_context.sessions() as db:
        seed_failed_run(db)
        first = recover_failed_screening(db, source_run_id="source-run", settings=settings)
        assert first["errors"] == 1
        assert first["pending"] == 2
        assert facade.calls == 1
        good = FakeScreeningFacade({"Allowed": "keep", "Rejected": "reject", "Uncertain": "uncertain"})
        monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: good)
        final = recover_failed_screening(db, source_run_id="source-run", recovery_run_id=first["runId"],
                                         settings=settings)
        assert final["errors"] == 0
        assert final["added"] == 1
        assert final["screened"] == 3
        assert final["aiCalls"] == 4


def test_recovery_excludes_other_owner_and_other_time_window(api_context: ApiContext):
    with api_context.sessions() as db:
        source = seed_failed_run(db)
        errors = db.scalars(select(JobScreeningDecisionRecord).order_by(
            JobScreeningDecisionRecord.created_at,
        )).all()
        errors[0].created_at = source.completed_at + timedelta(seconds=1)
        errors[1].reason_code = "seniority_mismatch"
        db.commit()
        dry = recover_failed_screening(db, source_run_id=source.id, settings=api_context.settings,
                                       dry_run=True)
        assert dry["total"] == 2
        assert dry["eligible"] == 1
        token = current_owner_id.set("someone-else")
        try:
            with pytest.raises(ValueError, match="not found for this owner"):
                recover_failed_screening(db, source_run_id=source.id, settings=api_context.settings,
                                         dry_run=True)
        finally:
            current_owner_id.reset(token)


def test_parallel_workers_use_independent_sessions_and_serial_checkpoints(tmp_path, api_context, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.sqlite'}")
    Base.metadata.create_all(engine)
    barrier = Barrier(2)
    lock = Lock()
    calls = []

    class ConcurrentFacade(FakeScreeningFacade):
        def screen(self, config, jobs):
            with lock:
                calls.append((current_owner_id.get(), jobs[0]["title"]))
                number = len(calls)
            if number <= 2:
                barrier.wait(timeout=5)
            return super().screen(config, jobs)

    facade = ConcurrentFacade({"Allowed": "keep", "Rejected": "reject", "Uncertain": "uncertain"})
    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: facade)
    settings = api_context.settings.model_copy(update={"job_screening_batch_size": 1})
    with Session(engine) as db:
        seed_failed_run(db)
        result = recover_failed_screening(db, source_run_id="source-run", settings=settings, workers=2)
        assert result["status"] == "completed"
        assert result["added"] == 1
        assert result["screened"] == 3
        assert result["aiCalls"] == 3
        assert {owner for owner, _ in calls} == {"local-owner"}
    with Session(engine) as db:
        run = db.get(JobSearchRunRecord, result["runId"])
        assert run.jobs_added == 1
        assert len(db.scalars(select(StoredJobRecord)).all()) == 2
        assert db.get(JobSearchRunRecord, "source-run").jobs_added == 0


def test_parallel_failure_finishes_in_flight_without_submitting_more(tmp_path, api_context, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'failure.sqlite'}")
    Base.metadata.create_all(engine)
    barrier = Barrier(2)
    calls = []

    class PartlyBroken(FakeScreeningFacade):
        def screen(self, config, jobs):
            calls.append(jobs[0]["title"])
            barrier.wait(timeout=5)
            if jobs[0]["title"] == "Allowed":
                raise RuntimeError("Provider error")
            sleep(0.1)
            return super().screen(config, jobs)

    facade = PartlyBroken({"Rejected": "reject"})
    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: facade)
    settings = api_context.settings.model_copy(update={"job_screening_batch_size": 1})
    with Session(engine) as db:
        seed_failed_run(db)
        result = recover_failed_screening(db, source_run_id="source-run", settings=settings, workers=2)
        assert set(calls) == {"Allowed", "Rejected"}
        assert result["errors"] == 1
        assert result["rejected"] == 1
        assert result["pending"] == 1
    good = FakeScreeningFacade({"Allowed": "keep", "Uncertain": "uncertain"})
    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: good)
    with Session(engine) as db:
        final = recover_failed_screening(db, source_run_id="source-run", settings=settings, workers=2,
                                         recovery_run_id=result["runId"])
        assert final["errors"] == 0
        assert final["screened"] == 3
        assert final["added"] == 1


def test_worker_cache_survives_interrupted_main_checkpoint(tmp_path, api_context, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'checkpoint.sqlite'}")
    Base.metadata.create_all(engine)
    facade = FakeScreeningFacade({"Allowed": "keep", "Rejected": "reject", "Uncertain": "uncertain"})
    monkeypatch.setattr(job_search_execution, "create_job_screening_ai_facade", lambda _: facade)
    persist = job_screening_recovery.persist_new_jobs

    def interrupt_checkpoint(*args, **kwargs):
        raise RuntimeError("Interrupted before checkpoint")

    monkeypatch.setattr(job_screening_recovery, "persist_new_jobs", interrupt_checkpoint)
    settings = api_context.settings.model_copy(update={"job_screening_batch_size": 1})
    with Session(engine) as db:
        seed_failed_run(db)
        with pytest.raises(RuntimeError, match="Interrupted before checkpoint"):
            recover_failed_screening(db, source_run_id="source-run", settings=settings, workers=2)
        db.rollback()
    assert len(facade.calls) == 2
    monkeypatch.setattr(job_screening_recovery, "persist_new_jobs", persist)
    with Session(engine) as db:
        recovery = db.scalar(select(JobSearchRunRecord).where(JobSearchRunRecord.id != "source-run"))
        final = recover_failed_screening(db, source_run_id="source-run", settings=settings, workers=2,
                                         recovery_run_id=recovery.id)
        assert final["status"] == "completed"
        assert final["added"] == 1
        # The two committed worker decisions are reused rather than sent again.
        assert len(facade.calls) == 3
