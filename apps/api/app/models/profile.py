from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProfileRecord(OwnerScoped, Base):
    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("owner_id", name="uq_profiles_owner_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )


class ProfileVersionRecord(OwnerScoped, Base):
    __tablename__ = "profile_versions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "profile_id",
            "revision",
            name="uq_profile_versions_owner_profile_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid4().hex)
    profile_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


ProfileFileKind = Literal["primary_resume", "supporting_document", "avatar"]


class ProfileFileRecord(OwnerScoped, Base):
    __tablename__ = "profile_files"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('primary_resume', 'supporting_document', 'avatar')",
            name="ck_profile_files_kind",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_profile_files_size_positive",
        ),
        CheckConstraint(
            "(kind = 'supporting_document' AND singleton_key IS NULL) OR "
            "(kind IN ('primary_resume', 'avatar') AND singleton_key = kind)",
            name="ck_profile_files_singleton_key",
        ),
        CheckConstraint(
            "kind = 'supporting_document' OR legacy_document_id IS NULL",
            name="ck_profile_files_legacy_id_kind",
        ),
        UniqueConstraint(
            "owner_id",
            "singleton_key",
            name="uq_profile_files_owner_singleton",
        ),
        UniqueConstraint(
            "owner_id",
            "kind",
            "legacy_document_id",
            name="uq_profile_files_owner_kind_legacy",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    singleton_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    issuer: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    notes: Mapped[str] = mapped_column(String(2_000), nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    legacy_document_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
        index=True,
    )


class CandidateMatchSnapshotRecord(OwnerScoped, Base):
    __tablename__ = "candidate_match_snapshots"
    __table_args__ = (
        Index(
            "ix_candidate_match_snapshots_cache_identity",
            "profile_input_hash",
            "matcher_version",
            "source",
            "model",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_input_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    matcher_version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False, default="legacy")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provider_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class ProfilePayload(BaseModel):
    avatar_url: str = Field(default="/avatars/default-pug.png", max_length=2_000)
    name: str = Field(default="", max_length=120)
    current_role: str = Field(default="", max_length=160)
    desired_role: str = Field(default="", max_length=160)
    location: str = Field(default="", max_length=160)
    work_format: str = Field(default="", max_length=120)
    headline: str = Field(default="", max_length=600)
    linkedin: str = Field(default="", max_length=240)
    github: str = Field(default="", max_length=240)
    portfolio: str = Field(default="", max_length=240)
    personal_site: str = Field(default="", max_length=240)
    experience: str = Field(default="", max_length=12000)
    skills: str = Field(default="", max_length=2000)
    education: str = Field(default="", max_length=12000)
    job_preferences: str = Field(default="", max_length=12000)
    dealbreakers: str = Field(default="", max_length=2000)
    additional_notes: str = Field(default="", max_length=2000)
    # Legacy file-bearing fields remain readable by old callers, but are never
    # serialized or persisted by the profile API. Files belong in profile_files.
    documents: str = Field(default="", max_length=20_000_000, exclude=True, repr=False)
    resume_file_name: str = Field(default="", max_length=240)
    resume_file_size: str = Field(default="", max_length=40)
    resume_updated_at: str = Field(default="", max_length=80)
    resume_data_url: str = Field(
        default="",
        max_length=10_000_000,
        exclude=True,
        repr=False,
    )
    # Hydrated from profile_files for server-side AI calls only. These fields
    # are deliberately excluded so file-derived text and metadata can never
    # leak back into ProfileRecord/ProfileVersionRecord JSON.
    runtime_primary_resume: dict[str, Any] | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )
    runtime_supporting_documents: list[dict[str, Any]] = Field(
        default_factory=list,
        exclude=True,
        repr=False,
    )

    @field_validator("documents", "resume_data_url", mode="before")
    @classmethod
    def reject_legacy_file_payloads(cls, value: object) -> str:
        if value not in (None, "", [], {}):
            raise ValueError("Profile files must be uploaded through the binary profile file API")
        return ""

    @field_validator("avatar_url", mode="before")
    @classmethod
    def discard_inline_avatar(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().casefold().startswith("data:"):
            raise ValueError("Profile avatars must be uploaded through the binary profile file API")
        return value


class ProfileFilePayload(BaseModel):
    id: str
    kind: ProfileFileKind
    title: str
    category: str
    language: str
    issuer: str
    notes: str
    file_name: str = Field(alias="fileName")
    size_bytes: int = Field(alias="sizeBytes")
    content_type: str = Field(alias="contentType")
    content_sha256: str = Field(alias="contentSha256")
    extracted_text_available: bool = Field(alias="extractedTextAvailable")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    download_url: str = Field(alias="downloadUrl")

    model_config = ConfigDict(populate_by_name=True)


class ProfileFileMetadataUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    category: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=40)
    issuer: str | None = Field(default=None, max_length=240)
    notes: str | None = Field(default=None, max_length=2_000)

    model_config = ConfigDict(extra="forbid")


class ProfileFileImportRequest(BaseModel):
    profile_file_id: str | None = Field(
        default=None,
        alias="profileFileId",
        min_length=1,
        max_length=36,
    )
    # Transitional request-only compatibility. These bytes are decoded in
    # memory and are never written into ProfileRecord/ProfileVersionRecord.
    resume_file_name: str = Field(default="", alias="resumeFileName", max_length=240)
    resume_data_url: str = Field(
        default="",
        alias="resumeDataUrl",
        max_length=20_000_000,
        repr=False,
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def require_exactly_one_source(self) -> "ProfileFileImportRequest":
        has_profile_file = bool(self.profile_file_id)
        has_legacy_file = bool(self.resume_file_name and self.resume_data_url)
        if has_profile_file == has_legacy_file:
            raise ValueError(
                "Provide either profile_file_id or resume_file_name with resume_data_url"
            )
        if bool(self.resume_file_name) != bool(self.resume_data_url):
            raise ValueError("resume_file_name and resume_data_url must be provided together")
        return self


# Backwards-compatible import name for existing internal callers.
ResumeExperienceImportRequest = ProfileFileImportRequest


class ImportedExperienceEntry(BaseModel):
    title: str = Field(default="", max_length=180)
    company: str = Field(default="", max_length=180)
    employment_type: str = Field(default="Full-time", max_length=80)
    location: str = Field(default="", max_length=180)
    start_date: str = Field(default="", max_length=20)
    end_date: str = Field(default="", max_length=20)
    is_current: bool = False
    description: str = Field(default="", max_length=2000)


class ResumeExperienceImportResponse(BaseModel):
    experience: list[ImportedExperienceEntry]
    message: str = ""


class ImportedEducationEntry(BaseModel):
    institution: str = Field(default="", max_length=180)
    credential: str = Field(default="", max_length=180)
    field_of_study: str = Field(default="", max_length=180)
    location: str = Field(default="", max_length=180)
    start_date: str = Field(default="", max_length=20)
    end_date: str = Field(default="", max_length=20)
    is_current: bool = False
    description: str = Field(default="", max_length=2000)


class ResumeEducationImportResponse(BaseModel):
    education: list[ImportedEducationEntry]
    message: str = ""


class ResumeSkillsImportResponse(BaseModel):
    skills: list[str]
    message: str = ""
