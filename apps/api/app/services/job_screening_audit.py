from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models.job_screening import (
    JobScreeningAuditPayload,
    JobScreeningDecisionRecord,
)
from app.models.job_search import (
    JobSearchConfigRecord,
    normalize_job_search_config,
)
from app.models.jobs import StoredJobRecord
from app.models.parsers import ParsedJob
from app.services.job_screening import (
    JOB_SCREENING_PROMPT_VERSION,
    CompactScreeningJob,
)
from app.services.job_screening_store import (
    build_screening_config_hash,
    latest_screening_decision,
)
from app.services.job_search_execution import (
    JobImportProvenance,
    NewJobCandidate,
    apply_job_import_provenance,
    effective_screening_config,
    persist_new_jobs,
    screen_new_job_candidates,
)

ACTIVE_JOB_STATUS = "active"
DISMISSED_JOB_STATUS = "dismissed"
SCREENED_OUT_JOB_STATUS = "screened_out"


class JobScreeningAuditError(RuntimeError):
    pass


class JobScreeningAuditActionUnavailable(JobScreeningAuditError):
    pass


def list_screening_audit(
    db: Session,
    *,
    limit: int,
) -> list[JobScreeningAuditPayload]:
    records = db.scalars(
        select(JobScreeningDecisionRecord)
        .order_by(
            JobScreeningDecisionRecord.created_at.desc(),
            JobScreeningDecisionRecord.id.desc(),
        )
        .limit(limit)
    ).all()
    return [screening_audit_payload(record) for record in records]


def recheck_screening_decision(
    db: Session,
    *,
    record: JobScreeningDecisionRecord,
    settings: Settings,
) -> JobScreeningAuditPayload:
    config = require_audit_config(db, record)
    try:
        normalized_config = normalize_job_search_config(config.filters)
    except ValidationError as exc:
        raise JobScreeningAuditActionUnavailable(
            "The screening config is invalid"
        ) from exc
    screening = effective_screening_config(
        normalized_config,
        screening_required=False,
    )
    if not screening.enabled:
        raise JobScreeningAuditActionUnavailable(
            "Screening is disabled in this config"
        )

    candidate = audit_candidate(record)
    config_hash = build_screening_config_hash(screening)
    now = datetime.now(UTC)
    cached_records = db.scalars(
        select(JobScreeningDecisionRecord).where(
            JobScreeningDecisionRecord.vacancy_hash == record.vacancy_hash,
            JobScreeningDecisionRecord.config_hash == config_hash,
            JobScreeningDecisionRecord.model == settings.job_screening_model,
            JobScreeningDecisionRecord.prompt_version
            == JOB_SCREENING_PROMPT_VERSION,
            JobScreeningDecisionRecord.invalidated_at.is_(None),
        )
    ).all()
    for cached_record in cached_records:
        cached_record.invalidated_at = now
    record.invalidated_at = record.invalidated_at or now
    db.flush()

    result = screen_new_job_candidates(
        db,
        candidates=[candidate],
        screening_config=screening,
        settings=settings,
        search_config_id=config.id,
    )
    if len(result.decisions) != 1:
        raise JobScreeningAuditError(
            "Vacancy screening did not produce a decision"
        )
    decision = result.decisions[0]
    apply_screening_decision(
        db,
        candidate=candidate,
        decision=decision.decision,
        applied_at=now,
        provenance=JobImportProvenance(
            search_config_id=config.id,
            search_config_version=as_version(config.updated_at),
            screening_config_hash=config_hash,
            screening_config_snapshot=(
                screening.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
            ),
        ),
    )
    db.flush()

    latest = latest_screening_decision(
        db,
        vacancy_hash=record.vacancy_hash,
        config_hash=config_hash,
        model=settings.job_screening_model,
        prompt_version=JOB_SCREENING_PROMPT_VERSION,
    )
    if latest is None:
        raise JobScreeningAuditError(
            "Vacancy screening decision was not persisted"
        )
    return screening_audit_payload(latest)


def allow_screening_decision_manually(
    db: Session,
    *,
    record: JobScreeningDecisionRecord,
) -> JobScreeningAuditPayload:
    if record.decision == "keep":
        raise JobScreeningAuditActionUnavailable(
            "This vacancy has already passed screening"
        )
    if record.manually_allowed_at is not None:
        raise JobScreeningAuditActionUnavailable(
            "This vacancy has already been allowed manually"
        )
    candidate = audit_candidate(record)
    now = datetime.now(UTC)
    provenance = audit_record_provenance(db, record)
    stored = find_stored_job(db, candidate.job_id)
    if stored is not None and stored.status == DISMISSED_JOB_STATUS:
        raise JobScreeningAuditActionUnavailable(
            "A dismissed vacancy cannot be restored from the screening audit"
        )
    if stored is None:
        persist_new_jobs(
            db,
            jobs=[candidate],
            added_at=now,
            provenance=provenance,
        )
    else:
        stored.status = ACTIVE_JOB_STATUS
        stored.dismissed_at = None
        if provenance is not None:
            apply_job_import_provenance(stored, provenance)
    record.manually_allowed_at = now
    record.invalidated_at = record.invalidated_at or now
    db.flush()
    return screening_audit_payload(record)


def screening_audit_payload(
    record: JobScreeningDecisionRecord,
) -> JobScreeningAuditPayload:
    has_snapshot = bool(record.job_id and record.vacancy_data)
    return JobScreeningAuditPayload(
        id=record.id,
        jobId=record.job_id,
        decision=record.decision,
        reasonCode=record.reason_code,
        reason=record.reason,
        matchedRuleIds=list(record.matched_rule_ids),
        configHash=record.config_hash,
        configId=record.search_config_id,
        model=record.model,
        promptVersion=record.prompt_version,
        title=record.title,
        company=record.company,
        sourceUrl=record.source_url,
        checkedAt=record.created_at,
        invalidatedAt=record.invalidated_at,
        manuallyAllowedAt=record.manually_allowed_at,
        canRecheck=bool(
            has_snapshot
            and record.search_config_id
            and record.manually_allowed_at is None
        ),
        canAllowManually=bool(
            has_snapshot
            and record.decision != "keep"
            and record.manually_allowed_at is None
        ),
    )


def audit_candidate(record: JobScreeningDecisionRecord) -> NewJobCandidate:
    if not record.job_id or not record.vacancy_data:
        raise JobScreeningAuditActionUnavailable(
            "This legacy audit entry does not contain a vacancy snapshot"
        )
    try:
        compact = CompactScreeningJob.model_validate(
            {
                **record.vacancy_data,
                "id": record.job_id,
            }
        )
    except ValidationError as exc:
        raise JobScreeningAuditActionUnavailable(
            "The stored vacancy snapshot is invalid"
        ) from exc
    job = ParsedJob(
        source=compact.source or "linkedin",
        title=compact.title or record.title,
        company=compact.company or record.company,
        location=compact.location,
        url=record.source_url or None,
        apply_url=record.source_url or None,
        posted_at=compact.posted_at,
        employment_type=compact.employment_type,
        seniority=compact.seniority,
        description=compact.description,
        salary_min=integer_or_none(compact.salary_min),
        salary_max=integer_or_none(compact.salary_max),
        salary_currency=compact.salary_currency or None,
    )
    return NewJobCandidate(
        job=job,
        job_id=record.job_id,
        compact_data=compact.model_dump(
            by_alias=True,
            exclude={"id"},
        ),
    )


def require_audit_config(
    db: Session,
    record: JobScreeningDecisionRecord,
) -> JobSearchConfigRecord:
    if not record.search_config_id:
        raise JobScreeningAuditActionUnavailable(
            "This audit entry is not linked to a saved search config"
        )
    config = db.get(JobSearchConfigRecord, record.search_config_id)
    if config is None:
        raise JobScreeningAuditActionUnavailable(
            "The linked search config no longer exists"
        )
    return config


def apply_screening_decision(
    db: Session,
    *,
    candidate: NewJobCandidate,
    decision: str,
    applied_at: datetime,
    provenance: JobImportProvenance,
) -> None:
    stored = find_stored_job(db, candidate.job_id)
    if decision == "keep":
        if stored is None:
            persist_new_jobs(
                db,
                jobs=[candidate],
                added_at=applied_at,
                provenance=provenance,
            )
        elif stored.status == SCREENED_OUT_JOB_STATUS:
            stored.status = ACTIVE_JOB_STATUS
            stored.dismissed_at = None
        if stored is not None:
            apply_job_import_provenance(stored, provenance)
        return
    if stored is not None and stored.status == ACTIVE_JOB_STATUS:
        stored.status = SCREENED_OUT_JOB_STATUS
        stored.dismissed_at = None


def integer_or_none(value: int | float | str | None) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_stored_job(
    db: Session,
    job_id: str,
) -> StoredJobRecord | None:
    return db.scalar(
        select(StoredJobRecord).where(StoredJobRecord.id == job_id)
    )


def audit_record_provenance(
    db: Session,
    record: JobScreeningDecisionRecord,
) -> JobImportProvenance | None:
    if not record.search_config_id:
        return None
    config = db.get(JobSearchConfigRecord, record.search_config_id)
    if config is None:
        return None
    try:
        screening = normalize_job_search_config(config.filters).screening
    except ValidationError:
        return None
    return JobImportProvenance(
        search_config_id=config.id,
        search_config_version=as_version(config.updated_at),
        screening_config_hash=build_screening_config_hash(screening),
        screening_config_snapshot=screening.model_dump(
            by_alias=True,
            exclude_none=True,
        ),
    )


def as_version(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()
