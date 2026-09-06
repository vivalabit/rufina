from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped
from app.core.identity import DEFAULT_OWNER_ID

JOB_STATE_PLACEHOLDER_KEY = "_jobStatePlaceholder"


class StoredJobRecord(OwnerScoped, Base):
    __tablename__ = "stored_jobs"

    owner_id: Mapped[str] = mapped_column(
        String(160),
        primary_key=True,
        default=DEFAULT_OWNER_ID,
        index=True,
    )
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    search_config_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    search_config_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    screening_config_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    screening_config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": revision}


def is_job_state_placeholder(record: StoredJobRecord) -> bool:
    return (
        isinstance(record.data, dict)
        and record.data.get(JOB_STATE_PLACEHOLDER_KEY) is True
    )


def is_replaceable_job_state_placeholder(record: StoredJobRecord) -> bool:
    return is_job_state_placeholder(record) and record.status != "dismissed"


class DiscoveredVacancyRecord(OwnerScoped, Base):
    __tablename__ = "discovered_vacancies"
    __table_args__ = (
        CheckConstraint(
            "availability IN ('active', 'inactive')",
            name="ck_discovered_vacancies_availability",
        ),
        Index(
            "ix_discovered_vacancies_owner_url_hash",
            "owner_id",
            "url_hash",
        ),
        Index(
            "ix_discovered_vacancies_owner_identity_hash",
            "owner_id",
            "identity_hash",
        ),
        Index(
            "ix_discovered_vacancies_owner_source_availability",
            "owner_id",
            "source",
            "availability",
        ),
    )

    owner_id: Mapped[str] = mapped_column(
        String(160),
        primary_key=True,
        default=DEFAULT_OWNER_ID,
        index=True,
    )
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    source: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    vacancy_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    last_seen_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    availability: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )
    unavailable_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class JobMatchRecord(OwnerScoped, Base):
    __tablename__ = "job_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    vacancy_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")
    backend: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False, default="openclaw_codex"
    )
    prompt_version: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    matcher_version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    gaps: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    heuristic_score: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class JobMatchFeedbackRecord(OwnerScoped, Base):
    __tablename__ = "job_match_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    matcher_version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    feedback: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class StoredJobPayload(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    data: dict[str, Any]


class StoredJobsRequest(BaseModel):
    jobs: list[StoredJobPayload] = Field(default_factory=list)


class JobStatePayload(BaseModel):
    job_id: str = Field(alias="jobId")
    saved: bool
    archived: bool
    dismissed: bool
    saved_at: datetime | None = Field(alias="savedAt")
    archived_at: datetime | None = Field(alias="archivedAt")
    dismissed_at: datetime | None = Field(alias="dismissedAt")
    updated_at: datetime = Field(alias="updatedAt")
    revision: int = Field(ge=1)

    model_config = {"populate_by_name": True}


class JobStatePatchRequest(BaseModel):
    saved: bool | None = None
    archived: bool | None = None
    dismissed: bool | None = None
    revision: int | None = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def require_state_change(self) -> "JobStatePatchRequest":
        if self.saved is None and self.archived is None and self.dismissed is None:
            raise ValueError("At least one job state field must be provided")
        return self


class AiMatchJobFailure(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    error: str = Field(min_length=1, max_length=240)


class AiMatchJobStatus(BaseModel):
    run_id: str = Field(default="", alias="runId")
    status: Literal["idle", "queued", "running", "completed", "failed"] = "idle"
    total: int = 0
    processed: int = 0
    updated_jobs: list[StoredJobPayload] = Field(default_factory=list, alias="updatedJobs")
    failed_jobs: list[AiMatchJobFailure] = Field(default_factory=list, alias="failedJobs")
    error: str | None = None

    model_config = {"populate_by_name": True}
