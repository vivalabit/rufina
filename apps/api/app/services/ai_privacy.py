from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import RequestIdentity, get_request_identity
from app.core.settings import Settings, get_settings
from app.models.assistant import AppliedAssistantActionRecord
from app.models.conversations import ConversationRecord
from app.models.documents import (
    DocumentPackJobRecord,
    DocumentRecord,
    DocumentValidationArtifactRecord,
    utc_now,
)
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.jobs import JobMatchRecord
from app.models.privacy import AiPrivacySettingsRecord
from app.models.profile import CandidateMatchSnapshotRecord
from app.models.resume import ImaginatorResumeRecord


def privacy_settings_record(
    db: Session,
    owner_id: str,
) -> AiPrivacySettingsRecord | None:
    return db.scalar(
        select(AiPrivacySettingsRecord).where(
            AiPrivacySettingsRecord.owner_id == owner_id
        )
    )


def has_current_ai_consent(
    record: AiPrivacySettingsRecord | None,
    settings: Settings,
) -> bool:
    return bool(
        record
        and record.consented_at is not None
        and record.consent_version == settings.ai_consent_version
        and record.consent_backend == settings.ai_backend_mode
    )


def require_current_ai_consent(
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AiPrivacySettingsRecord:
    record = privacy_settings_record(db, identity.owner_id)
    if not has_current_ai_consent(record, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ai_consent_required",
                "message": "Current AI data-processing consent is required",
                "requiredVersion": settings.ai_consent_version,
                "requiredBackend": settings.ai_backend_mode,
            },
        )

    assert record is not None
    now = utc_now()
    record.last_ai_activity_at = now
    record.ai_data_expires_at = now + timedelta(days=record.retention_days)
    record.updated_at = now
    db.commit()
    return record


def delete_ai_data_for_owner(db: Session, owner_id: str) -> int:
    deleted = 0
    models = (
        AppliedAssistantActionRecord,
        ConversationRecord,
        DocumentValidationArtifactRecord,
        DocumentPackJobRecord,
        DocumentRecord,
        JobScreeningDecisionRecord,
        JobMatchRecord,
        CandidateMatchSnapshotRecord,
        ImaginatorResumeRecord,
    )
    for model in models:
        result = db.execute(delete(model).where(model.owner_id == owner_id))
        deleted += result.rowcount or 0

    record = privacy_settings_record(db, owner_id)
    if record:
        record.last_ai_activity_at = None
        record.ai_data_expires_at = None
        record.updated_at = utc_now()
    return deleted


def cleanup_expired_ai_data(
    db: Session,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    cutoff = now or utc_now()
    owner_ids = db.scalars(
        select(AiPrivacySettingsRecord.owner_id).where(
            AiPrivacySettingsRecord.ai_data_expires_at.is_not(None),
            AiPrivacySettingsRecord.ai_data_expires_at <= cutoff,
        )
    ).all()
    deleted_records = 0
    for owner_id in owner_ids:
        deleted_records += delete_ai_data_for_owner(db, owner_id)
    db.commit()
    return len(owner_ids), deleted_records
