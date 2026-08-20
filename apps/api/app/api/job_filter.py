from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import (
    RequestIdentity,
    bind_request_identity,
    get_request_identity,
)
from app.models.job_filter import (
    JobFilterSettingsPayload,
    JobFilterSettingsUpdateRequest,
)
from app.services.job_filter_settings import (
    JobFilterSettingsStorageError,
    get_job_filter_settings,
    upsert_job_filter_settings,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])


@router.get(
    "/filter-settings",
    response_model=JobFilterSettingsPayload,
    response_model_exclude_none=True,
)
def read_job_filter_settings(
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
) -> JobFilterSettingsPayload:
    try:
        return get_job_filter_settings(db, identity.owner_id)
    except JobFilterSettingsStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.put(
    "/filter-settings",
    response_model=JobFilterSettingsPayload,
    response_model_exclude_none=True,
)
def replace_job_filter_settings(
    request: JobFilterSettingsUpdateRequest,
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
) -> JobFilterSettingsPayload:
    try:
        payload = upsert_job_filter_settings(
            db,
            owner_id=identity.owner_id,
            settings=request,
        )
        db.commit()
        return payload
    except JobFilterSettingsStorageError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


def database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Job filter settings database is unavailable",
    )
