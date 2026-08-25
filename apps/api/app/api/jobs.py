from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.core.identity import (
    RequestIdentity,
    bind_request_identity,
    get_bound_owner_id,
    get_request_identity,
)
from app.core.settings import Settings, get_settings
from app.models.jobs import (
    AiMatchJobStatus,
    DismissedJobIdsRequest,
    StoredJobPayload,
    StoredJobRecord,
    StoredJobsRequest,
)
from app.models.profile import ProfilePayload, ProfileRecord
from app.services.ai_match import (
    JOB_ADDED_AT_FIELDS,
    AiMatchError,
    create_vacancy_matching_ai_facade,
)
from app.services.ai_match_jobs import ai_match_jobs
from app.services.ai_privacy import record_ai_activity
from app.services.candidate_snapshot import CandidateSnapshotError, get_candidate_match_snapshot
from app.services.job_match_store import (
    hydrate_job_data,
    persist_job_and_match,
    strip_ai_match,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])

ACTIVE_JOB_STATUS = "active"
DISMISSED_JOB_STATUS = "dismissed"
PARSER_JOB_ID_PREFIXES = ("linkedin-", "indeed-", "jobs_ch-")
PARSER_JOB_LOGOS = {"linkedin", "indeed", "jobs_ch", "jobs.ch"}


@router.get("", response_model=list[StoredJobPayload])
def list_jobs(db: Session = Depends(get_db)) -> list[StoredJobPayload]:
    try:
        profile = get_current_profile(db)
        candidate_snapshot = get_candidate_match_snapshot(db, profile=profile)
        records = (
            db.query(StoredJobRecord)
            .filter(StoredJobRecord.status == ACTIVE_JOB_STATUS)
            .order_by(StoredJobRecord.id.desc())
            .all()
        )
        return [
            StoredJobPayload(
                id=record.id,
                data=hydrate_job_data(
                    db,
                    job_id=record.id,
                    job_data=record.data,
                    profile_hash=candidate_snapshot.profile_hash,
                ),
            )
            for record in records
        ]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc


@router.put("", response_model=list[StoredJobPayload])
def upsert_jobs(request: StoredJobsRequest, db: Session = Depends(get_db)) -> list[StoredJobPayload]:
    try:
        now = datetime.now(UTC).isoformat()
        for job in request.jobs:
            record = db.get(StoredJobRecord, (get_bound_owner_id(), job.id))
            if record is None and is_parser_import(job.id, job.data):
                continue
            if record and record.status != ACTIVE_JOB_STATUS:
                continue
            job_data = prepare_job_data(job.data, record, now)
            if record:
                record.data = strip_ai_match(job_data)
                record.status = ACTIVE_JOB_STATUS
                record.dismissed_at = None
            else:
                db.add(
                    StoredJobRecord(
                        id=job.id,
                        data=strip_ai_match(job_data),
                        status=ACTIVE_JOB_STATUS,
                    )
                )

        db.commit()
        return list_jobs(db)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc


@router.post("/ai-match", response_model=list[StoredJobPayload])
def match_jobs(
    request: StoredJobsRequest,
    force: bool = False,
    _activity=Depends(record_ai_activity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[StoredJobPayload]:
    try:
        now = datetime.now(UTC).isoformat()
        jobs_to_match = []
        for job in request.jobs:
            record = db.get(StoredJobRecord, (get_bound_owner_id(), job.id))
            if record is None and is_parser_import(job.id, job.data):
                continue
            if record and record.status != ACTIVE_JOB_STATUS:
                continue
            jobs_to_match.append(prepare_job_data(job.data, record, now))
        if not jobs_to_match:
            return []
        profile = get_current_profile(db)
        candidate_snapshot = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=settings,
            allow_ai=True,
            strict_ai=True,
        )
        jobs_to_match = [
            hydrate_job_data(
                db,
                job_id=str(job.get("id") or ""),
                job_data=job,
                profile_hash=candidate_snapshot.profile_hash,
            )
            for job in jobs_to_match
        ]
        matched_jobs = create_vacancy_matching_ai_facade(settings).match(
            profile,
            jobs_to_match,
            force=force,
            candidate_snapshot=candidate_snapshot.data,
        )

        persisted_jobs: list[dict[str, Any]] = []
        for job in matched_jobs:
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            persist_job_and_match(db, job=job, profile_hash=candidate_snapshot.profile_hash)
            persisted_jobs.append(job)

        db.commit()
        return [StoredJobPayload(id=str(job.get("id")), data=job) for job in persisted_jobs if job.get("id")]
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc
    except AiMatchError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except CandidateSnapshotError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/ai-match/run", response_model=AiMatchJobStatus, status_code=status.HTTP_202_ACCEPTED)
def run_match_jobs(
    request: StoredJobsRequest,
    force: bool = False,
    identity: RequestIdentity = Depends(get_request_identity),
    _activity=Depends(record_ai_activity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AiMatchJobStatus:
    try:
        now = datetime.now(UTC).isoformat()
        jobs_to_match = []
        for job in request.jobs:
            record = db.get(StoredJobRecord, (get_bound_owner_id(), job.id))
            if record is None and is_parser_import(job.id, job.data):
                continue
            if record and record.status != ACTIVE_JOB_STATUS:
                continue
            jobs_to_match.append(prepare_job_data(job.data, record, now))
        if not jobs_to_match:
            return AiMatchJobStatus(status="completed")
        profile = get_current_profile(db)
        candidate_snapshot = get_candidate_match_snapshot(
            db,
            profile=profile,
            settings=settings,
            allow_ai=True,
            strict_ai=True,
        )
        jobs_to_match = [
            hydrate_job_data(
                db,
                job_id=str(job.get("id") or ""),
                job_data=job,
                profile_hash=candidate_snapshot.profile_hash,
            )
            for job in jobs_to_match
        ]
        db.commit()
        session_factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
        started, current_status = ai_match_jobs.start(
            owner_id=identity.owner_id,
            profile=profile,
            jobs=jobs_to_match,
            profile_hash=candidate_snapshot.profile_hash,
            candidate_snapshot=candidate_snapshot.data,
            settings=settings,
            session_factory=session_factory,
            force=force,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc
    except CandidateSnapshotError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if not started:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AI match job is already running",
        )

    return current_status


@router.get("/ai-match/status", response_model=AiMatchJobStatus)
def get_match_jobs_status(
    identity: RequestIdentity = Depends(get_request_identity),
) -> AiMatchJobStatus:
    return ai_match_jobs.status(identity.owner_id)


def get_current_profile(db: Session) -> ProfilePayload:
    profile_record = db.get(ProfileRecord, "default")
    return (
        ProfilePayload.model_validate(profile_record.data)
        if profile_record
        else ProfilePayload()
    )


def prepare_job_data(
    job_data: dict[str, Any],
    record: StoredJobRecord | None,
    now: str,
) -> dict[str, Any]:
    next_job_data = dict(job_data)
    if has_added_at(next_job_data):
        return next_job_data

    if record and isinstance(record.data, dict):
        added_at = first_added_at(record.data)
        if added_at:
            next_job_data["addedAt"] = added_at
            return next_job_data

        return next_job_data

    next_job_data["addedAt"] = now
    return next_job_data


def is_parser_import(job_id: str, job_data: dict[str, Any]) -> bool:
    if job_id.casefold().startswith(PARSER_JOB_ID_PREFIXES):
        return True
    logo = job_data.get("logo")
    return (
        isinstance(logo, str)
        and logo.strip().casefold() in PARSER_JOB_LOGOS
    )


def has_added_at(job_data: dict[str, Any]) -> bool:
    return bool(first_added_at(job_data))


def first_added_at(job_data: dict[str, Any]) -> str:
    for field in JOB_ADDED_AT_FIELDS:
        value = job_data.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@router.get("/dismissed-ids", response_model=list[str])
def list_dismissed_job_ids(db: Session = Depends(get_db)) -> list[str]:
    try:
        return [
            job_id
            for (job_id,) in db.query(StoredJobRecord.id)
            .filter(StoredJobRecord.status == DISMISSED_JOB_STATUS)
            .order_by(StoredJobRecord.id.asc())
            .all()
        ]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc


@router.put("/dismissed-ids", response_model=list[str])
def import_dismissed_job_ids(
    request: DismissedJobIdsRequest,
    db: Session = Depends(get_db),
) -> list[str]:
    try:
        dismissed_at = datetime.now(UTC)
        for job_id in dict.fromkeys(request.job_ids):
            normalized_job_id = job_id.strip()
            if not normalized_job_id or len(normalized_job_id) > 160:
                continue
            record = db.get(
                StoredJobRecord,
                (get_bound_owner_id(), normalized_job_id),
            )
            if not record:
                db.add(
                    StoredJobRecord(
                        id=normalized_job_id,
                        data={"id": normalized_job_id},
                        status=DISMISSED_JOB_STATUS,
                        dismissed_at=dismissed_at,
                    )
                )
            elif record.status != DISMISSED_JOB_STATUS:
                record.status = DISMISSED_JOB_STATUS
                record.dismissed_at = dismissed_at
        db.commit()
        return list_dismissed_job_ids(db)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str, db: Session = Depends(get_db)) -> None:
    try:
        record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
        if not record:
            record = StoredJobRecord(
                id=job_id,
                data={"id": job_id},
                status=DISMISSED_JOB_STATUS,
                dismissed_at=datetime.now(UTC),
            )
            db.add(record)
        else:
            record.status = DISMISSED_JOB_STATUS
            record.dismissed_at = datetime.now(UTC)
        db.commit()
        return None
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc
