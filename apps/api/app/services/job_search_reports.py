"""Build a historical snapshot from observed pipeline outcomes, never from live Jobs."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vacancy_sources import direct_company_definition
from app.models.job_search import JobSearchRunRecord
from app.models.parsers import LinkedInSearchRequest, ParsedJob
from app.services.discovered_vacancies import (
    DiscoveredVacancySnapshot,
    DiscoveredVacancyUpsertResult,
)
from app.services.job_screening import JobScreeningDecision
from app.services.vacancy_search import (
    VacancySearchRunResult,
    canonical_job_url,
    filter_jobs_by_date_posted,
    job_identity,
)


def vacancy_snapshot(job: ParsedJob, *, job_id: str | None = None) -> dict[str, Any]:
    return {
        "jobId": job_id,
        "title": job.title or "Untitled vacancy",
        "company": job.company or "",
        "location": job.location or "",
        "url": job.url or job.apply_url or "",
        "source": job.source,
    }


def catalog_disappearances(
    db: Session,
    *,
    run: JobSearchRunRecord,
    result: VacancySearchRunResult,
    fallback: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Compare complete per-source sightings, including cross-source duplicates.

    The legacy inventory stores one canonical source. New reports retain every
    source occurrence and therefore provide a more accurate catalog baseline.
    """
    missing = dict(fallback)
    pending = set(fallback)
    if not pending:
        return missing
    previous_runs = db.scalars(
        select(JobSearchRunRecord)
        .where(
            JobSearchRunRecord.owner_id == run.owner_id,
            JobSearchRunRecord.id != run.id,
            JobSearchRunRecord.started_at < run.started_at,
            JobSearchRunRecord.report_version == 1,
        )
        .order_by(JobSearchRunRecord.started_at.desc(), JobSearchRunRecord.id.desc())
    )
    for previous in previous_runs:
        if not pending.intersection(previous.sources):
            continue
        report = previous.report
        if not report or report.get("detailsRemoved"):
            continue
        complete = {
            source["source"] for source in report.get("sources", []) if source.get("fullCatalog")
        } & pending
        for source in complete:
            current_jobs = result.source_results[source].jobs
            urls = {canonical_job_url(job.url or job.apply_url) for job in current_jobs}
            identities = {job_identity(job) for job in current_jobs}
            removed: dict[str, dict[str, Any]] = {}
            for row in report.get("vacancies", []):
                if (
                    row["source"] != source
                    or row["outcome"] == "missing"
                    or row.get("reasonCode") == "invalid_record"
                ):
                    continue
                job = ParsedJob.model_validate(row)
                url = canonical_job_url(job.url or job.apply_url)
                identity = job_identity(job)
                if (url and url in urls) or (identity and identity in identities):
                    continue
                removed[url or identity] = vacancy_snapshot(job, job_id=row.get("jobId"))
            missing[source] = list(removed.values())
        pending -= complete
        if not pending:
            break
    return missing


def build_search_report(
    *,
    sources: list[str],
    result: VacancySearchRunResult,
    inventory: DiscoveredVacancyUpsertResult,
    candidate_ids: set[str],
    request: LinkedInSearchRequest,
    source_requests: dict[str, LinkedInSearchRequest],
    missing: dict[str, list[dict[str, Any]]],
    decisions: list[JobScreeningDecision] | None = None,
    added_ids: set[str] | None = None,
) -> dict[str, Any]:
    by_url: dict[str, DiscoveredVacancySnapshot] = {}
    by_identity: dict[str, DiscoveredVacancySnapshot] = {}
    first_observation: dict[str, DiscoveredVacancySnapshot] = {}
    for item in inventory.vacancies:
        primary = first_observation.setdefault(item.job_id, item)
        if url := canonical_job_url(item.job.url or item.job.apply_url):
            by_url.setdefault(url, primary)
        if identity := job_identity(item.job):
            by_identity.setdefault(identity, primary)
    decision_by_id = {decision.id: decision for decision in decisions or []}
    claimed: set[str] = set()
    source_reports: list[dict[str, Any]] = []
    vacancies: list[dict[str, Any]] = []
    for source in sources:
        response = result.source_results.get(source)
        # Compatibility with injected runners that return only a merged result.
        jobs = response.jobs if response else [job for job in result.jobs if job.source == source]
        error = result.source_errors.get(source)
        definition = direct_company_definition(source)
        full_catalog = bool(
            definition
            and definition.full_catalog
            and response
            and response.status == "completed"
            and not error
        )
        rows: list[dict[str, Any]] = []
        for job in jobs:
            row = vacancy_snapshot(job)
            row.update(source=source, discovery=None, outcome="pending", reason="")
            snapshot = by_url.get(canonical_job_url(job.url or job.apply_url)) or (
                by_identity.get(job_identity(job))
            )
            if not filter_jobs_by_date_posted(
                [job],
                request=request,
                source_requests=source_requests,
            ):
                row.update(
                    outcome="filtered",
                    reason="Outside the selected publication window.",
                    reasonCode="posting_age",
                )
            elif snapshot is None:
                row.update(
                    outcome="error",
                    reason="No usable inventory record was produced.",
                    reasonCode="inventory_error",
                )
            else:
                row["jobId"] = snapshot.job_id
                if snapshot.job_id in claimed or snapshot.job.source != source:
                    row.update(
                        outcome="duplicate",
                        reason="The same vacancy was returned elsewhere in this search.",
                    )
                else:
                    claimed.add(snapshot.job_id)
                    row["discovery"] = (
                        "new"
                        if snapshot.is_new
                        else "updated"
                        if snapshot.content_changed
                        else "observed"
                    )
                    decision = decision_by_id.get(snapshot.job_id)
                    if snapshot.job_id not in candidate_ids:
                        row.update(outcome="known", reason="Already in your Jobs list.")
                    elif decision is not None:
                        row.update(
                            outcome=(
                                "error"
                                if decision.reason_code == "screening_error"
                                else {
                                    "keep": "pending",
                                    "reject": "filtered",
                                    "uncertain": "uncertain",
                                }[decision.decision]
                            ),
                            reason=decision.reason,
                            reasonCode=decision.reason_code,
                        )
                    if added_ids is not None and row["outcome"] == "pending":
                        row["outcome"] = "added" if snapshot.job_id in added_ids else "known"
                        if not row["reason"]:
                            row["reason"] = (
                                "Added to your Jobs list."
                                if row["outcome"] == "added"
                                else "Already present when results were saved."
                            )
            rows.append(row)
        invalid_jobs = result.source_invalid_jobs.get(source, [])
        rows.extend(
            {
                **vacancy_snapshot(job),
                "source": source,
                "outcome": "error",
                "discovery": None,
                "reasonCode": "invalid_record",
                "reason": "The source returned a record without a usable title or URL.",
            }
            for job in invalid_jobs
        )
        missing_rows = [
            {
                **row,
                "outcome": "missing",
                "discovery": None,
                "reason": "Absent from a successful complete company catalog scan.",
            }
            for row in missing.get(source, [])
        ]
        source_reports.append(
            {
                "source": source,
                "status": (
                    "partial"
                    if error and rows
                    else "failed"
                    if error
                    else "completed"
                    if response is None or response.status == "completed"
                    else "partial"
                ),
                "received": len(rows) if response is not None or jobs else None,
                "firstSeen": sum(row["discovery"] == "new" for row in rows),
                "updated": sum(row["discovery"] == "updated" for row in rows),
                "observed": sum(row["discovery"] == "observed" for row in rows),
                **{
                    outcome: sum(row["outcome"] == outcome for row in rows)
                    for outcome in (
                        "added",
                        "known",
                        "duplicate",
                        "filtered",
                        "uncertain",
                        "error",
                        "pending",
                    )
                },
                "missing": len(missing_rows) if full_catalog else None,
                "fullCatalog": full_catalog,
                "attempts": result.source_attempts.get(source),
                "durationSeconds": result.source_durations.get(source),
                "errorMessage": error,
                "warnings": list(response.warnings) if response else [],
            }
        )
        vacancies.extend([*rows, *missing_rows])
    return {"version": 1, "sources": source_reports, "vacancies": vacancies}
