from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.database import get_db
from app.core.identity import bind_request_identity, get_bound_owner_id
from app.models.applications import (
    StoredApplicationEventInput,
    StoredApplicationEventPatchRequest,
    StoredApplicationEventPayload,
    StoredApplicationEventRecord,
    StoredApplicationInput,
    StoredApplicationPatchRequest,
    StoredApplicationPayload,
    StoredApplicationRecord,
)
from app.models.documents import WorkspaceSourceDocumentRecord
from app.models.jobs import StoredJobRecord
from app.services.job_match_store import (
    authoritative_match_to_ai_match,
    latest_job_match_record,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])


def parse_if_match(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    value = if_match.strip()
    if value.startswith("W/"):
        value = value[2:].strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    try:
        revision = int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='If-Match must contain a single numeric revision, for example "3"',
        ) from exc
    if revision < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match revision must be positive",
        )
    return revision


def expected_revision(
    body_revision: int | None,
    if_match: str | None,
) -> int | None:
    header_revision = parse_if_match(if_match)
    if (
        body_revision is not None
        and header_revision is not None
        and body_revision != header_revision
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body revision and If-Match revision do not match",
        )
    return header_revision if header_revision is not None else body_revision


def require_current_revision(record_revision: int, expected: int | None) -> None:
    if expected is not None and record_revision != expected:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "message": "Resource revision is stale",
                "current_revision": record_revision,
            },
            headers={"ETag": f'"{record_revision}"'},
        )


def set_revision_etag(response: Response, revision: int) -> None:
    response.headers["ETag"] = f'"{revision}"'


def concurrent_change_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail="Resource changed while the request was being saved",
    )


def application_payload(
    db: Session,
    record: StoredApplicationRecord,
) -> StoredApplicationPayload:
    data = dict(record.data) if isinstance(record.data, dict) else {}
    data.pop("documents", None)
    raw_job = data.get("job")
    job_id = str(raw_job.get("id") or "").strip() if isinstance(raw_job, dict) else ""
    stored_job = db.get(StoredJobRecord, (get_bound_owner_id(), job_id)) if job_id else None
    if stored_job and isinstance(stored_job.data, dict):
        job = dict(stored_job.data)
        job["id"] = job_id
    else:
        job = dict(raw_job) if isinstance(raw_job, dict) else {}
    job.pop("aiMatch", None)

    match_record = latest_job_match_record(db, job_id=job_id) if job_id else None
    if match_record:
        job["match"] = match_record.score
        job["aiMatch"] = authoritative_match_to_ai_match(match_record)
    if job:
        data["job"] = job
    return StoredApplicationPayload(
        id=record.id,
        data=data,
        created_at=record.created_at,
        updated_at=record.updated_at,
        revision=record.revision,
    )


def application_event_payload(
    record: StoredApplicationEventRecord,
) -> StoredApplicationEventPayload:
    return StoredApplicationEventPayload(
        id=record.id,
        application_id=record.application_id,
        data=record.data,
        created_at=record.created_at,
        updated_at=record.updated_at,
        revision=record.revision,
    )


def strip_client_application_analysis(data: dict[str, object]) -> dict[str, object]:
    sanitized = dict(data)
    sanitized.pop("documents", None)
    raw_job = sanitized.get("job")
    if isinstance(raw_job, dict):
        job = dict(raw_job)
        job.pop("aiMatch", None)
        sanitized["job"] = job
    return sanitized


@router.get("", response_model=list[StoredApplicationPayload])
def list_applications(db: Session = Depends(get_db)) -> list[StoredApplicationPayload]:
    try:
        records = (
            db.query(StoredApplicationRecord).order_by(StoredApplicationRecord.id.desc()).all()
        )
        return [application_payload(db, record) for record in records]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Applications database is unavailable",
        ) from exc


@router.post(
    "",
    response_model=StoredApplicationPayload,
    status_code=status.HTTP_201_CREATED,
)
def create_application(
    request: StoredApplicationInput,
    response: Response,
    db: Session = Depends(get_db),
) -> StoredApplicationPayload:
    try:
        if db.get(StoredApplicationRecord, request.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application already exists",
            )
        record = StoredApplicationRecord(
            id=request.id,
            data=strip_client_application_analysis(request.data),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        set_revision_etag(response, record.revision)
        return application_payload(db, record)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application already exists",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application could not be created",
        ) from exc


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: str,
    revision: int | None = Query(default=None, ge=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> None:
    try:
        record = db.get(StoredApplicationRecord, application_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        require_current_revision(
            record.revision,
            expected_revision(revision, if_match),
        )

        related_events = (
            db.query(StoredApplicationEventRecord)
            .filter(StoredApplicationEventRecord.application_id == application_id)
            .all()
        )
        for event in related_events:
            db.delete(event)

        db.query(WorkspaceSourceDocumentRecord).filter(
            WorkspaceSourceDocumentRecord.application_id == application_id
        ).delete()

        db.delete(record)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except StaleDataError as exc:
        db.rollback()
        raise concurrent_change_error() from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Applications database is unavailable",
        ) from exc


@router.get("/events", response_model=list[StoredApplicationEventPayload])
def list_application_events(db: Session = Depends(get_db)) -> list[StoredApplicationEventPayload]:
    try:
        records = (
            db.query(StoredApplicationEventRecord)
            .order_by(StoredApplicationEventRecord.id.desc())
            .all()
        )
        return [application_event_payload(record) for record in records]
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application events database is unavailable",
        ) from exc


@router.post(
    "/events",
    response_model=StoredApplicationEventPayload,
    status_code=status.HTTP_201_CREATED,
)
def create_application_event(
    request: StoredApplicationEventInput,
    response: Response,
    db: Session = Depends(get_db),
) -> StoredApplicationEventPayload:
    try:
        if db.get(StoredApplicationEventRecord, request.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application event already exists",
            )
        if not db.get(StoredApplicationRecord, request.application_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        record = StoredApplicationEventRecord(
            id=request.id,
            application_id=request.application_id,
            data=request.data,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        set_revision_etag(response, record.revision)
        return application_event_payload(record)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application event already exists",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application event could not be created",
        ) from exc


@router.get("/events/{event_id}", response_model=StoredApplicationEventPayload)
def get_application_event(
    event_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> StoredApplicationEventPayload:
    try:
        record = db.get(StoredApplicationEventRecord, event_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application event not found",
            )
        set_revision_etag(response, record.revision)
        return application_event_payload(record)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application event is unavailable",
        ) from exc


@router.patch("/events/{event_id}", response_model=StoredApplicationEventPayload)
def update_application_event(
    event_id: str,
    event: StoredApplicationEventPatchRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> StoredApplicationEventPayload:
    if event.id is not None and event.id != event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Application event id does not match request path",
        )

    try:
        record = db.get(StoredApplicationEventRecord, event_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application event not found",
            )
        require_current_revision(
            record.revision,
            expected_revision(event.revision, if_match),
        )
        if event.application_id is not None:
            if not db.get(StoredApplicationRecord, event.application_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Application not found",
                )
            record.application_id = event.application_id
        if event.data is not None:
            merged_data = dict(record.data) if isinstance(record.data, dict) else {}
            merged_data.update(event.data)
            record.data = merged_data
        if event.application_id is None and event.data is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Application event patch is empty",
            )
        record.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(record)
        set_revision_etag(response, record.revision)
        return application_event_payload(record)
    except HTTPException:
        db.rollback()
        raise
    except StaleDataError as exc:
        db.rollback()
        raise concurrent_change_error() from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application events database is unavailable",
        ) from exc


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application_event(
    event_id: str,
    revision: int | None = Query(default=None, ge=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> None:
    try:
        record = db.get(StoredApplicationEventRecord, event_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application event not found",
            )
        require_current_revision(
            record.revision,
            expected_revision(revision, if_match),
        )
        db.delete(record)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except StaleDataError as exc:
        db.rollback()
        raise concurrent_change_error() from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application events database is unavailable",
        ) from exc


@router.get("/{application_id}", response_model=StoredApplicationPayload)
def get_application(
    application_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> StoredApplicationPayload:
    try:
        record = db.get(StoredApplicationRecord, application_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        set_revision_etag(response, record.revision)
        return application_payload(db, record)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application is unavailable",
        ) from exc


@router.patch("/{application_id}", response_model=StoredApplicationPayload)
def update_application(
    application_id: str,
    request: StoredApplicationPatchRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> StoredApplicationPayload:
    try:
        record = db.get(StoredApplicationRecord, application_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        require_current_revision(
            record.revision,
            expected_revision(request.revision, if_match),
        )
        merged_data = dict(record.data) if isinstance(record.data, dict) else {}
        merged_data.update(request.data)
        record.data = strip_client_application_analysis(merged_data)
        record.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(record)
        set_revision_etag(response, record.revision)
        return application_payload(db, record)
    except HTTPException:
        db.rollback()
        raise
    except StaleDataError as exc:
        db.rollback()
        raise concurrent_change_error() from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application could not be updated",
        ) from exc
