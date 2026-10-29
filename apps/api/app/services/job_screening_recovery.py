"""Resume failed screening from saved discovery, without running any parsers."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identity import current_owner_id, get_bound_owner_id
from app.core.settings import Settings
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.job_search import JobSearchRunRecord, ScreeningConfig, normalize_job_search_config
from app.models.jobs import DiscoveredVacancyRecord
from app.models.parsers import ParsedJob
from app.services.ai_privacy import ensure_ai_privacy_settings
from app.services.job_screening import JOB_SCREENING_PROMPT_VERSION
from app.services.job_screening_store import build_screening_config_hash
from app.services.job_search_execution import (
    JobImportProvenance,
    NewJobCandidate,
    ScreeningPipelineResult,
    persist_new_jobs,
    prepare_new_job_candidates,
    screen_candidates_by_source,
)
from app.services.job_search_reports import vacancy_snapshot

RECOVERY_KEY = "screeningRecovery"


def recovery_plan(db: Session, source: JobSearchRunRecord) -> list[dict[str, Any]]:
    """Old decisions lack run IDs: require both the time window and inventory link."""
    if source.owner_id != get_bound_owner_id():
        raise ValueError("Source search belongs to another owner")
    if source.completed_at is None or source.status in {"running", "queued"}:
        raise ValueError("Source search must have finished")
    decisions = db.scalars(select(JobScreeningDecisionRecord).where(
        JobScreeningDecisionRecord.owner_id == source.owner_id,
        JobScreeningDecisionRecord.reason_code == "screening_error",
        JobScreeningDecisionRecord.created_at >= source.started_at,
        JobScreeningDecisionRecord.created_at <= source.completed_at,
    ).order_by(JobScreeningDecisionRecord.created_at, JobScreeningDecisionRecord.id)).all()
    inventory = {
        record.id: record for record in db.scalars(select(DiscoveredVacancyRecord).where(
            DiscoveredVacancyRecord.owner_id == source.owner_id,
            DiscoveredVacancyRecord.last_seen_run_id == source.id,
        )).all()
    }
    # A repeated catalog observation can share one inventory ID and decision.
    by_job = {decision.job_id: decision for decision in decisions}
    plan = []
    for job_id, decision in by_job.items():
        record = inventory.get(job_id)
        if record is None or record.source not in source.sources:
            continue
        job = ParsedJob.model_validate(record.data)
        plan.append({
            "decisionId": decision.id,
            "jobId": job_id,
            "job": job.model_dump(mode="json"),
            "compact": deepcopy(decision.vacancy_data) or None,
        })
    return plan


def summarize_recovery(run: JobSearchRunRecord) -> dict[str, Any]:
    rows = (run.report or {}).get("vacancies", [])
    return {
        "runId": run.id,
        "status": run.status,
        "total": run.jobs_found,
        "screened": run.jobs_screened,
        "added": run.jobs_added,
        "rejected": run.jobs_rejected,
        "uncertain": run.jobs_uncertain,
        "errors": run.screening_errors,
        "known": run.jobs_already_known,
        "pending": sum(row["outcome"] == "pending" for row in rows),
        "aiCalls": run.jobs_screening_ai_calls,
    }


def refresh_recovery_report(run: JobSearchRunRecord, rows: list[dict[str, Any]]) -> None:
    source_rows = []
    for source in run.sources:
        group = [row for row in rows if row["source"] == source]
        counts = Counter(row["outcome"] for row in group)
        source_rows.append({
            "source": source,
            "status": "partial" if counts["error"] or counts["pending"] else "completed",
            "received": len(group),
            "firstSeen": 0,
            "updated": 0,
            "observed": len(group),
            **{key: counts[key] for key in (
                "added", "known", "duplicate", "filtered", "uncertain", "error", "pending",
            )},
            "missing": None,
            "fullCatalog": False,
            "attempts": None,
            "durationSeconds": None,
            "errorMessage": None,
            "warnings": ["AI screening retry using saved vacancies; no website scan."],
        })
    run.report = {"version": 1, "sources": source_rows, "vacancies": rows}
    run.jobs_screened = sum(bool(row.get("screeningDecision")) for row in rows)
    run.jobs_passed = sum(row.get("screeningDecision") == "keep" for row in rows)
    run.jobs_rejected = sum(row.get("screeningDecision") == "reject" for row in rows)
    run.jobs_uncertain = sum(row.get("screeningDecision") == "uncertain" for row in rows)
    run.screening_errors = sum(row.get("reasonCode") == "screening_error" for row in rows)
    run.jobs_added = sum(row["outcome"] == "added" for row in rows)
    run.jobs_already_known = sum(row["outcome"] == "known" for row in rows)


def recover_failed_screening(
    db: Session,
    *,
    source_run_id: str,
    settings: Settings,
    recovery_run_id: str | None = None,
    dry_run: bool = False,
    max_batches: int | None = None,
    workers: int = 1,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Commit each batch atomically; a resumed run retries pending/error rows only."""
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be positive")
    if not 1 <= workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    source = db.scalar(select(JobSearchRunRecord).where(
        JobSearchRunRecord.id == source_run_id,
        JobSearchRunRecord.owner_id == get_bound_owner_id(),
    ))
    if source is None:
        raise ValueError("Source search not found for this owner")
    if recovery_run_id:
        run = db.scalar(select(JobSearchRunRecord).where(
            JobSearchRunRecord.id == recovery_run_id,
            JobSearchRunRecord.owner_id == get_bound_owner_id(),
        ))
        meta = (run.config_snapshot if run else {}).get(RECOVERY_KEY, {})
        if meta.get("sourceRunId") != source.id:
            raise ValueError("Recovery run does not belong to this source search")
        if meta.get("model") != settings.job_screening_model:
            raise ValueError("Resume must use the original recovery model")
        if meta.get("promptVersion") != JOB_SCREENING_PROMPT_VERSION:
            raise ValueError("Screening prompt changed; start a new recovery")
        if not run.report or run.report.get("detailsRemoved"):
            raise ValueError("Recovery details have been removed by privacy retention")
        # Reuse retained audit/inventory data. Do not copy descriptions into the
        # configuration summary, which outlives AI data deletion/retention.
        available = {item["decisionId"]: item for item in recovery_plan(db, source)}
        if any(item["decisionId"] not in available for item in meta["items"]):
            raise ValueError("Recovery inputs changed or expired; start a new recovery")
        plans = [available[item["decisionId"]] for item in meta["items"]]
        rows = deepcopy(run.report["vacancies"])
    else:
        plans = recovery_plan(db, source)
        jobs = [ParsedJob.model_validate(item["job"]) for item in plans]
        candidates, known = prepare_new_job_candidates(
            db, jobs=jobs, resolved_job_ids=[item["jobId"] for item in plans],
        )
        candidate_ids = {item.job_id for item in candidates}
        if dry_run:
            return {
                "sourceRunId": source.id, "model": settings.job_screening_model,
                "total": len(plans), "eligible": len(candidates), "known": known,
                "dryRun": True,
            }
        rows = [{
            **vacancy_snapshot(job, job_id=item["jobId"]),
            "discovery": "observed",
            "outcome": "pending" if item["jobId"] in candidate_ids else "known",
            "reason": "Awaiting AI screening retry." if item["jobId"] in candidate_ids
            else "Already stored, dismissed, or duplicated in this retry.",
        } for item, job in zip(plans, jobs, strict=True)]
        snapshot = deepcopy(source.config_snapshot)
        snapshot["name"] = f"{snapshot.get('name', 'Search')} — AI screening retry"
        snapshot[RECOVERY_KEY] = {
            "sourceRunId": source.id,
            "model": settings.job_screening_model,
            "promptVersion": JOB_SCREENING_PROMPT_VERSION,
            "items": [{"decisionId": item["decisionId"], "jobId": item["jobId"]}
                      for item in plans],
        }
        run = JobSearchRunRecord(
            id=uuid4().hex, session_id=uuid4().hex, owner_id=source.owner_id,
            run_type="manual", config_snapshot=snapshot,
            sources=list(dict.fromkeys(job.source for job in jobs)),
            status="running", report_version=1,
            jobs_found=len(plans), jobs_already_observed=len(plans),
            jobs_screening_ai_calls=0, source_errors={}, started_at=datetime.now(UTC),
        )
        refresh_recovery_report(run, rows)
        db.add(run)
        db.commit()

    if dry_run:
        return {**summarize_recovery(run), "dryRun": True}
    config = normalize_job_search_config(run.config_snapshot["filters"])
    if not config.screening.enabled:
        raise ValueError("Recovery requires the original screening to be enabled")
    policies = {
        key: ScreeningConfig.model_validate(value)
        for key, value in run.config_snapshot.get("sourceScreening", {}).items()
    }
    by_id = {item["jobId"]: item for item in plans}
    row_by_id = {row["jobId"]: row for row in rows}
    pending_ids = [row["jobId"] for row in rows if row["outcome"] in {"pending", "error"}]
    search_config_id = run.config_snapshot.get("id")
    search_config_version = run.config_snapshot.get("updatedAt")
    owner_id = get_bound_owner_id()
    # Seed once before concurrent sessions can race to create this owner record.
    if workers > 1 and pending_ids:
        ensure_ai_privacy_settings(db, owner_id)
    run.status = "running"
    run.completed_at = None
    run.warning = None
    db.commit()
    if on_progress:
        on_progress(summarize_recovery(run))

    def prepare_batch(ids: list[str]) -> list[NewJobCandidate]:
        jobs = [ParsedJob.model_validate(by_id[job_id]["job"]) for job_id in ids]
        candidates, _ = prepare_new_job_candidates(db, jobs=jobs, resolved_job_ids=ids)
        eligible_ids = {item.job_id for item in candidates}
        for job_id in set(ids) - eligible_ids:
            row_by_id[job_id].update(
                outcome="known", reason="Already stored or dismissed before retry.",
            )
            row_by_id[job_id].pop("reasonCode", None)
            row_by_id[job_id].pop("screeningDecision", None)
        return [NewJobCandidate(
            job=item.job, job_id=item.job_id, compact_data=by_id[item.job_id]["compact"],
        ) for item in candidates]

    def screen_batch(target_db: Session, candidates: list[NewJobCandidate]) -> ScreeningPipelineResult:
        return screen_candidates_by_source(
            target_db, candidates=candidates, screening_config=config.screening,
            source_screening_configs=policies, settings=settings,
            rolling_posting_age=config.screening.max_posting_age_days is not None,
            search_config_id=search_config_id,
        )

    def save_batch(candidates: list[NewJobCandidate], result: ScreeningPipelineResult) -> None:
        # All writes to Jobs and the recovery report stay on the main thread.
        candidate_policies = {
            item.job_id: policies.get(item.job.source, config.screening) for item in candidates
        }
        added = persist_new_jobs(
            db, jobs=result.keep, added_at=datetime.now(UTC),
            candidate_provenance={
                job_id: JobImportProvenance(
                    search_config_id=search_config_id,
                    search_config_version=search_config_version,
                    screening_config_hash=build_screening_config_hash(policy),
                    screening_config_snapshot=policy.model_dump(by_alias=True, exclude_none=True),
                ) for job_id, policy in candidate_policies.items()
            },
        )
        added_ids = {job["id"] for job in added}
        for decision in result.decisions:
            outcome = (
                "error" if decision.reason_code == "screening_error"
                else "added" if decision.id in added_ids
                else {"keep": "known", "reject": "filtered", "uncertain": "uncertain"}[
                    decision.decision
                ]
            )
            row_by_id[decision.id].update(
                outcome=outcome, reason=decision.reason, reasonCode=decision.reason_code,
                screeningDecision=decision.decision,
            )
        run.jobs_screening_ai_calls += result.jobs_screening_ai_calls
        refresh_recovery_report(run, rows)
        db.commit()
        if on_progress:
            on_progress(summarize_recovery(run))

    batches = [pending_ids[offset:offset + settings.job_screening_batch_size]
               for offset in range(0, len(pending_ids), settings.job_screening_batch_size)]
    if max_batches is not None:
        batches = batches[:max_batches]
    if workers == 1:
        for ids in batches:
            candidates = prepare_batch(ids)
            result = screen_batch(db, candidates)
            save_batch(candidates, result)
            if result.screening_errors:
                break
    else:
        worker_engine = db.get_bind().engine

        def run_worker(candidates: list[NewJobCandidate]) -> ScreeningPipelineResult:
            token = current_owner_id.set(owner_id)
            try:
                with Session(bind=worker_engine, autoflush=False) as worker_db:
                    result = screen_batch(worker_db, candidates)
                    # A crash before the main checkpoint is recoverable from the
                    # normal decision cache; no unverified vacancy is added here.
                    worker_db.commit()
                    return result
            finally:
                current_owner_id.reset(token)

        remaining = iter(batches)
        in_flight: dict[Future[ScreeningPipelineResult], list[NewJobCandidate]] = {}
        stop_submitting = False
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="screening-retry") as pool:
            while True:
                while not stop_submitting and len(in_flight) < workers:
                    ids = next(remaining, None)
                    if ids is None:
                        break
                    candidates = prepare_batch(ids)
                    in_flight[pool.submit(run_worker, candidates)] = candidates
                if not in_flight:
                    break
                finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in finished:
                    candidates = in_flight.pop(future)
                    result = future.result()
                    save_batch(candidates, result)
                    stop_submitting = stop_submitting or bool(result.screening_errors)
                # After an error, finish/checkpoint only the already running
                # batches, without submitting any additional external requests.

    unfinished = any(row["outcome"] in {"pending", "error"} for row in rows)
    run.status = "partial" if unfinished else "completed"
    run.completed_at = datetime.now(UTC)
    run.warning = (
        "AI screening retry stopped after an error; resume this recovery after fixing the provider."
        if run.screening_errors else "AI screening retry paused; resume to process remaining vacancies."
        if unfinished else None
    )
    db.commit()
    return summarize_recovery(run)
