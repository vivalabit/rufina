from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped
from app.models.generation import GenerationStartRequest

GenerationRunStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
]
GenerationRunStage = Literal[
    "sources",
    "fit",
    "draft",
    "review",
    "pdf_checks",
    "final_review",
]
GenerationActor = Literal["system", "author", "reviewer", "user"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class ApplicationGenerationRunRecord(OwnerScoped, Base):
    __tablename__ = "application_generation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'completed', "
            "'failed', 'cancelled')",
            name="ck_application_generation_runs_status",
        ),
        CheckConstraint(
            "stage IN ('sources', 'fit', 'draft', 'review', 'pdf_checks', 'final_review')",
            name="ck_application_generation_runs_stage",
        ),
        CheckConstraint("revision >= 1", name="ck_application_generation_runs_revision"),
        UniqueConstraint(
            "owner_id",
            "application_id",
            "idempotency_key",
            name="uq_application_generation_runs_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("stored_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="sources")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    reasoning_effort: Mapped[str] = mapped_column(String(32), nullable=False)
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    pending_question: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": revision}


class GenerationRunEventRecord(OwnerScoped, Base):
    __tablename__ = "generation_run_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_generation_run_events_sequence"),
        UniqueConstraint("run_id", "sequence", name="uq_generation_run_events_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("application_generation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GenerationRunMessageRecord(OwnerScoped, Base):
    __tablename__ = "generation_run_messages"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_generation_run_messages_sequence"),
        CheckConstraint(
            "actor IN ('system', 'author', 'reviewer', 'user')",
            name="ck_generation_run_messages_actor",
        ),
        CheckConstraint(
            "role IN ('system', 'user', 'assistant')",
            name="ck_generation_run_messages_role",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_generation_run_messages_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("application_generation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(24), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GenerationRunArtifactRecord(OwnerScoped, Base):
    __tablename__ = "generation_run_artifacts"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_generation_run_artifacts_version"),
        UniqueConstraint(
            "run_id", "artifact_type", "version", name="uq_generation_run_artifacts_version"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("application_generation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json", JSON, nullable=False, default=dict
    )
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GenerationRunCheckRecord(OwnerScoped, Base):
    __tablename__ = "generation_run_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('passed', 'failed', 'warning')",
            name="ck_generation_run_checks_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("application_generation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_run_artifacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    check_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GenerationRunStartRequest(GenerationStartRequest):
    idempotency_key: str = Field(min_length=1, max_length=160, alias="idempotencyKey")


class GenerationRunEventPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sequence: int
    kind: str
    stage: GenerationRunStage
    data: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")


class GenerationRunArtifactPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_type: str | None = Field(alias="documentType")
    artifact_type: str = Field(alias="artifactType")
    version: int
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    content_sha256: str = Field(alias="contentSha256")
    metadata: dict[str, Any]
    document_id: str | None = Field(alias="documentId")
    document_version: int | None = Field(alias="documentVersion")
    created_at: datetime = Field(alias="createdAt")


class GenerationRunCheckPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    artifact_id: str | None = Field(alias="artifactId")
    check_type: str = Field(alias="checkType")
    status: Literal["passed", "failed", "warning"]
    artifact_sha256: str | None = Field(alias="artifactSha256")
    data: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")


class GenerationRunPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    application_id: str = Field(alias="applicationId")
    status: GenerationRunStatus
    stage: GenerationRunStage
    revision: int
    backend: str
    model: str
    reasoning_effort: str = Field(alias="reasoningEffort")
    input_fingerprint: str = Field(alias="inputFingerprint")
    document_types: list[str] = Field(alias="documentTypes")
    pending_question: dict[str, Any] | None = Field(alias="pendingQuestion")
    result: dict[str, Any]
    error: dict[str, Any] | None
    cancel_requested: bool = Field(alias="cancelRequested")
    events: list[GenerationRunEventPayload]
    artifacts: list[GenerationRunArtifactPayload]
    checks: list[GenerationRunCheckPayload]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    completed_at: datetime | None = Field(alias="completedAt")


class GenerationRunCancelRequest(BaseModel):
    revision: int = Field(ge=1)


class GenerationRunAnswerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question_id: str = Field(min_length=1, max_length=160, alias="questionId")
    response: Literal["continue", "stop"]
    revision: int = Field(ge=1)


__all__ = [
    "ApplicationGenerationRunRecord",
    "GenerationActor",
    "GenerationRunAnswerRequest",
    "GenerationRunArtifactPayload",
    "GenerationRunArtifactRecord",
    "GenerationRunCancelRequest",
    "GenerationRunCheckPayload",
    "GenerationRunCheckRecord",
    "GenerationRunEventPayload",
    "GenerationRunEventRecord",
    "GenerationRunMessageRecord",
    "GenerationRunPayload",
    "GenerationRunStage",
    "GenerationRunStartRequest",
    "GenerationRunStatus",
]
