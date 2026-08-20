from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.job_filter import (
    JobFilterSettings,
    JobFilterSettingsPayload,
    JobFilterSettingsRecord,
    JobFilterSettingsUpdateRequest,
    utc_now,
)


class JobFilterSettingsStorageError(RuntimeError):
    pass


def get_job_filter_settings(
    db: Session,
    owner_id: str,
) -> JobFilterSettingsPayload:
    record = db.get(JobFilterSettingsRecord, owner_id)
    if record is None:
        return JobFilterSettingsPayload()
    try:
        settings = JobFilterSettings.model_validate(record.data)
    except ValidationError as exc:
        raise JobFilterSettingsStorageError("Stored job filter settings are invalid") from exc
    return payload_from_settings(settings, updated_at=record.updated_at)


def upsert_job_filter_settings(
    db: Session,
    *,
    owner_id: str,
    settings: JobFilterSettingsUpdateRequest,
    updated_at: datetime | None = None,
) -> JobFilterSettingsPayload:
    changed_at = updated_at or utc_now()
    data = job_filter_settings_snapshot(settings)
    values = {
        "owner_id": owner_id,
        "data": data,
        "updated_at": changed_at,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        insert = postgresql_insert(JobFilterSettingsRecord).values(**values)
        statement = insert.on_conflict_do_update(
            index_elements=[JobFilterSettingsRecord.owner_id],
            set_={
                "data": insert.excluded.data,
                "updated_at": insert.excluded.updated_at,
            },
        )
    elif dialect == "sqlite":
        insert = sqlite_insert(JobFilterSettingsRecord).values(**values)
        statement = insert.on_conflict_do_update(
            index_elements=[JobFilterSettingsRecord.owner_id],
            set_={
                "data": insert.excluded.data,
                "updated_at": insert.excluded.updated_at,
            },
        )
    else:
        raise JobFilterSettingsStorageError(
            f"Unsupported job filter settings database dialect: {dialect}"
        )
    db.execute(statement)
    return payload_from_settings(settings, updated_at=changed_at)


def job_filter_settings_snapshot(
    settings: JobFilterSettings,
) -> dict[str, Any]:
    return settings.model_dump(
        by_alias=True,
        exclude={"updated_at"},
    )


def job_filter_settings_from_snapshot(value: object) -> JobFilterSettings:
    if value is None:
        return JobFilterSettings()
    return JobFilterSettings.model_validate(value)


def payload_from_settings(
    settings: JobFilterSettings,
    *,
    updated_at: datetime | None,
) -> JobFilterSettingsPayload:
    return JobFilterSettingsPayload.model_validate(
        {
            **job_filter_settings_snapshot(settings),
            "updatedAt": updated_at,
        }
    )
