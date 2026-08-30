from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped


def utc_now() -> datetime:
    return datetime.now(UTC)


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


class ApplicationPreferenceRecord(OwnerScoped, Base):
    __tablename__ = "application_preferences"
    __table_args__ = (
        CheckConstraint(
            "resume_generation_mode IS NULL OR "
            "resume_generation_mode IN ('recruiter_xyz_ats', 'imaginator')",
            name="ck_application_preferences_resume_generation_mode",
        ),
    )

    # Preference identity is owner-local even though legacy application IDs are
    # globally keyed. This avoids a cross-owner collision if that legacy
    # constraint is relaxed later.
    owner_id: Mapped[str] = mapped_column(
        String(160),
        primary_key=True,
        nullable=False,
        index=True,
    )
    application_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("stored_applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    resume_template_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resume_generation_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": revision}


class CandidateConfirmationRecord(OwnerScoped, Base):
    __tablename__ = "candidate_confirmations"

    application_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    requirement: Mapped[str] = mapped_column(String(500), nullable=False)
    response: Mapped[str] = mapped_column(String(16), nullable=False)
    example_text: Mapped[str] = mapped_column(String(1500), nullable=False, default="")
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoredApplicationInput(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    data: dict[str, Any]


class StoredApplicationsRequest(BaseModel):
    applications: list[StoredApplicationInput] = Field(default_factory=list)


class StoredApplicationPayload(StoredApplicationInput):
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)


class StoredApplicationPatchRequest(BaseModel):
    data: dict[str, Any]
    revision: int | None = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}


class StoredApplicationEventInput(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    application_id: str = Field(min_length=1, max_length=160)
    data: dict[str, Any]


class StoredApplicationEventsRequest(BaseModel):
    events: list[StoredApplicationEventInput] = Field(default_factory=list)


class StoredApplicationEventPayload(StoredApplicationEventInput):
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)


class StoredApplicationEventPatchRequest(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=160)
    application_id: str | None = Field(default=None, min_length=1, max_length=160)
    data: dict[str, Any] | None = None
    revision: int | None = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}


ResumeGenerationMode = Literal["recruiter_xyz_ats", "imaginator"]


class ApplicationPreferenceUpsertRequest(BaseModel):
    resume_template_id: str | None = Field(default=None, min_length=1, max_length=160)
    resume_generation_mode: ResumeGenerationMode | None = None
    revision: int | None = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}


class ApplicationPreferencePayload(BaseModel):
    application_id: str
    resume_template_id: str | None
    resume_generation_mode: ResumeGenerationMode | None
    updated_at: datetime
    revision: int = Field(ge=1)


class CandidateConfirmationInput(BaseModel):
    question_id: str = Field(min_length=1, max_length=160, alias="questionId")
    response: Literal["yes", "no", "partial"]
    example_text: str = Field(default="", max_length=1500, alias="exampleText")

    model_config = {"populate_by_name": True, "extra": "forbid"}


class CandidateConfirmationsRequest(BaseModel):
    confirmations: list[CandidateConfirmationInput] = Field(default_factory=list, max_length=20)

    model_config = {"populate_by_name": True, "extra": "forbid"}


class CandidateConfirmationPayload(BaseModel):
    question_id: str = Field(min_length=1, max_length=160, alias="questionId")
    requirement: str = Field(max_length=500)
    response: Literal["yes", "no", "partial"]
    example_text: str = Field(default="", max_length=1500, alias="exampleText")
    blocking: bool
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}
