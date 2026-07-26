from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, OwnerScoped


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentRecord(OwnerScoped, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )
    versions: Mapped[list["DocumentVersionRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersionRecord.version",
    )
    attachments: Mapped[list["DocumentAttachmentRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    generation_provenance: Mapped["DocumentGenerationProvenanceRecord | None"] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
    )
    version_generation_provenance: Mapped[
        list["DocumentVersionGenerationProvenanceRecord"]
    ] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersionGenerationProvenanceRecord.version",
    )
    version_validations: Mapped[list["DocumentVersionValidationRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersionValidationRecord.version",
    )
    files: Mapped[list["DocumentFileRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentFileRecord.version",
    )


class DocumentVersionRecord(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document: Mapped[DocumentRecord] = relationship(back_populates="versions")


class DocumentAttachmentRecord(Base):
    __tablename__ = "document_attachments"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "application_id",
            name="uq_document_attachments_application",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document: Mapped[DocumentRecord] = relationship(back_populates="attachments")


class DocumentGenerationProvenanceRecord(Base):
    __tablename__ = "document_generation_provenance"

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    generation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generation_model: Mapped[str] = mapped_column(String(160), nullable=False)
    generation_backend: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openclaw_codex"
    )
    input_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document: Mapped[DocumentRecord] = relationship(back_populates="generation_provenance")


class DocumentVersionGenerationProvenanceRecord(Base):
    __tablename__ = "document_version_generation_provenance"

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generation_model: Mapped[str] = mapped_column(String(160), nullable=False)
    generation_backend: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openclaw_codex"
    )
    input_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document: Mapped[DocumentRecord] = relationship(
        back_populates="version_generation_provenance"
    )


class DocumentVersionValidationRecord(Base):
    __tablename__ = "document_version_validations"

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    factual_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    visual_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    diff_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document: Mapped[DocumentRecord] = relationship(back_populates="version_validations")


class DocumentPackJobRecord(OwnerScoped, Base):
    __tablename__ = "document_pack_jobs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    application_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("stored_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persistence_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class DocumentValidationArtifactRecord(OwnerScoped, Base):
    __tablename__ = "document_validation_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("stored_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    template_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_artifact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("document_generation_artifacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    template_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DocumentGenerationArtifactRecord(OwnerScoped, Base):
    __tablename__ = "document_generation_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("stored_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    template_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    generation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    generation_backend: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openclaw_codex"
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(DocumentGenerationArtifactRecord, "before_update")
def prevent_generation_artifact_input_mutation(
    _mapper: Any,
    _connection: Any,
    artifact: DocumentGenerationArtifactRecord,
) -> None:
    immutable_fields = (
        "owner_id",
        "application_id",
        "job_id",
        "document_type",
        "template_id",
        "template_content",
        "input_snapshot",
        "generation_fingerprint",
        "generation_backend",
        "input_versions",
        "validation_evidence",
        "expires_at",
        "created_at",
    )
    state = inspect(artifact)
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("Generation artifact input snapshot is immutable")


class DocumentTemplateRecord(OwnerScoped, Base):
    __tablename__ = "document_templates"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "type",
            "content_sha256",
            name="uq_document_templates_owner_type_content_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )
    files: Mapped[list["DocumentFileRecord"]] = relationship(
        back_populates="template",
    )


class WorkspaceSourceDocumentRecord(OwnerScoped, Base):
    __tablename__ = "workspace_source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("stored_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )


class DocumentFileRecord(Base):
    __tablename__ = "document_files"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_files_version"),
        UniqueConstraint(
            "source_ats_final_review_id",
            "renderer_template_id",
            "renderer_template_version",
            "renderer_design_sha256",
            name="uq_document_files_resume_pdf_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("document_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(
        String(240),
        nullable=False,
        default="",
    )
    content_type: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        default=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )
    renderer_template_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    renderer_template_version: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    renderer_design_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_ats_final_review_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "ats_final_reviews.id",
            ondelete="SET NULL",
            name="fk_document_files_ats_final_review",
        ),
        nullable=True,
        index=True,
    )
    final_resume_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    stage_results: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    provenance: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document: Mapped[DocumentRecord] = relationship(back_populates="files")
    template: Mapped[DocumentTemplateRecord | None] = relationship(back_populates="files")


DocumentType = Literal["cover_letter", "tailored_resume"]
DocumentPackPersistenceMode = Literal["atomic", "partial"]
WorkspaceSourceCategory = Literal["CV / Resume", "Cover Letter"]


class DocumentArtifactPayload(BaseModel):
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    template_id: str | None = Field(default=None, alias="templateId")
    template_version: str | None = Field(default=None, alias="templateVersion")
    design_sha256: str | None = Field(default=None, alias="designSha256")
    source_ats_final_review_id: str | None = Field(
        default=None,
        alias="sourceAtsFinalReviewId",
    )
    final_resume_json: dict[str, Any] | None = Field(
        default=None,
        alias="finalResumeJson",
    )
    stage_results: dict[str, Any] | None = Field(
        default=None,
        alias="stageResults",
    )
    provenance: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class DocumentVersionPayload(BaseModel):
    id: str
    version: int
    content: str
    created_at: datetime = Field(alias="createdAt")
    has_rendered_docx: bool = Field(default=False, alias="hasRenderedDocx")
    has_rendered_artifact: bool = Field(
        default=False,
        alias="hasRenderedArtifact",
    )
    artifact: DocumentArtifactPayload | None = None
    factual_validation: dict[str, Any] = Field(
        default_factory=dict,
        alias="factualValidation",
    )
    visual_validation: dict[str, Any] = Field(
        default_factory=dict,
        alias="visualValidation",
    )
    diff: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class DocumentPayload(BaseModel):
    id: str
    type: DocumentType
    title: str
    job_id: str | None = Field(default=None, alias="jobId")
    application_ids: list[str] = Field(default_factory=list, alias="applicationIds")
    current_version: int = Field(alias="currentVersion")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    generation_fingerprint: str | None = Field(default=None, alias="generationFingerprint")
    current_generation_fingerprint: str | None = Field(
        default=None,
        alias="currentGenerationFingerprint",
    )
    generation_model: str | None = Field(default=None, alias="generationModel")
    generation_backend: str | None = Field(default=None, alias="generationBackend")
    input_versions: dict[str, Any] = Field(default_factory=dict, alias="inputVersions")
    versions: list[DocumentVersionPayload]
    versions_total: int = Field(alias="versionsTotal")
    versions_has_more: bool = Field(alias="versionsHasMore")

    model_config = {"populate_by_name": True}


class DocumentVersionPagePayload(BaseModel):
    items: list[DocumentVersionPayload]
    total: int
    limit: int
    offset: int

    model_config = {"populate_by_name": True}


class DocumentCreateRequest(BaseModel):
    type: DocumentType
    title: str = Field(min_length=1, max_length=240)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    job_id: str | None = Field(default=None, max_length=160, alias="jobId")
    application_id: str | None = Field(default=None, max_length=160, alias="applicationId")
    template_id: str | None = Field(default=None, max_length=36, alias="templateId")
    generation_artifact_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="generationArtifactId",
    )
    model_config = {"populate_by_name": True, "extra": "forbid"}


class DocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    job_id: str | None = Field(default=None, max_length=160, alias="jobId")
    application_id: str | None = Field(default=None, max_length=160, alias="applicationId")
    template_id: str | None = Field(default=None, max_length=36, alias="templateId")
    generation_artifact_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="generationArtifactId",
    )
    model_config = {"populate_by_name": True, "extra": "forbid"}


class DocumentPackItemRequest(BaseModel):
    document_id: str | None = Field(default=None, max_length=36, alias="documentId")
    title: str = Field(min_length=1, max_length=240)
    generation_artifact_id: str = Field(
        min_length=1,
        max_length=36,
        alias="generationArtifactId",
    )
    validation_artifact_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="validationArtifactId",
    )
    model_config = {"populate_by_name": True, "extra": "forbid"}


class DocumentPackValidationRequest(BaseModel):
    application_id: str = Field(min_length=1, max_length=160, alias="applicationId")
    resume: DocumentPackItemRequest

    model_config = {"populate_by_name": True}


class DocumentPackRequest(BaseModel):
    pack_job_id: str = Field(min_length=1, max_length=80, alias="packJobId")
    job_id: str | None = Field(default=None, max_length=160, alias="jobId")
    application_id: str = Field(min_length=1, max_length=160, alias="applicationId")
    persistence_mode: DocumentPackPersistenceMode = Field(
        default="atomic",
        alias="persistenceMode",
    )
    resume: DocumentPackItemRequest
    cover_letter: DocumentPackItemRequest | None = Field(
        default=None,
        alias="coverLetter",
    )
    partial_reason: str | None = Field(default=None, max_length=500, alias="partialReason")

    model_config = {"populate_by_name": True}


class DocumentPackValidationPayload(BaseModel):
    status: Literal["passed"] = "passed"
    validation: dict[str, Any]
    validation_artifact_id: str = Field(alias="validationArtifactId")
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}


class DocumentPackStagePayload(BaseModel):
    id: Literal["resume_validation", "cover_letter_validation", "saving"]
    status: Literal["completed", "failed", "skipped"]
    message: str = ""


class DocumentPackPayload(BaseModel):
    pack_job_id: str = Field(alias="packJobId")
    status: Literal["completed", "partial"]
    persistence_mode: DocumentPackPersistenceMode = Field(alias="persistenceMode")
    documents: list[DocumentPayload]
    stages: list[DocumentPackStagePayload]
    message: str = ""
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}


class DocumentAttachRequest(BaseModel):
    application_id: str = Field(min_length=1, max_length=160, alias="applicationId")

    model_config = {"populate_by_name": True}


class DocumentRestoreRequest(BaseModel):
    version: int = Field(ge=1)


class DocumentTemplateCreateRequest(BaseModel):
    type: DocumentType
    name: str = Field(min_length=1, max_length=240)
    file_name: str = Field(min_length=1, max_length=240, alias="fileName")
    data_url: str = Field(min_length=1, max_length=15_000_000, alias="dataUrl")

    model_config = {"populate_by_name": True}


class DocumentTemplatePreflightRequest(DocumentTemplateCreateRequest):
    application_id: str | None = Field(
        default=None,
        max_length=160,
        alias="applicationId",
    )
    prompt_characters: int = Field(
        default=0,
        ge=0,
        le=12_000,
        alias="promptCharacters",
    )


class DocumentTemplatePayload(BaseModel):
    id: str
    type: DocumentType
    name: str
    file_name: str = Field(alias="fileName")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class BundledResumeTemplatePayload(BaseModel):
    id: Literal[
        "classic_single",
        "modern_single",
        "modern_two_column",
        "swiss_classic",
        "swiss_local_german",
    ]
    name: str
    description: str
    layout: Literal["single_column", "two_column"]
    columns: Literal[1, 2]


class DocumentTemplatePreflightPayload(BaseModel):
    supported: bool
    template: DocumentTemplatePayload | None = None
    editable_count: int = Field(alias="editableCount")
    immutable_count: int = Field(alias="immutableCount")
    immutable_elements: list[dict[str, str]] = Field(alias="immutableElements")
    rejected_elements: list[dict[str, str]] = Field(alias="rejectedElements")
    ai_context: dict[str, Any] | None = Field(default=None, alias="aiContext")
    warnings: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WorkspaceSourceDocumentCreateRequest(BaseModel):
    application_id: str = Field(min_length=1, max_length=160, alias="applicationId")
    category: WorkspaceSourceCategory
    title: str = Field(min_length=1, max_length=240)
    language: str = Field(default="", max_length=40)
    file_name: str = Field(min_length=1, max_length=240, alias="fileName")
    data_url: str = Field(min_length=1, max_length=15_000_000, alias="dataUrl")

    model_config = {"populate_by_name": True, "extra": "forbid"}


class WorkspaceSourceDocumentPayload(BaseModel):
    id: str
    application_id: str = Field(alias="applicationId")
    category: WorkspaceSourceCategory
    title: str
    language: str
    file_name: str = Field(alias="fileName")
    file_size: str = Field(alias="fileSize")
    file_type: str = Field(alias="fileType")
    uploaded_at: datetime = Field(alias="uploadedAt")
    data_url: str = Field(alias="dataUrl")

    model_config = {"populate_by_name": True}
