from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.database import get_db
from app.core.identity import bind_request_identity, get_bound_owner_id
from app.models.applications import (
    ApplicationPreferencePayload,
    ApplicationPreferenceRecord,
    ApplicationPreferenceUpsertRequest,
    CandidateConfirmationPayload,
    CandidateConfirmationRecord,
    CandidateConfirmationsRequest,
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
from app.services.generation_context import (
    ClarificationQuestion,
    GenerationContextError,
    clarification_questions,
    load_stored_application_guide,
)
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


def application_preference_record(
    db: Session,
    application_id: str,
) -> ApplicationPreferenceRecord | None:
    return (
        db.query(ApplicationPreferenceRecord)
        .filter(ApplicationPreferenceRecord.application_id == application_id)
        .one_or_none()
    )


def application_preference_payload(
    record: ApplicationPreferenceRecord,
) -> ApplicationPreferencePayload:
    return ApplicationPreferencePayload(
        application_id=record.application_id,
        resume_template_id=record.resume_template_id,
        resume_generation_mode=record.resume_generation_mode,
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


def confirmation_payload(record: CandidateConfirmationRecord) -> CandidateConfirmationPayload:
    return CandidateConfirmationPayload(
        questionId=record.question_id,
        requirement=record.requirement,
        response=record.response,
        exampleText=record.example_text,
        blocking=record.blocking,
        updatedAt=record.updated_at,
    )


def stored_clarification_questions(
    db: Session,
    application: StoredApplicationRecord,
) -> dict[str, ClarificationQuestion]:
    application_data = application.data if isinstance(application.data, dict) else {}
    job = application_data.get("job")
    job_id = str(job.get("id") or "").strip() if isinstance(job, dict) else ""
    if not job_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application does not reference a job with a stored ai-match-v3",
        )

    try:
        application_guide = load_stored_application_guide(db, job_id=job_id)
        return {
            question.question_id: question
            for question in clarification_questions(application_guide)
        }
    except GenerationContextError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc


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


@router.get("/{application_id}/analysis", response_model=StoredApplicationPayload)
def get_authoritative_application_analysis(
    application_id: str,
    db: Session = Depends(get_db),
) -> StoredApplicationPayload:
    try:
        record = db.get(StoredApplicationRecord, application_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        return application_payload(db, record)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authoritative application analysis is unavailable",
        ) from exc


@router.get(
    "/{application_id}/confirmations",
    response_model=list[CandidateConfirmationPayload],
)
def list_candidate_confirmations(
    application_id: str,
    db: Session = Depends(get_db),
) -> list[CandidateConfirmationPayload]:
    try:
        if not db.get(StoredApplicationRecord, application_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        records = (
            db.query(CandidateConfirmationRecord)
            .filter(CandidateConfirmationRecord.application_id == application_id)
            .order_by(CandidateConfirmationRecord.question_id)
            .all()
        )
        return [confirmation_payload(record) for record in records]
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate confirmations are unavailable",
        ) from exc


@router.put(
    "/{application_id}/confirmations",
    response_model=list[CandidateConfirmationPayload],
)
def replace_candidate_confirmations(
    application_id: str,
    request: CandidateConfirmationsRequest,
    db: Session = Depends(get_db),
) -> list[CandidateConfirmationPayload]:
    try:
        application = db.get(StoredApplicationRecord, application_id)
        if not application:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )

        questions_by_id = stored_clarification_questions(db, application)

        question_ids = [confirmation.question_id for confirmation in request.confirmations]
        if len(question_ids) != len(set(question_ids)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Candidate confirmation question IDs must be unique",
            )

        unknown_question_ids = set(question_ids) - set(questions_by_id)
        if unknown_question_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Unknown candidate confirmation question IDs: "
                    f"{', '.join(sorted(unknown_question_ids))}"
                ),
            )
        existing_records = {
            record.question_id: record
            for record in db.query(CandidateConfirmationRecord)
            .filter(CandidateConfirmationRecord.application_id == application_id)
            .all()
        }
        now = datetime.now(UTC)
        requested_ids = set(question_ids)

        for question_id, record in existing_records.items():
            if question_id not in requested_ids:
                db.delete(record)

        for confirmation in request.confirmations:
            question = questions_by_id[confirmation.question_id]
            example_text = confirmation.example_text.strip()
            record = existing_records.get(confirmation.question_id)
            if record:
                has_changed = (
                    record.requirement != question.requirement
                    or record.response != confirmation.response
                    or record.example_text != example_text
                    or record.blocking != question.blocking
                )
                record.requirement = question.requirement
                record.response = confirmation.response
                record.example_text = example_text
                record.blocking = question.blocking
                if has_changed:
                    record.updated_at = now
            else:
                db.add(
                    CandidateConfirmationRecord(
                        application_id=application_id,
                        question_id=confirmation.question_id,
                        requirement=question.requirement,
                        response=confirmation.response,
                        example_text=example_text,
                        blocking=question.blocking,
                        updated_at=now,
                    )
                )

        db.commit()
        return list_candidate_confirmations(application_id, db)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate confirmations could not be saved",
        ) from exc


@router.get(
    "/{application_id}/preferences",
    response_model=ApplicationPreferencePayload,
)
def get_application_preferences(
    application_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> ApplicationPreferencePayload:
    try:
        if not db.get(StoredApplicationRecord, application_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        record = application_preference_record(db, application_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application preferences not found",
            )
        set_revision_etag(response, record.revision)
        return application_preference_payload(record)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application preferences are unavailable",
        ) from exc


def save_application_preferences(
    application_id: str,
    request: ApplicationPreferenceUpsertRequest,
    *,
    allow_create: bool,
    if_match: str | None,
    response: Response,
    db: Session,
) -> ApplicationPreferencePayload:
    if not db.get(StoredApplicationRecord, application_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    record = application_preference_record(db, application_id)
    supplied_fields = request.model_fields_set - {"revision"}
    requested_revision = expected_revision(request.revision, if_match)
    if not supplied_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one application preference must be supplied",
        )
    if record is None:
        if not allow_create:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application preferences not found",
            )
        if requested_revision is not None:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="Application preferences do not exist at the requested revision",
            )
        record = ApplicationPreferenceRecord(application_id=application_id)
        db.add(record)
    else:
        require_current_revision(record.revision, requested_revision)

    if "resume_template_id" in supplied_fields:
        record.resume_template_id = request.resume_template_id
    if "resume_generation_mode" in supplied_fields:
        record.resume_generation_mode = request.resume_generation_mode
    if supplied_fields:
        record.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(record)
    set_revision_etag(response, record.revision)
    return application_preference_payload(record)


@router.put(
    "/{application_id}/preferences",
    response_model=ApplicationPreferencePayload,
)
def upsert_application_preferences(
    application_id: str,
    request: ApplicationPreferenceUpsertRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> ApplicationPreferencePayload:
    try:
        return save_application_preferences(
            application_id,
            request,
            allow_create=True,
            if_match=if_match,
            response=response,
            db=db,
        )
    except HTTPException:
        db.rollback()
        raise
    except StaleDataError as exc:
        db.rollback()
        raise concurrent_change_error() from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application preferences already exist",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application preferences could not be saved",
        ) from exc


@router.patch(
    "/{application_id}/preferences",
    response_model=ApplicationPreferencePayload,
)
def update_application_preferences(
    application_id: str,
    request: ApplicationPreferenceUpsertRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> ApplicationPreferencePayload:
    try:
        return save_application_preferences(
            application_id,
            request,
            allow_create=False,
            if_match=if_match,
            response=response,
            db=db,
        )
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
            detail="Application preferences could not be saved",
        ) from exc


@router.delete(
    "/{application_id}/preferences",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_application_preferences(
    application_id: str,
    revision: int | None = Query(default=None, ge=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> None:
    try:
        record = application_preference_record(db, application_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application preferences not found",
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
            detail="Application preferences could not be deleted",
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

        preference = application_preference_record(db, application_id)
        if preference:
            db.delete(preference)

        db.query(CandidateConfirmationRecord).filter(
            CandidateConfirmationRecord.application_id == application_id
        ).delete()
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
