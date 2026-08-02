from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identity import get_bound_owner_id
from app.core.settings import Settings
from app.core.vacancy_sources import SUPPORTED_VACANCY_SOURCE_IDS
from app.models.job_search import (
    JobSearchConfigRecord,
    JobSearchRescreenConfigGroupPayload,
    JobSearchRescreenPayload,
    ScreeningConfig,
    normalize_job_search_config,
)
from app.models.jobs import StoredJobRecord
from app.models.parsers import ParsedJob
from app.services.job_screening import JOB_SCREENING_PROMPT_VERSION
from app.services.job_screening_store import (
    build_screening_config_hash,
    build_screening_vacancy_hash,
    sha256_json,
)
from app.services.job_search_execution import (
    JobImportProvenance,
    NewJobCandidate,
    apply_job_import_provenance,
    combine_warnings,
    compact_screening_job,
    effective_screening_config,
    screen_new_job_candidates,
    serialize_datetime,
)

ACTIVE_JOB_STATUS = "active"
DISMISSED_JOB_STATUS = "dismissed"
SCREENED_OUT_JOB_STATUS = "screened_out"
IMPORTED_JOB_SOURCES = SUPPORTED_VACANCY_SOURCE_IDS


class JobRescreeningError(RuntimeError):
    pass


class JobRescreeningConfirmationRequired(JobRescreeningError):
    pass


class JobRescreeningPlanChanged(JobRescreeningError):
    pass


@dataclass(frozen=True)
class EligibleStoredJob:
    record: StoredJobRecord
    candidate: NewJobCandidate


@dataclass(frozen=True)
class RescreenConfigContext:
    config_id: str
    screening: ScreeningConfig
    config_hash: str
    provenance: JobImportProvenance


@dataclass
class RescreenConfigGroup:
    context: RescreenConfigContext
    items: list[EligibleStoredJob]
    fallback_jobs: int = 0


def rescreen_stored_jobs(
    db: Session,
    *,
    config: JobSearchConfigRecord,
    settings: Settings,
    dry_run: bool,
    confirm: bool,
    use_selected_config_as_fallback: bool,
    confirmation_token: str | None,
) -> JobSearchRescreenPayload:
    selected_context = require_rescreen_context(config)
    eligible = eligible_stored_jobs(db)
    groups, skipped_reasons = group_jobs_by_source_config(
        db,
        eligible=eligible,
        selected_context=selected_context,
        use_selected_config_as_fallback=use_selected_config_as_fallback,
    )
    decision_by_id: dict[str, Any] = {}
    context_by_job_id: dict[str, RescreenConfigContext] = {}
    config_group_payloads: list[JobSearchRescreenConfigGroupPayload] = []
    jobs_screened = 0
    jobs_passed = 0
    jobs_rejected = 0
    jobs_uncertain = 0
    screening_errors = 0
    warnings: list[str | None] = []

    for group in groups:
        screening_result = screen_new_job_candidates(
            db,
            candidates=[item.candidate for item in group.items],
            screening_config=group.context.screening,
            settings=settings,
            search_config_id=group.context.config_id,
        )
        if len(screening_result.decisions) != len(group.items):
            raise JobRescreeningError(
                "Vacancy screening did not produce a complete rescreening plan"
            )
        for decision in screening_result.decisions:
            decision_by_id[decision.id] = decision
            context_by_job_id[decision.id] = group.context
        jobs_screened += screening_result.jobs_screened
        jobs_passed += screening_result.jobs_passed
        jobs_rejected += screening_result.jobs_rejected
        jobs_uncertain += screening_result.jobs_uncertain
        screening_errors += screening_result.screening_errors
        warnings.append(screening_result.warning)
        config_group_payloads.append(
            JobSearchRescreenConfigGroupPayload(
                configId=group.context.config_id,
                configHash=group.context.config_hash,
                usedAsFallback=group.fallback_jobs > 0,
                fallbackJobs=group.fallback_jobs,
                jobs=len(group.items),
                jobsScreened=screening_result.jobs_screened,
                jobsPassed=screening_result.jobs_passed,
                jobsRejected=screening_result.jobs_rejected,
                jobsUncertain=screening_result.jobs_uncertain,
                screeningErrors=screening_result.screening_errors,
            )
        )

    screened = [
        item
        for group in groups
        for item in group.items
    ]
    jobs_to_hide = [
        item
        for item in screened
        if item.record.status == ACTIVE_JOB_STATUS
        and decision_by_id[item.record.id].decision != "keep"
    ]
    jobs_to_restore = [
        item
        for item in screened
        if item.record.status == SCREENED_OUT_JOB_STATUS
        and decision_by_id[item.record.id].decision == "keep"
    ]
    plan_token = build_confirmation_token(
        screened,
        decision_by_id=decision_by_id,
        context_by_job_id=context_by_job_id,
        settings=settings,
    )

    if not dry_run:
        if not confirm or not confirmation_token:
            raise JobRescreeningConfirmationRequired(
                "Run a dry run and explicitly confirm its rescreening plan"
            )
        if confirmation_token != plan_token:
            raise JobRescreeningPlanChanged(
                "The rescreening plan changed; run a new dry run before confirming"
            )
        for item in screened:
            decision = decision_by_id[item.record.id]
            context = context_by_job_id[item.record.id]
            item.record.status = (
                ACTIVE_JOB_STATUS
                if decision.decision == "keep"
                else SCREENED_OUT_JOB_STATUS
            )
            item.record.dismissed_at = None
            apply_job_import_provenance(
                item.record,
                context.provenance,
            )

    skipped_jobs = sum(skipped_reasons.values())
    if skipped_jobs:
        warnings.append(
            f"{skipped_jobs} imported vacancies were skipped because their "
            "source search config was unavailable and no fallback was selected"
        )

    return JobSearchRescreenPayload(
        configId=config.id,
        configHash=selected_context.config_hash,
        dryRun=dry_run,
        applied=not dry_run,
        eligibleJobs=len(eligible),
        jobsScreened=jobs_screened,
        jobsPassed=jobs_passed,
        jobsRejected=jobs_rejected,
        jobsUncertain=jobs_uncertain,
        screeningErrors=screening_errors,
        jobsSkipped=skipped_jobs,
        jobsUsingFallback=sum(
            group.fallback_jobs
            for group in groups
        ),
        skippedReasons=skipped_reasons,
        configGroups=config_group_payloads,
        jobsToHide=len(jobs_to_hide),
        jobsToRestore=len(jobs_to_restore),
        jobsHidden=len(jobs_to_hide) if not dry_run else 0,
        jobsRestored=len(jobs_to_restore) if not dry_run else 0,
        confirmationToken=plan_token,
        warning=combine_warnings(*warnings),
    )


def eligible_stored_jobs(db: Session) -> list[EligibleStoredJob]:
    records = list(
        db.scalars(
            select(StoredJobRecord)
            .where(
                StoredJobRecord.status.in_(
                    (ACTIVE_JOB_STATUS, SCREENED_OUT_JOB_STATUS)
                )
            )
            .order_by(StoredJobRecord.id)
        ).all()
    )
    return [
        EligibleStoredJob(
            record=record,
            candidate=stored_job_candidate(record),
        )
        for record in records
        if is_automatically_imported(record)
    ]


def require_rescreen_context(
    config: JobSearchConfigRecord,
) -> RescreenConfigContext:
    context, reason = build_rescreen_context(config)
    if context is not None:
        return context
    if reason == "source_config_screening_disabled":
        raise JobRescreeningError(
            "The selected search config does not have screening enabled"
        )
    raise JobRescreeningError("The selected search config is invalid")


def build_rescreen_context(
    config: JobSearchConfigRecord,
) -> tuple[RescreenConfigContext | None, str | None]:
    try:
        normalized_config = normalize_job_search_config(config.filters)
    except ValidationError:
        return None, "source_config_invalid"
    screening = effective_screening_config(
        normalized_config,
        screening_required=False,
    )
    if not screening.enabled:
        return None, "source_config_screening_disabled"
    config_hash = build_screening_config_hash(screening)
    return (
        RescreenConfigContext(
            config_id=config.id,
            screening=screening,
            config_hash=config_hash,
            provenance=JobImportProvenance(
                search_config_id=config.id,
                search_config_version=serialize_datetime(config.updated_at),
                screening_config_hash=config_hash,
                screening_config_snapshot=(
                    screening.model_dump(
                        by_alias=True,
                        exclude_none=True,
                    )
                ),
            ),
        ),
        None,
    )


def group_jobs_by_source_config(
    db: Session,
    *,
    eligible: list[EligibleStoredJob],
    selected_context: RescreenConfigContext,
    use_selected_config_as_fallback: bool,
) -> tuple[list[RescreenConfigGroup], dict[str, int]]:
    source_config_ids = {
        config_id
        for item in eligible
        if (config_id := source_config_id(item.record))
    }
    configs = list(
        db.scalars(
            select(JobSearchConfigRecord).where(
                JobSearchConfigRecord.id.in_(source_config_ids)
            )
        ).all()
    )
    configs_by_id = {config.id: config for config in configs}
    contexts: dict[str, RescreenConfigContext] = {
        selected_context.config_id: selected_context,
    }
    unavailable_reasons: dict[str, str] = {}
    for config_id in sorted(source_config_ids):
        if config_id in contexts:
            continue
        config = configs_by_id.get(config_id)
        if config is None:
            unavailable_reasons[config_id] = "source_config_not_found"
            continue
        context, reason = build_rescreen_context(config)
        if context is None:
            unavailable_reasons[config_id] = (
                reason or "source_config_invalid"
            )
            continue
        contexts[config_id] = context

    groups_by_id: dict[str, RescreenConfigGroup] = {}
    skipped_reasons: dict[str, int] = {}
    for item in eligible:
        config_id = source_config_id(item.record)
        context = contexts.get(config_id or "")
        used_as_fallback = False
        if context is None:
            reason = (
                "missing_source_config"
                if not config_id
                else unavailable_reasons.get(
                    config_id,
                    "source_config_not_found",
                )
            )
            if not use_selected_config_as_fallback:
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                continue
            context = selected_context
            used_as_fallback = True
        group = groups_by_id.setdefault(
            context.config_id,
            RescreenConfigGroup(context=context, items=[]),
        )
        group.items.append(item)
        if used_as_fallback:
            group.fallback_jobs += 1
    return (
        [groups_by_id[key] for key in sorted(groups_by_id)],
        skipped_reasons,
    )


def source_config_id(record: StoredJobRecord) -> str | None:
    if record.search_config_id:
        return record.search_config_id
    value = record.data.get("searchConfigId")
    return value.strip() if isinstance(value, str) and value.strip() else None


def is_automatically_imported(record: StoredJobRecord) -> bool:
    source = imported_source_from_id(record.id)
    logo = normalize_imported_source(record.data.get("logo"))
    return bool(source and logo == source)


def imported_source_from_id(job_id: str) -> str:
    for source in IMPORTED_JOB_SOURCES:
        if job_id.startswith(f"{source}-"):
            return source
    return ""


def normalize_imported_source(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().casefold()
    return "jobs_ch" if normalized == "jobs.ch" else normalized


def stored_job_candidate(record: StoredJobRecord) -> NewJobCandidate:
    data = record.data
    source = imported_source_from_id(record.id)
    job = ParsedJob(
        source=source,
        title=text_value(data.get("title")),
        company=text_value(data.get("company")),
        location=text_value(data.get("location")),
        url=text_value(data.get("sourceUrl")),
        apply_url=text_value(data.get("applyUrl")),
        posted_at=text_value(data.get("posted")),
        employment_type=text_value(data.get("type")),
        seniority=text_value(data.get("experience")),
        description=text_value(data.get("overview")),
    )
    return NewJobCandidate(
        job=job,
        job_id=record.id,
        compact_data={
            "title": job.title or "",
            "company": job.company or "",
            "location": job.location or "",
            "description": job.description or "",
            "employmentType": job.employment_type or "",
            "seniority": job.seniority or "",
            "source": source,
            "postedAt": job.posted_at or "",
            "salaryMin": compact_value(data.get("salaryMin")),
            "salaryMax": compact_value(data.get("salaryMax")),
            "salaryCurrency": text_value(data.get("salaryCurrency")) or "",
        },
    )


def build_confirmation_token(
    screened: list[EligibleStoredJob],
    *,
    decision_by_id: dict[str, Any],
    context_by_job_id: dict[str, RescreenConfigContext],
    settings: Settings,
) -> str:
    return sha256_json(
        {
            "ownerId": get_bound_owner_id(),
            "model": settings.job_screening_model,
            "promptVersion": JOB_SCREENING_PROMPT_VERSION,
            "jobs": [
                {
                    "id": item.record.id,
                    "status": item.record.status,
                    "configId": (
                        context_by_job_id[item.record.id].config_id
                    ),
                    "configHash": (
                        context_by_job_id[item.record.id].config_hash
                    ),
                    "vacancyHash": build_screening_vacancy_hash(
                        compact_screening_job(item.candidate),
                        max_description_chars=(
                            settings.job_screening_max_description_chars
                        ),
                    ),
                    "decision": decision_by_id[item.record.id].decision,
                }
                for item in screened
            ],
        }
    )


def text_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def compact_value(value: object) -> int | float | str | None:
    return value if isinstance(value, (int, float, str)) else None
