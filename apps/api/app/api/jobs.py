from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

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
    JobStatePatchRequest,
    JobStatePayload,
    StoredJobPayload,
    StoredJobRecord,
    StoredJobsRequest,
    is_job_state_placeholder,
)
from app.models.profile import ProfilePayload
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
from app.services.profile_versions import get_profile_record

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
            if not is_job_state_placeholder(record)
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
            if (record is None or is_job_state_placeholder(record)) and is_parser_import(
                job.id,
                job.data,
            ):
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
            if (record is None or is_job_state_placeholder(record)) and is_parser_import(
                job.id,
                job.data,
            ):
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
            if (record is None or is_job_state_placeholder(record)) and is_parser_import(
                job.id,
                job.data,
            ):
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
    profile_record = get_profile_record(db)
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


def job_state_payload(record: StoredJobRecord) -> JobStatePayload:
    return JobStatePayload(
        jobId=record.id,
        saved=record.saved_at is not None,
        archived=record.archived_at is not None,
        dismissed=record.status == DISMISSED_JOB_STATUS,
        savedAt=record.saved_at,
        archivedAt=record.archived_at,
        dismissedAt=record.dismissed_at,
        updatedAt=record.updated_at,
        revision=record.revision,
    )


def set_job_state_etag(response: Response, revision: int) -> None:
    response.headers["ETag"] = f'"{revision}"'


def parse_if_match_revision(if_match: str) -> int:
    candidate = if_match.strip()
    if candidate.startswith("W/"):
        candidate = candidate[2:].strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] == '"':
        candidate = candidate[1:-1]
    if not candidate.isdigit() or int(candidate) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match must contain one numeric job revision",
        )
    return int(candidate)


def requested_job_state_revision(
    request_revision: int | None,
    if_match: str | None,
) -> tuple[int, bool]:
    header_revision = parse_if_match_revision(if_match) if if_match is not None else None
    if (
        request_revision is not None
        and header_revision is not None
        and request_revision != header_revision
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body revision and If-Match revision must be equal",
        )
    expected_revision = header_revision if header_revision is not None else request_revision
    if expected_revision is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Job state PATCH requires revision or If-Match",
        )
    return expected_revision, header_revision is not None


def job_state_conflict(
    record: StoredJobRecord | None,
    *,
    if_match_used: bool,
) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_412_PRECONDITION_FAILED if if_match_used else status.HTTP_409_CONFLICT
        ),
        detail={
            "message": "Job state revision conflict",
            "currentRevision": record.revision if record is not None else None,
        },
    )


@router.get("/state", response_model=list[JobStatePayload])
def list_job_states(db: Session = Depends(get_db)) -> list[JobStatePayload]:
    try:
        records = db.query(StoredJobRecord).order_by(StoredJobRecord.id.asc()).all()
        return [job_state_payload(record) for record in records]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc


@router.get("/{job_id}/state", response_model=JobStatePayload)
def get_job_state(
    job_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> JobStatePayload:
    try:
        record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found",
            )
        set_job_state_etag(response, record.revision)
        return job_state_payload(record)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc


@router.patch("/{job_id}/state", response_model=JobStatePayload)
def patch_job_state(
    job_id: str,
    request: JobStatePatchRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> JobStatePayload:
    expected_revision, if_match_used = requested_job_state_revision(
        request.revision,
        if_match,
    )
    try:
        record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found",
            )
        if record.revision != expected_revision:
            raise job_state_conflict(record, if_match_used=if_match_used)

        changed_at = datetime.now(UTC)
        if request.saved is not None:
            record.saved_at = record.saved_at or changed_at if request.saved else None
        if request.archived is not None:
            record.archived_at = record.archived_at or changed_at if request.archived else None
        if request.dismissed is not None:
            if request.dismissed:
                record.status = DISMISSED_JOB_STATUS
                record.dismissed_at = record.dismissed_at or changed_at
            else:
                record.status = ACTIVE_JOB_STATUS
                record.dismissed_at = None

        db.commit()
        db.refresh(record)
        set_job_state_etag(response, record.revision)
        return job_state_payload(record)
    except HTTPException:
        db.rollback()
        raise
    except StaleDataError as exc:
        db.rollback()
        current_record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
        raise job_state_conflict(
            current_record,
            if_match_used=if_match_used,
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job state could not be saved",
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
        return
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jobs database is unavailable",
        ) from exc
