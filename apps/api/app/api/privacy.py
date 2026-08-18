from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import (
    RequestIdentity,
    bind_request_identity,
    get_request_identity,
)
from app.core.settings import Settings, get_settings
from app.models.documents import utc_now
from app.models.privacy import (
    AiPrivacySettingsPayload,
    AiPrivacySettingsRecord,
    AiRetentionUpdateRequest,
)
from app.services.ai_backend import ai_backend_provider_name
from app.services.ai_privacy import (
    delete_ai_data_for_owner,
    ensure_ai_privacy_settings,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])


@router.get("/ai-retention", response_model=AiPrivacySettingsPayload)
def get_ai_privacy_settings(
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AiPrivacySettingsPayload:
    try:
        record = ensure_ai_privacy_settings(db, identity.owner_id)
        db.commit()
        db.refresh(record)
        return privacy_payload(record, settings)
    except SQLAlchemyError as exc:
        db.rollback()
        raise privacy_database_unavailable(exc) from exc


@router.put("/ai-retention", response_model=AiPrivacySettingsPayload)
def update_ai_retention(
    request: AiRetentionUpdateRequest,
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AiPrivacySettingsPayload:
    try:
        record = ensure_ai_privacy_settings(db, identity.owner_id)
        record.retention_days = request.retention_days
        if record.last_ai_activity_at is not None:
            record.ai_data_expires_at = record.last_ai_activity_at + timedelta(
                days=request.retention_days
            )
        record.updated_at = utc_now()
        db.commit()
        db.refresh(record)
        return privacy_payload(record, settings)
    except SQLAlchemyError as exc:
        db.rollback()
        raise privacy_database_unavailable(exc) from exc


@router.delete("/ai-data", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_data(
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
) -> Response:
    try:
        discard_owner_assistant_streams(identity.owner_id)
        delete_ai_data_for_owner(db, identity.owner_id)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except SQLAlchemyError as exc:
        db.rollback()
        raise privacy_database_unavailable(exc) from exc


def privacy_payload(
    record: AiPrivacySettingsRecord,
    settings: Settings,
) -> AiPrivacySettingsPayload:
    return AiPrivacySettingsPayload(
        provider_name=ai_backend_provider_name(settings.ai_backend_mode),
        current_backend=settings.ai_backend_mode,
        retention_days=record.retention_days,
        last_ai_activity_at=record.last_ai_activity_at,
        ai_data_expires_at=record.ai_data_expires_at,
    )


def privacy_database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="AI privacy settings database is unavailable",
    )


def discard_owner_assistant_streams(owner_id: str) -> None:
    # Imported lazily to avoid a module cycle with assistant routes.
    from app.api.assistant import discard_owner_assistant_streams as discard_streams

    discard_streams(owner_id)
