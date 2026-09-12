import re
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped


def utc_now() -> datetime:
    return datetime.now(UTC)


INLINE_FILE_FIELD_NAMES = {
    "dataurl",
    "documents",
    "filedata",
    "legacydataurl",
    "resumedataurl",
}
SERIALIZED_DATA_URL_PATTERN = re.compile(
    r"""["']\s*data:[^,\r\n]{0,200},""",
    flags=re.IGNORECASE,
)


def sanitize_file_free_json(value: dict[str, Any]) -> dict[str, Any]:
    """Reject inline bytes anywhere in application/event JSON and drop empty file keys."""

    def sanitize(candidate: Any) -> Any:
        if isinstance(candidate, dict):
            sanitized: dict[str, Any] = {}
            for key, nested in candidate.items():
                normalized_key = re.sub(r"[_-]+", "", str(key)).casefold()
                if normalized_key in INLINE_FILE_FIELD_NAMES:
                    if nested not in (None, "", [], {}):
                        raise ValueError("Files must be uploaded through the binary document API")
                    continue
                sanitized[str(key)] = sanitize(nested)
            return sanitized
        if isinstance(candidate, list):
            return [sanitize(item) for item in candidate]
        if isinstance(candidate, str):
            normalized = candidate.strip().casefold()
            if normalized.startswith("data:") or SERIALIZED_DATA_URL_PATTERN.search(candidate):
                raise ValueError("Files must be uploaded through the binary document API")
        return candidate

    return sanitize(value)


class StoredApplicationRecord(OwnerScoped, Base):
    __tablename__ = "stored_applications"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": revision}


class StoredApplicationEventRecord(OwnerScoped, Base):
    __tablename__ = "stored_application_events"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(160), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": revision}


class StoredApplicationInput(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    data: dict[str, Any]

    @field_validator("data")
    @classmethod
    def reject_inline_documents(cls, value: dict[str, Any]) -> dict[str, Any]:
        return sanitize_file_free_json(value)


class StoredApplicationPayload(StoredApplicationInput):
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)


class StoredApplicationPatchRequest(BaseModel):
    data: dict[str, Any]
    revision: int | None = Field(default=None, ge=1)

    @field_validator("data")
    @classmethod
    def reject_inline_documents(cls, value: dict[str, Any]) -> dict[str, Any]:
        return sanitize_file_free_json(value)

    model_config = {"extra": "forbid"}


class StoredApplicationEventInput(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    application_id: str = Field(min_length=1, max_length=160)
    data: dict[str, Any]

    @field_validator("data")
    @classmethod
    def reject_inline_files(cls, value: dict[str, Any]) -> dict[str, Any]:
        return sanitize_file_free_json(value)


class StoredApplicationEventPayload(StoredApplicationEventInput):
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)


class StoredApplicationEventPatchRequest(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=160)
    application_id: str | None = Field(default=None, min_length=1, max_length=160)
    data: dict[str, Any] | None = None
    revision: int | None = Field(default=None, ge=1)

    @field_validator("data")
    @classmethod
    def reject_inline_files(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return sanitize_file_free_json(value) if value is not None else None

    model_config = {"extra": "forbid"}
