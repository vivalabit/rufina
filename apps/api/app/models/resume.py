from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, OwnerScoped


MAX_TEXT_LENGTH = 20_000
MAX_ITEMS_PER_SECTION = 100

CanonicalId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]
ResumeId = CanonicalId
ResumeItemId = CanonicalId
ExperienceId = CanonicalId
EvidenceId = CanonicalId
JobId = CanonicalId
StrictText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_LENGTH),
]
OptionalText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_TEXT_LENGTH),
]

ResumeSectionName = Literal[
    "summary",
    "experience",
    "skills",
    "education",
    "projects",
    "certifications",
    "languages",
    "additional",
]
MasterResumeReviewSectionName = Literal[
    "contacts",
    "summary",
    "skills",
    "experience",
    "education",
    "projects",
    "certifications",
]
MASTER_RESUME_REVIEW_SECTIONS: tuple[MasterResumeReviewSectionName, ...] = (
    "contacts",
    "summary",
    "skills",
    "experience",
    "education",
    "projects",
    "certifications",
)
EvidenceKind = Literal[
    "source",
    "profile",
    "confirmation",
    "vacancy",
    "generation",
]
EvidenceClaimType = Literal[
    "employer",
    "title",
    "period",
    "technology",
    "achievement",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class ResumeMasterRecord(OwnerScoped, Base):
    """Mutable resume identity pointing at an immutable canonical version."""

    __tablename__ = "resume_masters"
    __table_args__ = (
        CheckConstraint(
            "current_version >= 1",
            name="ck_resume_masters_current_version_positive",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
    versions: Mapped[list[ResumeMasterVersionRecord]] = relationship(
        back_populates="resume_master",
        cascade="all, delete-orphan",
        order_by="ResumeMasterVersionRecord.version",
    )
    source_files: Mapped[list[ResumeSourceFileRecord]] = relationship(
        back_populates="resume_master",
        cascade="all, delete-orphan",
        order_by="ResumeSourceFileRecord.created_at",
    )


class ResumeSourceFileRecord(OwnerScoped, Base):
    """Original PDF/DOCX retained solely as provenance for resume import."""

    __tablename__ = "resume_source_files"
    __table_args__ = (
        CheckConstraint(
            "content_type IN ("
            "'application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
            ")",
            name="ck_resume_source_files_content_type",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_resume_source_files_size_positive",
        ),
        UniqueConstraint(
            "resume_master_id",
            "content_sha256",
            name="uq_resume_source_files_master_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_master_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "resume_masters.id",
            ondelete="CASCADE",
            name="fk_resume_source_files_master",
        ),
        nullable=True,
        index=True,
    )
    draft_resume_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extraction: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    resume_master: Mapped[ResumeMasterRecord | None] = relationship(
        back_populates="source_files",
    )
    imported_versions: Mapped[list[ResumeMasterVersionRecord]] = relationship(
        back_populates="source_file",
        passive_deletes=True,
    )


class ResumeMasterVersionRecord(OwnerScoped, Base):
    """Immutable canonical snapshot produced by an import."""

    __tablename__ = "resume_master_versions"
    __table_args__ = (
        CheckConstraint(
            "version >= 1",
            name="ck_resume_master_versions_version_positive",
        ),
        UniqueConstraint(
            "resume_master_id",
            "version",
            name="uq_resume_master_versions_number",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_master_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_masters.id",
            ondelete="CASCADE",
            name="fk_resume_master_versions_master",
        ),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="1.0",
    )
    data: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "resume_source_files.id",
            ondelete="SET NULL",
            name="fk_resume_master_versions_source",
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    resume_master: Mapped[ResumeMasterRecord] = relationship(
        back_populates="versions",
    )
    source_file: Mapped[ResumeSourceFileRecord | None] = relationship(
        back_populates="imported_versions",
    )


class SeniorRecruiterAnalysisRecord(OwnerScoped, Base):
    """Immutable result of the mandatory first resume-tailoring AI stage."""

    __tablename__ = "senior_recruiter_analyses"
    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0",
            name="ck_senior_recruiter_analyses_tokens_nonnegative",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_senior_recruiter_analyses_latency_nonnegative",
        ),
        Index(
            "ix_senior_recruiter_analyses_input",
            "owner_id",
            "resume_master_version_id",
            "target_job_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_master_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_masters.id",
            ondelete="CASCADE",
            name="fk_senior_recruiter_analyses_master",
        ),
        nullable=False,
        index=True,
    )
    resume_master_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_master_versions.id",
            ondelete="CASCADE",
            name="fk_senior_recruiter_analyses_master_version",
        ),
        nullable=False,
        index=True,
    )
    target_job_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )
    vacancy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_session_id: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unavailable",
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ExperienceRewriteRecord(OwnerScoped, Base):
    """Immutable output of the mandatory XYZ experience rewrite stage."""

    __tablename__ = "experience_rewrites"
    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0",
            name="ck_experience_rewrites_tokens_nonnegative",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_experience_rewrites_latency_nonnegative",
        ),
        Index(
            "ix_experience_rewrites_input",
            "owner_id",
            "senior_recruiter_analysis_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    senior_recruiter_analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "senior_recruiter_analyses.id",
            ondelete="CASCADE",
            name="fk_experience_rewrites_recruiter_analysis",
        ),
        nullable=False,
        index=True,
    )
    resume_master_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_masters.id",
            ondelete="CASCADE",
            name="fk_experience_rewrites_master",
        ),
        nullable=False,
        index=True,
    )
    resume_master_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_master_versions.id",
            ondelete="CASCADE",
            name="fk_experience_rewrites_master_version",
        ),
        nullable=False,
        index=True,
    )
    target_job_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    original_experiences: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    links: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_session_id: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unavailable",
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AtsFinalReviewRecord(OwnerScoped, Base):
    """Immutable ATS review and the sole JSON input for final resume rendering."""

    __tablename__ = "ats_final_reviews"
    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0",
            name="ck_ats_final_reviews_tokens_nonnegative",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_ats_final_reviews_latency_nonnegative",
        ),
        Index(
            "ix_ats_final_reviews_input",
            "owner_id",
            "experience_rewrite_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experience_rewrite_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "experience_rewrites.id",
            ondelete="CASCADE",
            name="fk_ats_final_reviews_experience_rewrite",
        ),
        nullable=False,
        index=True,
    )
    resume_master_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_masters.id",
            ondelete="CASCADE",
            name="fk_ats_final_reviews_master",
        ),
        nullable=False,
        index=True,
    )
    resume_master_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_master_versions.id",
            ondelete="CASCADE",
            name="fk_ats_final_reviews_master_version",
        ),
        nullable=False,
        index=True,
    )
    target_job_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    render_input: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_session_id: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unavailable",
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ResumeTailoringRunRecord(OwnerScoped, Base):
    """Durable identity and aggregate status for one three-stage tailoring run."""

    __tablename__ = "resume_tailoring_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_resume_tailoring_runs_status",
        ),
        CheckConstraint(
            "current_stage >= 1 AND current_stage <= 3",
            name="ck_resume_tailoring_runs_current_stage",
        ),
        Index(
            "ix_resume_tailoring_runs_input",
            "owner_id",
            "resume_master_version_id",
            "target_job_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_master_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_masters.id",
            ondelete="CASCADE",
            name="fk_resume_tailoring_runs_master",
        ),
        nullable=False,
        index=True,
    )
    resume_master_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_master_versions.id",
            ondelete="CASCADE",
            name="fk_resume_tailoring_runs_master_version",
        ),
        nullable=False,
        index=True,
    )
    target_job_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ResumeTailoringStageRecord(OwnerScoped, Base):
    """One durable, independently auditable attempt of a tailoring stage."""

    __tablename__ = "resume_tailoring_stages"
    __table_args__ = (
        CheckConstraint(
            "stage_number >= 1 AND stage_number <= 3",
            name="ck_resume_tailoring_stages_number",
        ),
        CheckConstraint(
            "attempt >= 1",
            name="ck_resume_tailoring_stages_attempt",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_resume_tailoring_stages_status",
        ),
        CheckConstraint(
            "request_type IN ("
            "'senior_recruiter_analysis', "
            "'xyz_experience_rewrite', "
            "'ats_final_review'"
            ")",
            name="ck_resume_tailoring_stages_request_type",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0",
            name="ck_resume_tailoring_stages_tokens_nonnegative",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_resume_tailoring_stages_latency_nonnegative",
        ),
        UniqueConstraint(
            "run_id",
            "stage_number",
            "attempt",
            name="uq_resume_tailoring_stages_attempt",
        ),
        Index(
            "ix_resume_tailoring_stages_output",
            "owner_id",
            "output_record_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "resume_tailoring_runs.id",
            ondelete="CASCADE",
            name="fk_resume_tailoring_stages_run",
        ),
        nullable=False,
        index=True,
    )
    stage_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    structured_output: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    output_record_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unavailable",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


@event.listens_for(ResumeSourceFileRecord, "before_update")
def prevent_resume_source_file_mutation(
    _mapper: object,
    _connection: object,
    source_file: ResumeSourceFileRecord,
) -> None:
    state = inspect(source_file)
    master_history = state.attrs.resume_master_id.history
    master_association_is_confirmation = (
        master_history.has_changes()
        and tuple(master_history.deleted) == (None,)
        and len(master_history.added) == 1
        and master_history.added[0] is not None
    )
    immutable_fields = (
        "owner_id",
        "draft_resume_id",
        "file_name",
        "content_type",
        "content_sha256",
        "size_bytes",
        "content",
        "extraction",
        "created_at",
    )
    if (
        master_history.has_changes()
        and not master_association_is_confirmation
    ) or any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("Resume import source files are immutable")


@event.listens_for(ResumeMasterVersionRecord, "before_update")
def prevent_resume_master_version_mutation(
    _mapper: object,
    _connection: object,
    version: ResumeMasterVersionRecord,
) -> None:
    state = inspect(version)
    immutable_fields = (
        "owner_id",
        "resume_master_id",
        "version",
        "schema_version",
        "data",
        "content_sha256",
        "source_file_id",
        "created_at",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("Resume master versions are immutable")


@event.listens_for(SeniorRecruiterAnalysisRecord, "before_update")
def prevent_senior_recruiter_analysis_mutation(
    _mapper: object,
    _connection: object,
    analysis: SeniorRecruiterAnalysisRecord,
) -> None:
    state = inspect(analysis)
    if any(
        attribute.history.has_changes()
        for attribute in state.attrs
    ):
        raise ValueError("Senior recruiter analyses are immutable")


@event.listens_for(ExperienceRewriteRecord, "before_update")
def prevent_experience_rewrite_mutation(
    _mapper: object,
    _connection: object,
    rewrite: ExperienceRewriteRecord,
) -> None:
    state = inspect(rewrite)
    if any(attribute.history.has_changes() for attribute in state.attrs):
        raise ValueError("Experience rewrites are immutable")


@event.listens_for(AtsFinalReviewRecord, "before_update")
def prevent_ats_final_review_mutation(
    _mapper: object,
    _connection: object,
    review: AtsFinalReviewRecord,
) -> None:
    state = inspect(review)
    if any(attribute.history.has_changes() for attribute in state.attrs):
        raise ValueError("ATS final reviews are immutable")


@event.listens_for(ResumeTailoringStageRecord, "before_update")
def protect_resume_tailoring_stage_audit_input(
    _mapper: object,
    _connection: object,
    stage: ResumeTailoringStageRecord,
) -> None:
    state = inspect(stage)
    immutable_fields = (
        "owner_id",
        "run_id",
        "stage_number",
        "request_type",
        "input_fingerprint",
        "attempt",
        "started_at",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("Resume tailoring stage inputs are immutable")
    status_history = state.attrs.status.history
    previous_status = (
        status_history.deleted[0]
        if status_history.has_changes() and status_history.deleted
        else stage.status
    )
    if previous_status in {"succeeded", "failed"} and any(
        attribute.history.has_changes() for attribute in state.attrs
    ):
        raise ValueError("Completed resume tailoring stages are immutable")


@event.listens_for(ResumeTailoringRunRecord, "before_update")
def protect_resume_tailoring_run_identity(
    _mapper: object,
    _connection: object,
    run: ResumeTailoringRunRecord,
) -> None:
    state = inspect(run)
    immutable_fields = (
        "owner_id",
        "resume_master_id",
        "resume_master_version_id",
        "target_job_id",
        "created_at",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("Resume tailoring run identity is immutable")


class StrictResumeModel(BaseModel):
    """Shared contract for persisted and AI-produced resume structures."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        validate_default=True,
    )


class ResumeSourceBoundingBox(StrictResumeModel):
    """Normalized source coordinates in the range 0..1."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_coordinates(self) -> ResumeSourceBoundingBox:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("source bounding box must have positive width and height")
        return self


class ResumeSourceFragment(StrictResumeModel):
    id: ResumeItemId
    text: StrictText
    order: int = Field(ge=0)
    page_number: int | None = Field(default=None, ge=1, alias="pageNumber")
    column_index: int | None = Field(default=None, ge=0, le=1, alias="columnIndex")
    kind: Literal["paragraph", "line", "table_cell", "header", "footer"]
    extraction_method: Literal["docx", "pdf_text", "pdf_ocr"] = Field(
        alias="extractionMethod",
    )
    bbox: ResumeSourceBoundingBox | None = None


class ResumeSourceExtraction(StrictResumeModel):
    source_format: Literal["pdf", "docx"] = Field(alias="sourceFormat")
    layout: Literal["one_column", "two_column", "mixed"]
    page_count: int | None = Field(default=None, ge=1, alias="pageCount")
    used_ocr: bool = Field(default=False, alias="usedOcr")
    fragments: list[ResumeSourceFragment] = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_fragment_order(self) -> ResumeSourceExtraction:
        orders = [fragment.order for fragment in self.fragments]
        if orders != list(range(len(self.fragments))):
            raise ValueError("source fragment order must be contiguous and zero-based")
        _require_unique((fragment.id for fragment in self.fragments), "source fragment IDs")
        return self

    @property
    def text(self) -> str:
        return "\n".join(fragment.text for fragment in self.fragments)


class ResumeEvidence(StrictResumeModel):
    """An authoritative fact that may support one or more resume statements."""

    id: EvidenceId
    type: EvidenceKind
    text: StrictText
    claim_type: EvidenceClaimType | None = Field(default=None, alias="claimType")
    experience_id: ExperienceId | None = Field(default=None, alias="experienceId")
    source_id: CanonicalId | None = Field(default=None, alias="sourceId")

    @model_validator(mode="after")
    def validate_evidence_identity(self) -> ResumeEvidence:
        if not self.id.startswith(f"{self.type}:"):
            raise ValueError("evidence ID must start with its type and a colon")
        has_claim_metadata = self.claim_type is not None or self.experience_id is not None
        if has_claim_metadata and (
            self.type != "profile"
            or self.claim_type is None
            or self.experience_id is None
        ):
            raise ValueError(
                "claimType and experienceId must be provided together for profile evidence"
            )
        return self


class EvidenceBackedText(StrictResumeModel):
    text: StrictText
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> EvidenceBackedText:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class ResumeBullet(EvidenceBackedText):
    id: ResumeItemId


class ResumeBasics(StrictResumeModel):
    full_name: StrictText = Field(alias="fullName", max_length=200)
    headline: OptionalText = Field(default="", max_length=300)
    email: OptionalText = Field(default="", max_length=320)
    phone: OptionalText = Field(default="", max_length=80)
    location: OptionalText = Field(default="", max_length=240)
    linkedin: OptionalText = Field(default="", max_length=500)
    github: OptionalText = Field(default="", max_length=500)
    portfolio: OptionalText = Field(default="", max_length=500)


class MasterExperience(StrictResumeModel):
    id: ExperienceId
    company: StrictText = Field(max_length=300)
    title: StrictText = Field(max_length=300)
    employment_type: OptionalText = Field(
        default="",
        alias="employmentType",
        max_length=120,
    )
    location: OptionalText = Field(default="", max_length=240)
    start_date: OptionalText = Field(default="", alias="startDate", max_length=40)
    end_date: OptionalText = Field(default="", alias="endDate", max_length=40)
    is_current: bool = Field(default=False, alias="isCurrent")
    bullets: list[ResumeBullet] = Field(min_length=1, max_length=MAX_ITEMS_PER_SECTION)

    @model_validator(mode="after")
    def validate_experience(self) -> MasterExperience:
        if self.is_current and self.end_date:
            raise ValueError("endDate must be empty when isCurrent is true")
        _require_unique((bullet.id for bullet in self.bullets), "experience bullet IDs")
        return self


class MasterSkill(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=160)
    category: OptionalText = Field(default="", max_length=160)
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> MasterSkill:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class MasterEducation(StrictResumeModel):
    id: ResumeItemId
    institution: StrictText = Field(max_length=300)
    credential: StrictText = Field(max_length=300)
    field_of_study: OptionalText = Field(
        default="",
        alias="fieldOfStudy",
        max_length=300,
    )
    location: OptionalText = Field(default="", max_length=240)
    start_date: OptionalText = Field(default="", alias="startDate", max_length=40)
    end_date: OptionalText = Field(default="", alias="endDate", max_length=40)
    details: list[ResumeBullet] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )

    @model_validator(mode="after")
    def reject_duplicate_detail_ids(self) -> MasterEducation:
        _require_unique((detail.id for detail in self.details), "education detail IDs")
        return self


class MasterProject(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=300)
    role: OptionalText = Field(default="", max_length=300)
    url: OptionalText = Field(default="", max_length=500)
    bullets: list[ResumeBullet] = Field(min_length=1, max_length=MAX_ITEMS_PER_SECTION)

    @model_validator(mode="after")
    def reject_duplicate_bullet_ids(self) -> MasterProject:
        _require_unique((bullet.id for bullet in self.bullets), "project bullet IDs")
        return self


class MasterCertification(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=300)
    issuer: StrictText = Field(max_length=300)
    issued_on: OptionalText = Field(default="", alias="issuedOn", max_length=40)
    expires_on: OptionalText = Field(default="", alias="expiresOn", max_length=40)
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> MasterCertification:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class MasterLanguage(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=120)
    proficiency: StrictText = Field(max_length=120)
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> MasterLanguage:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class AdditionalResumeSection(StrictResumeModel):
    id: ResumeItemId
    title: StrictText = Field(max_length=200)
    items: list[ResumeBullet] = Field(min_length=1, max_length=MAX_ITEMS_PER_SECTION)

    @model_validator(mode="after")
    def reject_duplicate_item_ids(self) -> AdditionalResumeSection:
        _require_unique((item.id for item in self.items), "additional section item IDs")
        return self


class MasterResume(StrictResumeModel):
    """Canonical, vacancy-independent resume and its evidence catalog."""

    schema_version: Literal["1.0"] = Field(default="1.0", alias="schemaVersion")
    id: ResumeId
    language: StrictText = Field(max_length=40)
    basics: ResumeBasics
    summary: EvidenceBackedText | None = None
    experiences: list[MasterExperience] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    skills: list[MasterSkill] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    education: list[MasterEducation] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    projects: list[MasterProject] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    certifications: list[MasterCertification] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    languages: list[MasterLanguage] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    additional_sections: list[AdditionalResumeSection] = Field(
        default_factory=list,
        alias="additionalSections",
        max_length=MAX_ITEMS_PER_SECTION,
    )
    evidence: list[ResumeEvidence] = Field(max_length=2_000)
    section_order: list[ResumeSectionName] = Field(alias="sectionOrder", max_length=8)

    @model_validator(mode="after")
    def validate_canonical_resume(self) -> MasterResume:
        _validate_resume_graph(self)
        return self


class RewrittenExperience(StrictResumeModel):
    """One vacancy-specific rewrite linked to a canonical experience."""

    id: ResumeItemId
    master_experience_id: ExperienceId = Field(alias="masterExperienceId")
    company: StrictText = Field(max_length=300)
    title: StrictText = Field(max_length=300)
    location: OptionalText = Field(default="", max_length=240)
    period: StrictText = Field(max_length=100)
    bullets: list[ResumeBullet] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def reject_duplicate_bullet_ids(self) -> RewrittenExperience:
        _require_unique((bullet.id for bullet in self.bullets), "rewritten bullet IDs")
        return self


class ExperienceBulletRewriteLink(StrictResumeModel):
    original_bullet_ids: list[ResumeItemId] = Field(
        alias="originalBulletIds",
        min_length=1,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    rewritten_bullet_id: ResumeItemId = Field(alias="rewrittenBulletId")

    @model_validator(mode="after")
    def reject_duplicate_original_bullets(
        self,
    ) -> ExperienceBulletRewriteLink:
        _require_unique(self.original_bullet_ids, "originalBulletIds")
        return self


class ExperienceRewriteLink(StrictResumeModel):
    original_experience_id: ExperienceId = Field(alias="originalExperienceId")
    rewritten_experience_id: ResumeItemId = Field(alias="rewrittenExperienceId")
    bullet_links: list[ExperienceBulletRewriteLink] = Field(
        alias="bulletLinks",
        min_length=1,
        max_length=MAX_ITEMS_PER_SECTION,
    )

    @model_validator(mode="after")
    def validate_bullet_links(self) -> ExperienceRewriteLink:
        _require_unique(
            (link.rewritten_bullet_id for link in self.bullet_links),
            "linked rewritten bullet IDs",
        )
        _require_unique(
            (
                original_id
                for link in self.bullet_links
                for original_id in link.original_bullet_ids
            ),
            "linked original bullet IDs",
        )
        return self


class ExperienceRewrite(StrictResumeModel):
    """Complete experience-rewrite result for one target vacancy."""

    master_resume_id: ResumeId = Field(alias="masterResumeId")
    target_job_id: JobId = Field(alias="targetJobId")
    experiences: list[RewrittenExperience] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    links: list[ExperienceRewriteLink] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_SECTION,
    )

    @model_validator(mode="after")
    def validate_rewrites(self) -> ExperienceRewrite:
        _require_unique((item.id for item in self.experiences), "rewrite IDs")
        _require_unique(
            (item.master_experience_id for item in self.experiences),
            "masterExperienceIds",
        )
        _require_unique(
            (bullet.id for item in self.experiences for bullet in item.bullets),
            "rewritten bullet IDs",
        )
        _require_unique(
            (link.original_experience_id for link in self.links),
            "linked original experience IDs",
        )
        _require_unique(
            (link.rewritten_experience_id for link in self.links),
            "linked rewritten experience IDs",
        )
        if {
            link.original_experience_id for link in self.links
        } != {
            experience.master_experience_id for experience in self.experiences
        }:
            raise ValueError(
                "links must cover every masterExperienceId exactly once"
            )
        if {
            link.rewritten_experience_id for link in self.links
        } != {
            experience.id for experience in self.experiences
        }:
            raise ValueError(
                "links must cover every rewritten experience ID exactly once"
            )
        linked_bullet_ids = {
            bullet_link.rewritten_bullet_id
            for link in self.links
            for bullet_link in link.bullet_links
        }
        rewritten_bullet_ids = {
            bullet.id
            for experience in self.experiences
            for bullet in experience.bullets
        }
        if linked_bullet_ids != rewritten_bullet_ids:
            raise ValueError(
                "links must cover every rewritten bullet ID exactly once"
            )
        return self


class FinalResume(StrictResumeModel):
    """Self-contained tailored resume ready for deterministic rendering."""

    schema_version: Literal["1.0"] = Field(default="1.0", alias="schemaVersion")
    id: ResumeId
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    target_job_id: JobId = Field(alias="targetJobId")
    language: StrictText = Field(max_length=40)
    basics: ResumeBasics
    summary: EvidenceBackedText | None = None
    experiences: list[RewrittenExperience] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    skills: list[MasterSkill] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    education: list[MasterEducation] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    projects: list[MasterProject] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    certifications: list[MasterCertification] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    languages: list[MasterLanguage] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    additional_sections: list[AdditionalResumeSection] = Field(
        default_factory=list,
        alias="additionalSections",
        max_length=MAX_ITEMS_PER_SECTION,
    )
    evidence: list[ResumeEvidence] = Field(min_length=1, max_length=2_000)
    section_order: list[ResumeSectionName] = Field(
        alias="sectionOrder",
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_final_resume(self) -> FinalResume:
        _validate_resume_graph(self)
        _require_unique(
            (item.master_experience_id for item in self.experiences),
            "masterExperienceIds",
        )
        return self


class AtsSkippedSection(StrictResumeModel):
    section: ResumeSectionName
    reason: StrictText = Field(max_length=2_000)
    action: StrictText = Field(max_length=2_000)


class AtsScan(StrictResumeModel):
    skipped_sections: list[AtsSkippedSection] = Field(
        default_factory=list,
        alias="skippedSections",
        max_length=8,
    )

    @model_validator(mode="after")
    def require_unique_sections(self) -> AtsScan:
        _require_unique(
            (item.section for item in self.skipped_sections),
            "ATS skipped sections",
        )
        return self


class AtsFinalReview(StrictResumeModel):
    """Strict output of mandatory resume-tailoring request number three."""

    ats_scan: AtsScan = Field(alias="atsScan")
    final_resume: FinalResume = Field(alias="finalResume")


class SeniorRecruiterKeyword(StrictResumeModel):
    keyword: StrictText = Field(max_length=200)
    why_it_matters: StrictText = Field(alias="whyItMatters", max_length=2_000)
    evidence_status: Literal["verified", "transferable", "unsupported"] = Field(
        alias="evidenceStatus",
    )
    evidence_ids: list[EvidenceId] = Field(
        default_factory=list,
        alias="evidenceIds",
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_evidence_status(self) -> SeniorRecruiterKeyword:
        _require_unique(self.evidence_ids, "keyword evidenceIds")
        if self.evidence_status == "unsupported" and self.evidence_ids:
            raise ValueError("unsupported keywords must not cite resume evidence")
        if self.evidence_status != "unsupported" and not self.evidence_ids:
            raise ValueError(
                "verified and transferable keywords must cite resume evidence"
            )
        return self


class SeniorRecruiterRedFlag(StrictResumeModel):
    flag: StrictText = Field(max_length=500)
    why_it_is_visible: StrictText = Field(
        alias="whyItIsVisible",
        max_length=2_000,
    )
    fix: StrictText = Field(max_length=2_000)


class SeniorRecruiterAnalysis(StrictResumeModel):
    """Strict output of mandatory resume-tailoring request number one."""

    missing_keywords: list[SeniorRecruiterKeyword] = Field(
        alias="missingKeywords",
        min_length=5,
        max_length=5,
    )
    red_flags: list[SeniorRecruiterRedFlag] = Field(
        alias="redFlags",
        min_length=3,
        max_length=3,
    )

    @model_validator(mode="after")
    def require_unique_findings(self) -> SeniorRecruiterAnalysis:
        normalized_keywords = [
            item.keyword.casefold() for item in self.missing_keywords
        ]
        normalized_red_flags = [item.flag.casefold() for item in self.red_flags]
        _require_unique(normalized_keywords, "missing keywords")
        _require_unique(normalized_red_flags, "red flags")
        return self


TailoringTargetJobId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]


class SeniorRecruiterAnalysisRequest(StrictResumeModel):
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    target_job_id: TailoringTargetJobId = Field(alias="targetJobId")


class SeniorRecruiterAnalysisMetrics(StrictResumeModel):
    latency_ms: int = Field(alias="latencyMs", ge=0)
    input_tokens: int = Field(alias="inputTokens", ge=0)
    output_tokens: int = Field(alias="outputTokens", ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)
    token_count_source: StrictText = Field(
        alias="tokenCountSource",
        max_length=32,
    )


class SeniorRecruiterAnalysisResponse(StrictResumeModel):
    id: CanonicalId
    run_id: CanonicalId | None = Field(default=None, alias="runId")
    attempt: int | None = Field(default=None, ge=1)
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    master_resume_version: int = Field(alias="masterResumeVersion", ge=1)
    target_job_id: TailoringTargetJobId = Field(alias="targetJobId")
    analysis: SeniorRecruiterAnalysis
    metrics: SeniorRecruiterAnalysisMetrics
    model: StrictText = Field(max_length=160)
    backend: Literal["openclaw_codex", "openai_api"]
    prompt_version: StrictText = Field(alias="promptVersion", max_length=64)
    created_at: datetime = Field(alias="createdAt")


class ExperienceRewriteRequest(StrictResumeModel):
    senior_recruiter_analysis_id: CanonicalId = Field(
        alias="seniorRecruiterAnalysisId",
    )


class ExperienceRewriteMetrics(StrictResumeModel):
    latency_ms: int = Field(alias="latencyMs", ge=0)
    input_tokens: int = Field(alias="inputTokens", ge=0)
    output_tokens: int = Field(alias="outputTokens", ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)
    token_count_source: StrictText = Field(
        alias="tokenCountSource",
        max_length=32,
    )


class ExperienceRewriteResponse(StrictResumeModel):
    id: CanonicalId
    run_id: CanonicalId | None = Field(default=None, alias="runId")
    attempt: int | None = Field(default=None, ge=1)
    senior_recruiter_analysis_id: CanonicalId = Field(
        alias="seniorRecruiterAnalysisId",
    )
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    master_resume_version: int = Field(alias="masterResumeVersion", ge=1)
    target_job_id: TailoringTargetJobId = Field(alias="targetJobId")
    experience_rewrite: ExperienceRewrite = Field(alias="experienceRewrite")
    metrics: ExperienceRewriteMetrics
    model: StrictText = Field(max_length=160)
    backend: Literal["openclaw_codex", "openai_api"]
    prompt_version: StrictText = Field(alias="promptVersion", max_length=64)
    created_at: datetime = Field(alias="createdAt")


class AtsFinalReviewRequest(StrictResumeModel):
    experience_rewrite_id: CanonicalId = Field(alias="experienceRewriteId")


class AtsFinalReviewMetrics(StrictResumeModel):
    latency_ms: int = Field(alias="latencyMs", ge=0)
    input_tokens: int = Field(alias="inputTokens", ge=0)
    output_tokens: int = Field(alias="outputTokens", ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)
    token_count_source: StrictText = Field(
        alias="tokenCountSource",
        max_length=32,
    )


class AtsFinalReviewResponse(StrictResumeModel):
    id: CanonicalId
    run_id: CanonicalId | None = Field(default=None, alias="runId")
    attempt: int | None = Field(default=None, ge=1)
    experience_rewrite_id: CanonicalId = Field(alias="experienceRewriteId")
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    master_resume_version: int = Field(alias="masterResumeVersion", ge=1)
    target_job_id: TailoringTargetJobId = Field(alias="targetJobId")
    ats_scan: AtsScan = Field(alias="atsScan")
    final_resume: FinalResume = Field(alias="finalResume")
    metrics: AtsFinalReviewMetrics
    model: StrictText = Field(max_length=160)
    backend: Literal["openclaw_codex", "openai_api"]
    prompt_version: StrictText = Field(alias="promptVersion", max_length=64)
    created_at: datetime = Field(alias="createdAt")


class MasterResumeReviewSection(StrictResumeModel):
    name: MasterResumeReviewSectionName
    item_count: int = Field(alias="itemCount", ge=0)


class MasterResumeImportResponse(StrictResumeModel):
    source_file_id: CanonicalId = Field(alias="sourceFileId")
    master_resume: MasterResume = Field(alias="masterResume")
    source: ResumeSourceExtraction
    review_sections: list[MasterResumeReviewSection] = Field(
        alias="reviewSections",
        min_length=len(MASTER_RESUME_REVIEW_SECTIONS),
        max_length=len(MASTER_RESUME_REVIEW_SECTIONS),
    )
    model: StrictText = Field(max_length=160)
    backend: Literal["openclaw_codex", "openai_api"]

    @model_validator(mode="after")
    def validate_review_sections(self) -> MasterResumeImportResponse:
        if tuple(section.name for section in self.review_sections) != (
            MASTER_RESUME_REVIEW_SECTIONS
        ):
            raise ValueError("reviewSections must use the canonical review order")
        return self


class MasterResumeConfirmationRequest(StrictResumeModel):
    source_file_id: CanonicalId = Field(alias="sourceFileId")
    master_resume: MasterResume = Field(alias="masterResume")
    confirmed_sections: list[MasterResumeReviewSectionName] = Field(
        alias="confirmedSections",
        min_length=len(MASTER_RESUME_REVIEW_SECTIONS),
        max_length=len(MASTER_RESUME_REVIEW_SECTIONS),
    )

    @model_validator(mode="after")
    def require_all_review_sections(self) -> MasterResumeConfirmationRequest:
        if set(self.confirmed_sections) != set(MASTER_RESUME_REVIEW_SECTIONS):
            raise ValueError(
                "confirmedSections must contain every review section exactly once"
            )
        return self


class MasterResumeConfirmationResponse(StrictResumeModel):
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    version: int = Field(ge=1)
    source_file_id: CanonicalId = Field(alias="sourceFileId")
    master_resume: MasterResume = Field(alias="masterResume")
    created_at: datetime = Field(alias="createdAt")


class CurrentMasterResumeResponse(StrictResumeModel):
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    version: int = Field(ge=1)
    master_resume: MasterResume = Field(alias="masterResume")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class MasterResumeImportRequest(StrictResumeModel):
    resume_file_name: str = Field(
        alias="resumeFileName",
        min_length=1,
        max_length=240,
    )
    resume_data_url: str = Field(
        alias="resumeDataUrl",
        min_length=1,
        max_length=20_000_000,
    )


def _require_unique(values: object, label: str) -> None:
    materialized = list(values)  # type: ignore[arg-type]
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} must not contain duplicates")


def _present_sections(resume: MasterResume | FinalResume) -> set[ResumeSectionName]:
    present: set[ResumeSectionName] = set()
    if resume.summary is not None:
        present.add("summary")
    if resume.experiences:
        present.add("experience")
    if resume.skills:
        present.add("skills")
    if resume.education:
        present.add("education")
    if resume.projects:
        present.add("projects")
    if resume.certifications:
        present.add("certifications")
    if resume.languages:
        present.add("languages")
    if resume.additional_sections:
        present.add("additional")
    return present


def _all_item_ids(resume: MasterResume | FinalResume) -> list[ResumeItemId]:
    item_ids: list[ResumeItemId] = []
    for experience in resume.experiences:
        item_ids.append(experience.id)
        item_ids.extend(bullet.id for bullet in experience.bullets)
    for item in (
        *resume.skills,
        *resume.education,
        *resume.projects,
        *resume.certifications,
        *resume.languages,
        *resume.additional_sections,
    ):
        item_ids.append(item.id)
    for item in resume.education:
        item_ids.extend(detail.id for detail in item.details)
    for item in resume.projects:
        item_ids.extend(bullet.id for bullet in item.bullets)
    for section in resume.additional_sections:
        item_ids.extend(item.id for item in section.items)
    return item_ids


def _all_evidence_references(resume: MasterResume | FinalResume) -> list[EvidenceId]:
    references: list[EvidenceId] = []
    if resume.summary is not None:
        references.extend(resume.summary.evidence_ids)
    for experience in resume.experiences:
        for bullet in experience.bullets:
            references.extend(bullet.evidence_ids)
    for skill in resume.skills:
        references.extend(skill.evidence_ids)
    for item in resume.education:
        for detail in item.details:
            references.extend(detail.evidence_ids)
    for item in resume.projects:
        for bullet in item.bullets:
            references.extend(bullet.evidence_ids)
    for item in (*resume.certifications, *resume.languages):
        references.extend(item.evidence_ids)
    for section in resume.additional_sections:
        for item in section.items:
            references.extend(item.evidence_ids)
    return references


def _validate_resume_graph(resume: MasterResume | FinalResume) -> None:
    _require_unique(resume.section_order, "sectionOrder")
    expected_sections = _present_sections(resume)
    actual_sections = set(resume.section_order)
    if actual_sections != expected_sections:
        missing = sorted(expected_sections - actual_sections)
        unexpected = sorted(actual_sections - expected_sections)
        raise ValueError(
            f"sectionOrder must contain every non-empty section exactly once; "
            f"missing={missing}, unexpected={unexpected}"
        )

    _require_unique(_all_item_ids(resume), "resume item IDs")
    evidence_ids = [item.id for item in resume.evidence]
    _require_unique(evidence_ids, "evidence IDs")
    unknown_evidence_ids = sorted(set(_all_evidence_references(resume)) - set(evidence_ids))
    if unknown_evidence_ids:
        raise ValueError(
            f"resume content references unknown evidence IDs: {unknown_evidence_ids}"
        )


# Explicit domain aliases used by generation and persistence boundaries.
CanonicalMasterResume = MasterResume
TailoredResume = FinalResume
Evidence = ResumeEvidence


__all__ = [
    "AdditionalResumeSection",
    "AtsFinalReview",
    "AtsFinalReviewMetrics",
    "AtsFinalReviewRecord",
    "AtsFinalReviewRequest",
    "AtsFinalReviewResponse",
    "AtsScan",
    "AtsSkippedSection",
    "CanonicalId",
    "CanonicalMasterResume",
    "CurrentMasterResumeResponse",
    "Evidence",
    "EvidenceBackedText",
    "EvidenceClaimType",
    "EvidenceId",
    "ExperienceId",
    "ExperienceBulletRewriteLink",
    "ExperienceRewrite",
    "ExperienceRewriteLink",
    "ExperienceRewriteMetrics",
    "ExperienceRewriteRecord",
    "ExperienceRewriteRequest",
    "ExperienceRewriteResponse",
    "FinalResume",
    "JobId",
    "MasterCertification",
    "MasterEducation",
    "MasterExperience",
    "MasterLanguage",
    "MasterProject",
    "MasterResume",
    "MasterResumeConfirmationRequest",
    "MasterResumeConfirmationResponse",
    "MasterResumeImportRequest",
    "MasterResumeImportResponse",
    "MasterResumeReviewSection",
    "MasterSkill",
    "ResumeBasics",
    "ResumeBullet",
    "ResumeEvidence",
    "ResumeId",
    "ResumeItemId",
    "ResumeMasterRecord",
    "ResumeMasterVersionRecord",
    "ResumeTailoringRunRecord",
    "ResumeTailoringStageRecord",
    "ResumeSectionName",
    "ResumeSourceBoundingBox",
    "ResumeSourceExtraction",
    "ResumeSourceFragment",
    "ResumeSourceFileRecord",
    "RewrittenExperience",
    "SeniorRecruiterAnalysis",
    "SeniorRecruiterAnalysisMetrics",
    "SeniorRecruiterAnalysisRecord",
    "SeniorRecruiterAnalysisRequest",
    "SeniorRecruiterAnalysisResponse",
    "SeniorRecruiterKeyword",
    "SeniorRecruiterRedFlag",
    "StrictResumeModel",
    "TailoredResume",
]
