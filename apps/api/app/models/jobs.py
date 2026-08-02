from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped
from app.core.identity import DEFAULT_OWNER_ID


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
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
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


class DismissedJobIdsRequest(BaseModel):
    job_ids: list[str] = Field(default_factory=list, max_length=10_000)


class JobMatchFeedbackRequest(BaseModel):
    feedback: Literal["good_match", "bad_match", "not_interested"]


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
