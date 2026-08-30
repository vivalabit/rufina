from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Index, Integer, String, UniqueConstraint
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
    avatar_url: str = Field(default="/avatars/default-pug.png", max_length=1_500_000)
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
    documents: str = Field(default="", max_length=20_000_000)
    resume_file_name: str = Field(default="", max_length=240)
    resume_file_size: str = Field(default="", max_length=40)
    resume_updated_at: str = Field(default="", max_length=80)
    resume_data_url: str = Field(default="", max_length=10_000_000)


class ResumeExperienceImportRequest(BaseModel):
    resume_file_name: str = Field(max_length=240)
    resume_data_url: str = Field(max_length=10_000_000)


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
