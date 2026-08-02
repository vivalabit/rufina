from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identity import get_bound_owner_id
from app.core.settings import Settings
from app.core.vacancy_sources import (
    AGGREGATOR_SOURCE_IDS,
    SUPPORTED_VACANCY_SOURCE_IDS,
    direct_company_definition,
)
from app.models.job_search import (
    JobSearchConfigRecord,
    JobSearchConfigV2,
    JobSearchRunRecord,
    JobSearchScheduleRecord,
    JobSourceConfigRecord,
    ScreeningConfig,
    SearchFilters,
    normalize_job_search_config,
)
from app.models.jobs import StoredJobRecord
from app.models.parsers import LinkedInSearchRequest, ParsedJob
from app.models.profile import ProfilePayload, ProfileRecord
from app.services.ai_match import AiMatchError, create_vacancy_matching_ai_facade
from app.services.ai_privacy import (
    has_current_ai_consent,
    privacy_settings_record,
)
from app.services.candidate_snapshot import (
    CandidateSnapshotError,
    get_candidate_match_snapshot,
)
from app.services.discovered_vacancies import (
    DiscoveredVacancyUpsertResult,
    compact_screening_data,
    mark_missing_vacancies_inactive,
    stable_job_id,
    upsert_discovered_vacancies,
)
from app.services.job_match_store import persist_job_and_match
from app.services.job_screening import (
    JOB_SCREENING_PROMPT_VERSION,
    JobScreeningDecision,
    JobScreeningPayload,
    create_job_screening_ai_facade,
    deterministic_seniority_decision,
    normalize_screening_decisions,
    screening_rule_ids,
    uncertain_or_keep_decision,
)
from app.services.job_screening_store import (
    build_screening_config_hash,
    build_screening_vacancy_hash,
    latest_screening_decision,
    persist_screening_decision,
)
from app.services.job_search_schedule import calculate_next_run_at
from app.services.vacancy_search import (
    VacancySearchRunner,
    VacancySearchRunResult,
    canonical_job_url,
    job_identity,
    normalize_identity_part,
)

AI_CONSENT_WARNING = "AI Match was skipped because current AI data-processing consent is missing"
SCREENING_CONSENT_WARNING = (
    "Vacancy screening was skipped because current AI data-processing consent is missing"
)

EXPERIENCE_LEVEL_SENIORITY = {
    "Entry level": ["intern", "entry", "junior"],
    "Associate": ["associate"],
    "Mid-Senior level": ["mid", "senior", "lead"],
    "Director": ["director", "executive"],
}


class JobSearchExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobSearchExecutionResult:
    run: JobSearchRunRecord
    warning: str | None = None


@dataclass(frozen=True)
class NewJobCandidate:
    job: ParsedJob
    job_id: str
    compact_data: dict[str, Any] | None = None


@dataclass(frozen=True)
class JobImportProvenance:
    search_config_id: str | None
    search_config_version: str | None
    screening_config_hash: str
    screening_config_snapshot: dict[str, Any]


@dataclass(frozen=True)
class ScreeningPipelineResult:
    keep: list[NewJobCandidate]
    decisions: list[JobScreeningDecision] = field(default_factory=list)
    jobs_screened: int = 0
    jobs_passed: int = 0
    jobs_rejected: int = 0
    jobs_uncertain: int = 0
    screening_errors: int = 0
    jobs_screening_ai_calls: int = 0
    warning: str | None = None


def effective_screening_config(
    config: JobSearchConfigV2,
    *,
    screening_required: bool,
) -> ScreeningConfig:
    screening = config.screening
    derived_levels = EXPERIENCE_LEVEL_SENIORITY.get(
        config.search.experience_level,
        [],
    )
    allowed_seniority = list(screening.allowed_seniority)
    if not allowed_seniority and derived_levels:
        allowed_seniority = [
            level
            for level in derived_levels
            if level not in screening.excluded_seniority
        ]

    target_roles = list(screening.target_roles)
    if screening_required and not target_roles and config.search.keywords:
        target_roles = [config.search.keywords]

    return ScreeningConfig.model_validate(
        {
            **screening.model_dump(by_alias=True),
            "enabled": bool(
                screening.enabled or screening_required or derived_levels
            ),
            "targetRoles": target_roles,
            "allowedSeniority": allowed_seniority,
        }
    )


def execute_job_search(
    db: Session,
    *,
    schedule: JobSearchScheduleRecord | None,
    config: JobSearchConfigRecord | None,
    runner: VacancySearchRunner,
    settings: Settings,
    run_type: Literal["manual", "automatic"],
    config_snapshot: dict[str, Any] | None = None,
    sources: list[str] | None = None,
    source_configs: dict[str, JobSourceConfigRecord] | None = None,
    ai_analysis_enabled: bool | None = None,
    scheduled_for: datetime | None = None,
    now: datetime | None = None,
    reserved_run: JobSearchRunRecord | None = None,
    recalculate_schedule: bool = True,
    screening_required: bool = False,
) -> JobSearchExecutionResult:
    started_at = now or datetime.now(UTC)
    if config_snapshot is None:
        if config is None:
            raise ValueError("config or config_snapshot is required")
        config_snapshot = build_config_snapshot(
            config,
            source_configs=source_configs,
        )
    elif source_configs:
        config_snapshot = {
            **config_snapshot,
            "sourceConfigs": build_source_config_snapshots(source_configs),
        }
    run_sources = list(sources if sources is not None else schedule.sources if schedule else [])
    if not run_sources:
        raise ValueError("at least one job search source is required")
    if reserved_run is None:
        run = JobSearchRunRecord(
            id=uuid4().hex,
            schedule_id=schedule.id if schedule else None,
            run_type=run_type,
            scheduled_for=scheduled_for,
            config_snapshot=config_snapshot,
            sources=run_sources,
            status="running",
            jobs_found=0,
            jobs_added=0,
            source_errors={},
            started_at=started_at,
        )
        db.add(run)
    else:
        run = reserved_run
        run.status = "running"
        run.jobs_found = 0
        run.jobs_already_known = 0
        run.jobs_discovered_new = 0
        run.jobs_discovered_updated = 0
        run.jobs_already_observed = 0
        run.jobs_screened = 0
        run.jobs_passed = 0
        run.jobs_rejected = 0
        run.jobs_uncertain = 0
        run.jobs_added = 0
        run.jobs_analyzed = 0
        run.screening_errors = 0
        run.jobs_screening_ai_calls = 0
        run.warning = None
        run.source_errors = {}
        run.started_at = started_at
        run.completed_at = None
    db.commit()

    try:
        config_data = run.config_snapshot.get(
            "filters",
            config.filters if config is not None else {},
        )
        normalized_config = normalize_job_search_config(config_data)
        normalized_config = normalized_config.model_copy(
            update={
                "screening": effective_screening_config(
                    normalized_config,
                    screening_required=screening_required,
                )
            }
        )
        run.config_snapshot = {
            **run.config_snapshot,
            "filters": normalized_config.model_dump(
                by_alias=True,
                exclude_none=True,
            ),
        }
        request = search_request_from_config(
            run.config_snapshot["filters"],
        )
        source_requests = source_requests_from_snapshot(
            run.config_snapshot,
        )
        search_result = runner.run(
            sources=list(run.sources),
            request=request,
            source_requests=source_requests,
            wait_for_snapshots=True,
        )
    except (TypeError, ValidationError, ValueError) as exc:
        completed_at = datetime.now(UTC)
        finish_failed_run(
            run,
            schedule,
            completed_at=completed_at,
            source_errors={"config": str(exc)[:500]},
            recalculate_schedule=recalculate_schedule,
        )
        db.commit()
        raise JobSearchExecutionError("Stored job search config is invalid") from exc
    except Exception as exc:
        completed_at = datetime.now(UTC)
        finish_failed_run(
            run,
            schedule,
            completed_at=completed_at,
            source_errors={"runner": str(exc)[:500]},
            recalculate_schedule=recalculate_schedule,
        )
        db.commit()
        raise

    discovered_at = datetime.now(UTC)
    inventory_result = upsert_discovered_vacancies(
        db,
        jobs=search_result.jobs,
        run_id=run.id,
        seen_at=discovered_at,
        max_description_chars=settings.job_screening_max_description_chars,
    )
    reconcile_full_catalog_inventory(
        db,
        search_result=search_result,
        inventory_result=inventory_result,
        unavailable_at=discovered_at,
    )
    run.jobs_found = len(search_result.jobs)
    run.jobs_discovered_new = inventory_result.jobs_discovered_new
    run.jobs_discovered_updated = inventory_result.jobs_discovered_updated
    run.jobs_already_observed = inventory_result.jobs_already_observed
    run.source_errors = search_result.source_errors
    db.commit()

    candidates, jobs_already_known = prepare_new_job_candidates(
        db,
        jobs=[snapshot.job for snapshot in inventory_result.vacancies],
        resolved_job_ids=[
            snapshot.job_id for snapshot in inventory_result.vacancies
        ],
    )
    screening_result = screen_new_job_candidates(
        db,
        candidates=candidates,
        screening_config=normalized_config.screening,
        settings=settings,
        search_config_id=(
            config.id
            if config is not None
            else str(run.config_snapshot.get("id") or "") or None
        ),
    )
    persisted_at = datetime.now(UTC)
    new_jobs = persist_new_jobs(
        db,
        jobs=screening_result.keep,
        added_at=persisted_at,
        provenance=JobImportProvenance(
            search_config_id=(
                config.id
                if config is not None
                else str(run.config_snapshot.get("id") or "") or None
            ),
            search_config_version=(
                str(run.config_snapshot.get("updatedAt") or "") or None
            ),
            screening_config_hash=build_screening_config_hash(
                normalized_config.screening
            ),
            screening_config_snapshot=normalized_config.screening.model_dump(
                by_alias=True,
                exclude_none=True,
            ),
        ),
    )
    run.jobs_already_known = jobs_already_known
    run.jobs_screened = screening_result.jobs_screened
    run.jobs_passed = screening_result.jobs_passed
    run.jobs_rejected = screening_result.jobs_rejected
    run.jobs_uncertain = screening_result.jobs_uncertain
    run.jobs_added = len(new_jobs)
    run.jobs_analyzed = 0
    run.screening_errors = screening_result.screening_errors
    run.jobs_screening_ai_calls = screening_result.jobs_screening_ai_calls
    run.warning = screening_result.warning
    run.source_errors = search_result.source_errors
    run.status = (
        "partial"
        if screening_result.screening_errors
        else run_status(search_result)
    )
    db.commit()

    analysis_enabled = (
        ai_analysis_enabled
        if ai_analysis_enabled is not None
        else schedule.ai_analysis_enabled if schedule else False
    )
    match_warning = match_new_jobs_if_allowed(
        db,
        jobs=new_jobs,
        enabled=analysis_enabled,
        settings=settings,
        owner_id=get_bound_owner_id(),
    )
    run.jobs_analyzed = (
        len(new_jobs)
        if analysis_enabled and new_jobs and match_warning is None
        else 0
    )
    run.warning = combine_warnings(screening_result.warning, match_warning)
    completed_at = datetime.now(UTC)
    run.completed_at = completed_at
    if schedule is not None:
        schedule.last_run_at = completed_at
        if recalculate_schedule:
            recalculate_next_schedule_run(schedule, now=completed_at)
        schedule.updated_at = completed_at
    db.commit()
    db.refresh(run)
    return JobSearchExecutionResult(run=run, warning=run.warning)


def finish_failed_run(
    run: JobSearchRunRecord,
    schedule: JobSearchScheduleRecord | None,
    *,
    completed_at: datetime,
    source_errors: dict[str, str],
    recalculate_schedule: bool,
) -> None:
    run.status = "failed"
    run.warning = None
    run.source_errors = source_errors
    run.completed_at = completed_at
    if schedule is not None:
        schedule.last_run_at = completed_at
        if recalculate_schedule:
            recalculate_next_schedule_run(schedule, now=completed_at)
        schedule.updated_at = completed_at


def recalculate_next_schedule_run(
    schedule: JobSearchScheduleRecord,
    *,
    now: datetime,
) -> None:
    if not schedule.enabled:
        schedule.next_run_at = None
        return
    schedule.next_run_at = calculate_next_run_at(
        frequency=schedule.frequency,
        weekdays=schedule.weekdays,
        local_time=schedule.local_time,
        timezone=schedule.timezone,
        now=now,
    )


def search_request_from_config(
    config: dict[str, Any] | JobSearchConfigV2,
) -> LinkedInSearchRequest:
    normalized = (
        config
        if isinstance(config, JobSearchConfigV2)
        else normalize_job_search_config(config)
    )
    parser_fields = {
        key: value
        for key, value in normalized.search.model_dump().items()
        if key in LinkedInSearchRequest.model_fields
    }
    return LinkedInSearchRequest.model_validate(parser_fields)


def build_config_snapshot(
    config: JobSearchConfigRecord,
    *,
    source_configs: dict[str, JobSourceConfigRecord] | None = None,
) -> dict[str, Any]:
    try:
        normalized_config = normalize_job_search_config(config.filters).model_dump(
            by_alias=True,
            exclude_none=True,
        )
    except ValidationError:
        normalized_config = deepcopy(config.filters)
    snapshot = {
        "id": config.id,
        "name": config.name,
        "filters": normalized_config,
        "createdAt": serialize_datetime(config.created_at),
        "updatedAt": serialize_datetime(config.updated_at),
    }
    if source_configs:
        snapshot["sourceConfigs"] = build_source_config_snapshots(source_configs)
    return snapshot


def build_source_config_snapshots(
    source_configs: dict[str, JobSourceConfigRecord],
) -> dict[str, dict[str, Any]]:
    return {
        source: {
            "id": record.id,
            "name": record.name,
            "source": record.source,
            "filters": deepcopy(record.filters),
            "createdAt": serialize_datetime(record.created_at),
            "updatedAt": serialize_datetime(record.updated_at),
        }
        for source, record in source_configs.items()
    }


def source_requests_from_snapshot(
    snapshot: dict[str, Any],
) -> dict[str, LinkedInSearchRequest]:
    raw_source_configs = snapshot.get("sourceConfigs")
    if not isinstance(raw_source_configs, dict):
        return {}
    requests: dict[str, LinkedInSearchRequest] = {}
    for source, raw_config in raw_source_configs.items():
        if not isinstance(source, str) or not isinstance(raw_config, dict):
            continue
        filters = raw_config.get("filters")
        if not isinstance(filters, dict):
            raise TypeError(f"Source config for {source} has invalid filters")
        normalized = SearchFilters.model_validate(filters)
        parser_fields = {
            key: value
            for key, value in normalized.model_dump().items()
            if key in LinkedInSearchRequest.model_fields
        }
        requests[source] = LinkedInSearchRequest.model_validate(parser_fields)
    return requests


def reconcile_full_catalog_inventory(
    db: Session,
    *,
    search_result: VacancySearchRunResult,
    inventory_result: DiscoveredVacancyUpsertResult,
    unavailable_at: datetime,
) -> None:
    seen_job_ids = {
        snapshot.job_id for snapshot in inventory_result.vacancies
    }
    for source, source_result in search_result.source_results.items():
        definition = direct_company_definition(source)
        if (
            definition is None
            or not definition.full_catalog
            or source in search_result.source_errors
            or source_result.status != "completed"
        ):
            continue
        mark_missing_vacancies_inactive(
            db,
            source=source,
            seen_job_ids=seen_job_ids,
            unavailable_at=unavailable_at,
        )


def prepare_new_job_candidates(
    db: Session,
    *,
    jobs: list[ParsedJob],
    resolved_job_ids: list[str] | None = None,
) -> tuple[list[NewJobCandidate], int]:
    if resolved_job_ids is not None and len(resolved_job_ids) != len(jobs):
        raise ValueError("resolved_job_ids must match jobs")
    records = db.scalars(select(StoredJobRecord)).all()
    existing_ids = {record.id for record in records}
    existing_urls = {
        canonical_job_url(stored_job_url(record.data))
        for record in records
        if canonical_job_url(stored_job_url(record.data))
    }
    existing_identities = {
        stored_job_identity(record.data) for record in records if stored_job_identity(record.data)
    }
    candidates: list[NewJobCandidate] = []

    for index, job in enumerate(jobs):
        job_id = (
            resolved_job_ids[index]
            if resolved_job_ids is not None
            else parsed_job_id(job, index=index)
        )
        url_key = canonical_job_url(job.url)
        identity_key = job_identity(job)
        if (
            job_id in existing_ids
            or (url_key and url_key in existing_urls)
            or (identity_key and identity_key in existing_identities)
        ):
            continue
        candidates.append(NewJobCandidate(job=job, job_id=job_id))
        existing_ids.add(job_id)
        if url_key:
            existing_urls.add(url_key)
        if identity_key:
            existing_identities.add(identity_key)

    return candidates, len(jobs) - len(candidates)


def screen_new_job_candidates(
    db: Session,
    *,
    candidates: list[NewJobCandidate],
    screening_config: ScreeningConfig,
    settings: Settings,
    search_config_id: str | None = None,
) -> ScreeningPipelineResult:
    if not candidates:
        return ScreeningPipelineResult(keep=[])
    if not screening_config.enabled:
        return ScreeningPipelineResult(keep=list(candidates))

    config_hash = build_screening_config_hash(screening_config)
    model = settings.job_screening_model
    compact_jobs = {
        candidate.job_id: compact_screening_job(candidate)
        for candidate in candidates
    }
    vacancy_hashes = {
        candidate.job_id: build_screening_vacancy_hash(
            compact_jobs[candidate.job_id],
            max_description_chars=settings.job_screening_max_description_chars,
        )
        for candidate in candidates
    }
    decisions_by_id: dict[str, JobScreeningDecision] = {}
    deterministic: list[NewJobCandidate] = []
    uncached: list[NewJobCandidate] = []

    for candidate in candidates:
        seniority_decision = deterministic_seniority_decision(
            screening_config,
            compact_jobs[candidate.job_id],
            job_id=candidate.job_id,
        )
        if seniority_decision is not None:
            decisions_by_id[candidate.job_id] = seniority_decision
            deterministic.append(candidate)
            continue
        cached = latest_screening_decision(
            db,
            vacancy_hash=vacancy_hashes[candidate.job_id],
            config_hash=config_hash,
            model=model,
            prompt_version=JOB_SCREENING_PROMPT_VERSION,
        )
        if cached is None or cached.reason_code == "screening_error":
            uncached.append(candidate)
            continue
        try:
            decisions_by_id[candidate.job_id] = JobScreeningDecision(
                id=candidate.job_id,
                decision=cached.decision,
                reasonCode=cached.reason_code,
                matchedRuleIds=list(cached.matched_rule_ids),
                reason=cached.reason,
            )
        except ValidationError:
            uncached.append(candidate)

    consent = privacy_settings_record(db, get_bound_owner_id())
    external_screening_attempted = False
    ai_calls = 0
    missing_consent = bool(
        uncached and not has_current_ai_consent(consent, settings)
    )
    if missing_consent:
        for candidate in uncached:
            decisions_by_id[candidate.job_id] = JobScreeningDecision.model_validate(
                uncertain_or_keep_decision(
                    candidate.job_id,
                    reason_code="screening_error",
                    reason="Current AI data-processing consent is missing",
                )
            )
    elif uncached:
        external_screening_attempted = True
        allowed_rule_ids = screening_rule_ids(screening_config)
        batch_size = settings.job_screening_batch_size
        try:
            facade = create_job_screening_ai_facade(settings)
        except Exception as exc:
            for candidate in uncached:
                decisions_by_id[candidate.job_id] = screening_error_decision(
                    candidate.job_id,
                    exc,
                )
        else:
            for offset in range(0, len(uncached), batch_size):
                batch = uncached[offset : offset + batch_size]
                expected_ids = [candidate.job_id for candidate in batch]
                try:
                    ai_calls += 1
                    raw_decisions = facade.screen(
                        screening_config,
                        [compact_jobs[job_id] for job_id in expected_ids],
                    )
                    payload = JobScreeningPayload.model_validate(
                        {"decisions": raw_decisions}
                    )
                    normalized = normalize_screening_decisions(
                        payload,
                        expected_ids=expected_ids,
                        allowed_rule_ids=allowed_rule_ids,
                    )
                    decisions_by_id.update(
                        {
                            decision.id: decision
                            for decision in (
                                JobScreeningDecision.model_validate(item)
                                for item in normalized
                            )
                        }
                    )
                except Exception as exc:
                    decisions_by_id.update(
                        {
                            candidate.job_id: screening_error_decision(
                                candidate.job_id,
                                exc,
                            )
                            for candidate in batch
                        }
                    )

    if external_screening_attempted and consent is not None:
        activity_at = datetime.now(UTC)
        consent.last_ai_activity_at = activity_at
        consent.ai_data_expires_at = activity_at + timedelta(
            days=consent.retention_days
        )
        consent.updated_at = activity_at

    for candidate in [*deterministic, *uncached]:
        persist_screening_decision(
            db,
            vacancy_hash=vacancy_hashes[candidate.job_id],
            config_hash=config_hash,
            decision=decisions_by_id[candidate.job_id],
            model=model,
            prompt_version=JOB_SCREENING_PROMPT_VERSION,
            title=candidate.job.title,
            company=candidate.job.company,
            source_url=candidate.job.url or candidate.job.apply_url,
            search_config_id=search_config_id,
            vacancy_data=compact_jobs[candidate.job_id],
        )

    ordered_decisions = [
        decisions_by_id[candidate.job_id]
        for candidate in candidates
    ]
    keep_ids = {
        decision.id
        for decision in ordered_decisions
        if decision.decision == "keep"
    }
    error_count = sum(
        decision.reason_code == "screening_error"
        for decision in ordered_decisions
    )
    warning = None
    if error_count:
        warning = (
            SCREENING_CONSENT_WARNING
            if missing_consent
            else (
                f"Vacancy screening failed for {error_count} "
                "vacancies; unverified vacancies were skipped"
            )
        )

    return ScreeningPipelineResult(
        keep=[
            candidate
            for candidate in candidates
            if candidate.job_id in keep_ids
        ],
        decisions=ordered_decisions,
        jobs_screened=len(candidates),
        jobs_passed=sum(
            decision.decision == "keep" for decision in ordered_decisions
        ),
        jobs_rejected=sum(
            decision.decision == "reject" for decision in ordered_decisions
        ),
        jobs_uncertain=sum(
            decision.decision == "uncertain" for decision in ordered_decisions
        ),
        screening_errors=error_count,
        jobs_screening_ai_calls=ai_calls,
        warning=warning,
    )


def compact_screening_job(candidate: NewJobCandidate) -> dict[str, Any]:
    if candidate.compact_data is not None:
        return {
            **candidate.compact_data,
            "id": candidate.job_id,
        }
    return compact_screening_data(candidate.job, job_id=candidate.job_id)


def screening_error_decision(
    job_id: str,
    error: Exception,
) -> JobScreeningDecision:
    detail = str(error).strip()
    reason = "Vacancy screening failed"
    if detail:
        reason = f"{reason}: {detail[:450]}"
    return JobScreeningDecision.model_validate(
        uncertain_or_keep_decision(
            job_id,
            reason_code="screening_error",
            reason=reason[:500],
        )
    )


def persist_new_jobs(
    db: Session,
    *,
    jobs: list[NewJobCandidate] | list[ParsedJob],
    added_at: datetime,
    provenance: JobImportProvenance | None = None,
) -> list[dict[str, Any]]:
    if jobs and isinstance(jobs[0], ParsedJob):
        candidates, _ = prepare_new_job_candidates(
            db,
            jobs=[job for job in jobs if isinstance(job, ParsedJob)],
        )
    else:
        candidates = [
            candidate
            for candidate in jobs
            if isinstance(candidate, NewJobCandidate)
        ]

    records = db.scalars(select(StoredJobRecord)).all()
    existing_ids = {record.id for record in records}
    existing_urls = {
        canonical_job_url(stored_job_url(record.data))
        for record in records
        if canonical_job_url(stored_job_url(record.data))
    }
    existing_identities = {
        stored_job_identity(record.data)
        for record in records
        if stored_job_identity(record.data)
    }
    added: list[dict[str, Any]] = []

    for candidate in candidates:
        job = candidate.job
        job_id = candidate.job_id
        url_key = canonical_job_url(job.url)
        identity_key = job_identity(job)
        if (
            job_id in existing_ids
            or (url_key and url_key in existing_urls)
            or (identity_key and identity_key in existing_identities)
        ):
            continue
        data = parsed_job_to_stored_job(
            job,
            job_id=job_id,
            added_at=added_at,
        )
        record = StoredJobRecord(id=job_id, data=data, status="active")
        if provenance is not None:
            apply_job_import_provenance(record, provenance)
        db.add(record)
        existing_ids.add(job_id)
        if url_key:
            existing_urls.add(url_key)
        if identity_key:
            existing_identities.add(identity_key)
        added.append(data)
    return added


def apply_job_import_provenance(
    record: StoredJobRecord,
    provenance: JobImportProvenance,
) -> None:
    snapshot = deepcopy(provenance.screening_config_snapshot)
    record.search_config_id = provenance.search_config_id
    record.search_config_version = provenance.search_config_version
    record.screening_config_hash = provenance.screening_config_hash
    record.screening_config_snapshot = snapshot
    record.data = {
        **record.data,
        "searchConfigId": provenance.search_config_id,
        "searchConfigVersion": provenance.search_config_version,
        "screeningConfigHash": provenance.screening_config_hash,
        "screeningConfigSnapshot": deepcopy(snapshot),
    }


def combine_warnings(*warnings: str | None) -> str | None:
    values = list(
        dict.fromkeys(
            warning.strip()
            for warning in warnings
            if warning and warning.strip()
        )
    )
    if not values:
        return None
    return "; ".join(values)[:500]


def match_new_jobs_if_allowed(
    db: Session,
    *,
    jobs: list[dict[str, Any]],
    enabled: bool,
    settings: Settings,
    owner_id: str,
) -> str | None:
    if not enabled or not jobs:
        return None
    consent = privacy_settings_record(db, owner_id)
    if not has_current_ai_consent(consent, settings):
        return AI_CONSENT_WARNING

    try:
        profile_record = db.get(ProfileRecord, "default")
        profile = (
            ProfilePayload.model_validate(profile_record.data)
            if profile_record
            else ProfilePayload()
        )
        candidate_snapshot = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=settings,
            allow_ai=True,
            strict_ai=True,
        )
        matched_jobs = create_vacancy_matching_ai_facade(settings).match(
            profile,
            jobs,
            candidate_snapshot=candidate_snapshot.data,
        )
        for matched_job in matched_jobs:
            persist_job_and_match(
                db,
                job=matched_job,
                profile_hash=candidate_snapshot.profile_hash,
            )
        assert consent is not None
        activity_at = datetime.now(UTC)
        consent.last_ai_activity_at = activity_at
        consent.ai_data_expires_at = activity_at + timedelta(days=consent.retention_days)
        consent.updated_at = activity_at
        db.commit()
        return None
    except (AiMatchError, CandidateSnapshotError, ValidationError) as exc:
        db.rollback()
        return f"AI Match failed for new vacancies: {str(exc)[:240]}"


def parsed_job_id(job: ParsedJob, *, index: int) -> str:
    del index
    return stable_job_id(job)


def parsed_job_to_stored_job(
    job: ParsedJob,
    *,
    job_id: str,
    added_at: datetime,
) -> dict[str, Any]:
    source = normalize_source(job.source)
    company_definition = direct_company_definition(source)
    source_label = {
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "jobs_ch": "jobs.ch",
    }.get(source, company_definition.name if company_definition else source)
    company = normalized_text(job.company, source_label)
    title = normalized_text(job.title, f"{source_label} vacancy")
    location = normalized_text(job.location, "Not specified")
    employment_type = normalized_text(job.employment_type, "Not specified")
    experience = normalized_text(job.seniority, "Not specified")
    overview = normalized_text(
        job.description,
        (
            f"Imported from {source_label}. Open the source vacancy to review "
            "the full description and apply details."
        ),
    )
    salary = normalized_text(job.salary, format_salary(job))
    source_url = normalized_text(job.url, "")
    apply_url = normalized_text(job.apply_url, source_url)
    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": employment_type,
        "salary": salary,
        "posted": normalized_text(job.posted_at, source_label),
        "experience": experience,
        "department": f"{source_label} import",
        "match": 50,
        "logo": source if source in AGGREGATOR_SOURCE_IDS else "company",
        "overview": overview,
        "responsibilities": [
            f"Review the {source_label} vacancy details",
            "Compare requirements with your profile",
            "Decide whether to save or apply",
        ],
        "requirements": [
            item for item in (experience, employment_type, location) if item != "Not specified"
        ],
        "skills": [source_label, "Imported"],
        "salaryAverage": format_salary_amount(
            average(job.salary_min, job.salary_max),
            job.salary_currency,
        ),
        "salaryMin": format_salary_amount(job.salary_min, job.salary_currency),
        "salaryMax": format_salary_amount(job.salary_max, job.salary_currency),
        "recommendations": [],
        "companyInfo": (
            f"{company} vacancy imported from {source_label}"
            f"{f': {source_url}' if source_url else '.'}"
        ),
        "reviews": ["This vacancy was imported automatically and has not been reviewed yet."],
        "similarJobs": [],
        "applyUrl": apply_url or None,
        "sourceUrl": source_url or None,
        "addedAt": serialize_datetime(added_at),
    }


def run_status(result: VacancySearchRunResult) -> str:
    if not result.source_errors:
        return "completed"
    successful_sources = set(result.source_results) - set(result.source_errors)
    if successful_sources:
        return "partial"
    return "failed"


def stored_job_url(data: dict[str, Any]) -> str:
    return str(data.get("sourceUrl") or data.get("applyUrl") or "")


def stored_job_identity(data: dict[str, Any]) -> str:
    title = normalize_identity_part(str(data.get("title") or ""))
    company = normalize_identity_part(str(data.get("company") or ""))
    location = normalize_identity_part(str(data.get("location") or ""))
    if not title or not company:
        return ""
    return "|".join((title, company, location))


def normalize_source(value: str) -> str:
    normalized = "jobs_ch" if value in {"jobs_ch", "jobs.ch"} else value
    if normalized in SUPPORTED_VACANCY_SOURCE_IDS:
        return normalized
    return "linkedin"


def normalized_text(value: str | None, fallback: str) -> str:
    return value.strip() if value and value.strip() else fallback


def format_salary(job: ParsedJob) -> str:
    minimum = format_salary_amount(job.salary_min, job.salary_currency)
    maximum = format_salary_amount(job.salary_max, job.salary_currency)
    values = [value for value in (minimum, maximum) if value != "N/A"]
    values = list(dict.fromkeys(values))
    return " – ".join(values) if values else "Not specified"


def format_salary_amount(value: int | None, currency: str | None) -> str:
    if value is None:
        return "N/A"
    prefix = f"{currency.strip()} " if currency and currency.strip() else ""
    return f"{prefix}{value:,}".replace(",", "'")


def average(minimum: int | None, maximum: int | None) -> int | None:
    if minimum is not None and maximum is not None:
        return round((minimum + maximum) / 2)
    return minimum if minimum is not None else maximum


def serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()
