from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, OwnerScoped


def utc_now() -> datetime:
    return datetime.now(UTC)


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
    __table_args__ = (
        CheckConstraint(
            "size_bytes > 0",
            name="ck_workspace_source_documents_size_positive",
        ),
    )

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
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )


class DocumentFileRecord(Base):
    __tablename__ = "document_files"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_files_version"),)

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
        default=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
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
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document: Mapped[DocumentRecord] = relationship(back_populates="files")
    template: Mapped[DocumentTemplateRecord | None] = relationship(back_populates="files")


DocumentType = Literal["cover_letter", "tailored_resume"]
WorkspaceSourceCategory = Literal[
    "CV / Resume",
    "Cover Letter",
    "Application Attachment",
]


class DocumentArtifactPayload(BaseModel):
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    template_id: str | None = Field(default=None, alias="templateId")
    template_version: str | None = Field(default=None, alias="templateVersion")
    design_sha256: str | None = Field(default=None, alias="designSha256")

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
    model_config = {"populate_by_name": True, "extra": "forbid"}


class DocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    job_id: str | None = Field(default=None, max_length=160, alias="jobId")
    application_id: str | None = Field(default=None, max_length=160, alias="applicationId")
    template_id: str | None = Field(default=None, max_length=36, alias="templateId")
    model_config = {"populate_by_name": True, "extra": "forbid"}


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
    pass


class DocumentTemplatePayload(BaseModel):
    id: str
    type: DocumentType
    name: str
    file_name: str = Field(alias="fileName")
    built_in: bool = Field(default=False, alias="builtIn")
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
    model_config = {"populate_by_name": True}


class WorkspaceSourceDocumentPayload(BaseModel):
    id: str
    application_id: str = Field(alias="applicationId")
    category: WorkspaceSourceCategory
    title: str
    language: str
    file_name: str = Field(alias="fileName")
    file_size: str = Field(alias="fileSize")
    size_bytes: int = Field(alias="sizeBytes")
    file_type: str = Field(alias="fileType")
    content_sha256: str = Field(alias="contentSha256")
    uploaded_at: datetime = Field(alias="uploadedAt")
    download_url: str = Field(alias="downloadUrl")

    model_config = {"populate_by_name": True}
