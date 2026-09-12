import base64
import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, load_only, selectinload

from app.core.database import get_db
from app.core.identity import bind_request_identity
from app.models.applications import StoredApplicationRecord
from app.models.documents import (
    DocumentArtifactPayload,
    DocumentAttachmentRecord,
    DocumentAttachRequest,
    DocumentCreateRequest,
    DocumentFileRecord,
    DocumentPayload,
    DocumentRecord,
    DocumentRestoreRequest,
    DocumentTemplateCreateRequest,
    DocumentTemplatePayload,
    DocumentTemplatePreflightPayload,
    DocumentTemplatePreflightRequest,
    DocumentTemplateRecord,
    DocumentUpdateRequest,
    DocumentVersionPagePayload,
    DocumentVersionPayload,
    DocumentVersionRecord,
    WorkspaceSourceCategory,
    WorkspaceSourceDocumentPayload,
    WorkspaceSourceDocumentRecord,
    utc_now,
)
from app.services.cover_letter_template_preview import (
    CoverLetterTemplatePreviewError,
    render_cover_letter_template_thumbnail,
)
from app.services.cover_letter_template_registry import (
    ensure_bundled_cover_letter_template,
    is_bundled_cover_letter_template_id,
)
from app.services.document_analysis import analyze_docx_source
from app.services.document_export import build_document_from_template
from app.services.document_preflight import analyze_document_template
from app.services.document_security import DocumentSecurityError
from app.services.document_validation import (
    DocumentValidationError,
    render_docx_to_pdf,
)
from app.services.profile_files import (
    ProfileFileValidationError,
    validate_profile_file_upload,
)
from app.services.resume_template_registry import (
    is_bundled_resume_template_id,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_CONTENT_TYPE = "application/pdf"
MAX_TEMPLATE_BYTES = 10_000_000
MAX_APPLICATION_ATTACHMENT_BYTES = 5_000_000
DOCUMENT_VERSION_PAGE_SIZE = 20
APPLICATION_ATTACHMENT_EXTENSIONS = {
    "application/pdf": (".pdf",),
    "application/msword": (".doc",),
    DOCX_CONTENT_TYPE: (".docx",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/webp": (".webp",),
}


def private_workspace_file_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Cross-Origin-Resource-Policy": "same-site",
        "Vary": "X-Rufina-Owner-Id, X-Tasko-Owner-Id",
        "X-Content-Type-Options": "nosniff",
    }


@router.get("", response_model=list[DocumentPayload])
def list_documents(
    job_id: str | None = Query(default=None, alias="jobId"),
    application_id: str | None = Query(default=None, alias="applicationId"),
    db: Session = Depends(get_db),
) -> list[DocumentPayload]:
    try:
        statement = select(DocumentRecord).order_by(DocumentRecord.updated_at.desc())
        if job_id is not None:
            statement = statement.where(DocumentRecord.job_id == job_id)
        if application_id is not None:
            statement = statement.join(DocumentAttachmentRecord).where(
                DocumentAttachmentRecord.application_id == application_id
            )
        records = db.scalars(statement).unique().all()
        return initial_document_payloads(db, records)
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.post("", response_model=DocumentPayload, status_code=status.HTTP_201_CREATED)
def create_document(
    request: DocumentCreateRequest,
    db: Session = Depends(get_db),
) -> DocumentPayload:
    if request.type == "tailored_resume":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Tailored resume creation is not available",
        )
    try:
        content = request.content
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Document content is required",
            )
        now = utc_now()
        document_id = str(uuid4())
        record = DocumentRecord(
            id=document_id,
            type=request.type,
            title=request.title.strip(),
            job_id=request.job_id,
            current_version=1,
            created_at=now,
            updated_at=now,
        )
        record.versions.append(
            DocumentVersionRecord(
                id=str(uuid4()),
                document_id=document_id,
                version=1,
                content=content,
                created_at=now,
            )
        )
        db.add(record)
        db.flush()
        if request.template_id:
            template = require_template(db, request.template_id)
            if template.type != request.type:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Document template type does not match document type",
                )
            try:
                rendered_content = build_document_from_template(
                    template_content=template.content,
                    content=content,
                    document_type=request.type,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            db.add(
                DocumentFileRecord(
                    id=str(uuid4()),
                    document_id=document_id,
                    version=1,
                    template_id=template.id,
                    content=rendered_content,
                    created_at=now,
                )
            )
        if request.application_id:
            attach_document_record(db, record, request.application_id)
        db.commit()
        return document_payload(require_document(db, document_id))
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.get("/{document_id}", response_model=DocumentPayload)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentPayload:
    try:
        record = require_document(db, document_id)
        return document_payload(record, version_limit=DOCUMENT_VERSION_PAGE_SIZE)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.get("/{document_id}/versions", response_model=DocumentVersionPagePayload)
def list_document_versions(
    document_id: str,
    limit: int = Query(default=DOCUMENT_VERSION_PAGE_SIZE, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DocumentVersionPagePayload:
    try:
        record = db.get(DocumentRecord, document_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )
        total = (
            db.scalar(
                select(func.count())
                .select_from(DocumentVersionRecord)
                .where(DocumentVersionRecord.document_id == document_id)
            )
            or 0
        )
        versions = list(
            reversed(
                db.scalars(
                    select(DocumentVersionRecord)
                    .where(DocumentVersionRecord.document_id == document_id)
                    .order_by(DocumentVersionRecord.version.desc())
                    .offset(offset)
                    .limit(limit)
                ).all()
            )
        )
        version_numbers = [version.version for version in versions]
        artifacts = (
            db.scalars(
                select(DocumentFileRecord)
                .options(
                    load_only(
                        DocumentFileRecord.id,
                        DocumentFileRecord.document_id,
                        DocumentFileRecord.version,
                        DocumentFileRecord.template_id,
                        DocumentFileRecord.file_name,
                        DocumentFileRecord.content_type,
                        DocumentFileRecord.renderer_template_id,
                        DocumentFileRecord.renderer_template_version,
                        DocumentFileRecord.renderer_design_sha256,
                    )
                )
                .where(
                    DocumentFileRecord.document_id == document_id,
                    DocumentFileRecord.version.in_(version_numbers),
                )
            ).all()
            if version_numbers
            else []
        )
        artifacts_by_version = {artifact.version: artifact for artifact in artifacts}
        return DocumentVersionPagePayload(
            items=document_version_payloads(
                versions,
                rendered_versions=set(artifacts_by_version),
                artifacts_by_version=artifacts_by_version,
                artifact_title=record.title,
            ),
            total=total,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.patch("/{document_id}", response_model=DocumentPayload)
def update_document(
    document_id: str,
    request: DocumentUpdateRequest,
    db: Session = Depends(get_db),
) -> DocumentPayload:
    try:
        record = require_document(db, document_id)
        if record.type == "tailored_resume":
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="Saved tailored resume artifacts are read-only",
            )
        fields = request.model_fields_set
        if request.application_id:
            require_document_application_ownership(record, request.application_id)
        if "template_id" in fields and ("content" not in fields or request.content is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Document template requires document content",
            )
        if "title" in fields and request.title is not None:
            record.title = request.title.strip()
        if "job_id" in fields:
            record.job_id = request.job_id
        if "content" in fields and request.content is not None:
            current = current_version_record(record)
            if current.content != request.content or "template_id" in fields:
                now = utc_now()
                next_version = record.current_version + 1
                record.versions.append(
                    DocumentVersionRecord(
                        id=str(uuid4()),
                        document_id=record.id,
                        version=next_version,
                        content=request.content,
                        created_at=now,
                    )
                )
                current_file = document_file_record(db, record.id, record.current_version)
                if "template_id" in fields:
                    template_id = request.template_id
                else:
                    template_id = current_file.template_id if current_file else None
                if template_id:
                    template = require_template(db, template_id)
                    if template.type != record.type:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Document template type does not match document type",
                        )
                    try:
                        rendered_content = build_document_from_template(
                            template_content=template.content,
                            content=request.content,
                            document_type=record.type,
                        )
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc),
                        ) from exc
                    db.add(
                        DocumentFileRecord(
                            id=str(uuid4()),
                            document_id=record.id,
                            version=next_version,
                            template_id=template.id,
                            content=rendered_content,
                            created_at=now,
                        )
                    )
                record.current_version = next_version
        record.updated_at = utc_now()
        db.commit()
        updated = require_document(db, document_id)
        return document_payload(updated)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.post("/{document_id}/restore", response_model=DocumentPayload)
def restore_document_version(
    document_id: str,
    request: DocumentRestoreRequest,
    db: Session = Depends(get_db),
) -> DocumentPayload:
    try:
        record = require_document(db, document_id)
        if record.type == "tailored_resume":
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail=("Saved tailored resume artifacts are read-only"),
            )
        source = next(
            (version for version in record.versions if version.version == request.version),
            None,
        )
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document version not found",
            )
        now = utc_now()
        next_version = record.current_version + 1
        record.versions.append(
            DocumentVersionRecord(
                id=str(uuid4()),
                document_id=record.id,
                version=next_version,
                content=source.content,
                created_at=now,
            )
        )
        source_file = document_file_record(db, record.id, source.version)
        if source_file:
            db.add(
                DocumentFileRecord(
                    id=str(uuid4()),
                    document_id=record.id,
                    version=next_version,
                    template_id=source_file.template_id,
                    file_name=source_file.file_name,
                    content_type=source_file.content_type,
                    renderer_template_id=source_file.renderer_template_id,
                    renderer_template_version=(source_file.renderer_template_version),
                    renderer_design_sha256=source_file.renderer_design_sha256,
                    content=source_file.content,
                    created_at=now,
                )
            )
        record.current_version = next_version
        record.updated_at = now
        db.commit()
        restored = require_document(db, document_id)
        return document_payload(restored)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.post("/{document_id}/attachments", response_model=DocumentPayload)
def attach_document(
    document_id: str,
    request: DocumentAttachRequest,
    db: Session = Depends(get_db),
) -> DocumentPayload:
    try:
        record = require_document(db, document_id)
        attach_document_record(db, record, request.application_id)
        record.updated_at = utc_now()
        db.commit()
        attached = require_document(db, document_id)
        return document_payload(attached)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.delete(
    "/{document_id}/attachments/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def detach_document(
    document_id: str,
    application_id: str,
    db: Session = Depends(get_db),
) -> None:
    try:
        record = require_document(db, document_id)
        attachment = next(
            (item for item in record.attachments if item.application_id == application_id),
            None,
        )
        if not attachment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document attachment not found",
            )
        db.delete(attachment)
        record.updated_at = utc_now()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    version: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> Response:
    try:
        record = require_document(db, document_id)
        selected_version = (
            next((item for item in record.versions if item.version == version), None)
            if version is not None
            else current_version_record(record)
        )
        if not selected_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document version not found",
            )
        rendered_file = document_file_record(db, record.id, selected_version.version)
        if not rendered_file:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Rendered document artifact is no longer available for recovery",
            )
        content_type = rendered_file.content_type or DOCX_CONTENT_TYPE
        extension = ".pdf" if content_type == PDF_CONTENT_TYPE else ".docx"
        filename = rendered_file.file_name.strip() or (
            f"{safe_filename(record.title)}-v{selected_version.version}{extension}"
        )
        return Response(
            content=rendered_file.content,
            media_type=content_type,
            headers={"Content-Disposition": content_disposition(filename)},
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.get("/{document_id}/pdf")
def download_document_pdf(
    document_id: str,
    version: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> Response:
    try:
        record = require_document(db, document_id)
        selected_version = (
            next((item for item in record.versions if item.version == version), None)
            if version is not None
            else current_version_record(record)
        )
        if not selected_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document version not found",
            )
        rendered_file = document_file_record(db, record.id, selected_version.version)
        if not rendered_file:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Rendered document artifact is no longer available for recovery",
            )
        content_type = rendered_file.content_type or DOCX_CONTENT_TYPE
        if content_type == PDF_CONTENT_TYPE:
            pdf_content = rendered_file.content
        elif content_type == DOCX_CONTENT_TYPE:
            try:
                pdf_content = render_docx_to_pdf(rendered_file.content)
            except DocumentValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(exc),
                ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only DOCX and PDF document artifacts support PDF download",
            )
        source_filename = rendered_file.file_name.strip() or (
            f"{safe_filename(record.title)}-v{selected_version.version}.docx"
        )
        pdf_filename = (
            f"{source_filename[:-5]}.pdf"
            if source_filename.lower().endswith(".docx")
            else (
                source_filename
                if source_filename.lower().endswith(".pdf")
                else f"{source_filename}.pdf"
            )
        )
        return Response(
            content=pdf_content,
            media_type=PDF_CONTENT_TYPE,
            headers={"Content-Disposition": content_disposition(pdf_filename)},
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.get("/templates/library", response_model=list[DocumentTemplatePayload])
def list_document_templates(db: Session = Depends(get_db)) -> list[DocumentTemplatePayload]:
    try:
        bundled_template = ensure_bundled_cover_letter_template(db)
        records = db.scalars(
            select(DocumentTemplateRecord)
            .where(DocumentTemplateRecord.type == "cover_letter")
            .order_by(DocumentTemplateRecord.updated_at.desc())
        ).all()
        ordered_records = [
            bundled_template,
            *(record for record in records if record.id != bundled_template.id),
        ]
        return [document_template_payload(record) for record in ordered_records]
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.get("/templates/{template_id}/thumbnail")
def download_document_template_thumbnail(
    template_id: str,
    db: Session = Depends(get_db),
) -> Response:
    try:
        template = require_template(db, template_id)
        if template.type != "cover_letter":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only cover-letter templates support document thumbnails",
            )
        try:
            thumbnail = render_cover_letter_template_thumbnail(template.content)
        except CoverLetterTemplatePreviewError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        return Response(
            content=thumbnail,
            media_type="image/png",
            headers={
                "Cache-Control": "private, max-age=300",
                "Content-Disposition": ('inline; filename="cover-letter-template-thumbnail.png"'),
                "Vary": "X-Rufina-Owner-Id, X-Tasko-Owner-Id",
                "X-Rufina-Template-Id": template.id,
            },
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.post(
    "/templates/preflight",
    response_model=DocumentTemplatePreflightPayload,
)
def preflight_document_template(
    request: DocumentTemplatePreflightRequest,
) -> DocumentTemplatePreflightPayload:
    if request.type == "tailored_resume":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Custom resume DOCX templates are not supported; choose "
                "classic_single, modern_single, modern_two_column, swiss_classic, "
                "or swiss_local_german"
            ),
        )
    if not request.file_name.lower().endswith(".docx"):
        return DocumentTemplatePreflightPayload(
            supported=False,
            editable_count=0,
            immutable_count=0,
            immutable_elements=[],
            rejected_elements=[
                {
                    "element": "fileType",
                    "description": "template must be a .docx file",
                }
            ],
        )
    _, content = decode_data_url(request.data_url)
    if not content or len(content) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Template must be a non-empty DOCX file under 10 MB",
        )

    report = analyze_document_template(content, request.type)
    if not report["supported"]:
        return DocumentTemplatePreflightPayload(
            supported=False,
            editable_count=report["editableCount"],
            immutable_count=report["immutableCount"],
            immutable_elements=report["immutableElements"],
            rejected_elements=report["rejectedElements"],
        )

    return DocumentTemplatePreflightPayload(
        supported=True,
        template=None,
        editable_count=report["editableCount"],
        immutable_count=report["immutableCount"],
        immutable_elements=report["immutableElements"],
        rejected_elements=report["rejectedElements"],
    )


@router.get(
    "/workspace-sources/library",
    response_model=list[WorkspaceSourceDocumentPayload],
)
def list_workspace_source_documents(
    response: Response,
    application_id: str = Query(min_length=1, max_length=160, alias="applicationId"),
    db: Session = Depends(get_db),
) -> list[WorkspaceSourceDocumentPayload]:
    try:
        require_stored_application(db, application_id)
        records = db.scalars(
            select(WorkspaceSourceDocumentRecord)
            .options(
                load_only(
                    WorkspaceSourceDocumentRecord.id,
                    WorkspaceSourceDocumentRecord.application_id,
                    WorkspaceSourceDocumentRecord.category,
                    WorkspaceSourceDocumentRecord.title,
                    WorkspaceSourceDocumentRecord.language,
                    WorkspaceSourceDocumentRecord.file_name,
                    WorkspaceSourceDocumentRecord.content_type,
                    WorkspaceSourceDocumentRecord.size_bytes,
                    WorkspaceSourceDocumentRecord.content_sha256,
                    WorkspaceSourceDocumentRecord.updated_at,
                )
            )
            .where(WorkspaceSourceDocumentRecord.application_id == application_id)
            .order_by(WorkspaceSourceDocumentRecord.updated_at.desc())
        ).all()
        response.headers.update(private_workspace_file_headers())
        return [workspace_source_document_payload(record) for record in records]
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.post(
    "/workspace-sources/upload",
    response_model=WorkspaceSourceDocumentPayload,
    status_code=status.HTTP_201_CREATED,
)
async def upload_workspace_source_document(
    request: Request,
    response: Response,
    application_id: str = Query(min_length=1, max_length=160, alias="applicationId"),
    category: WorkspaceSourceCategory = Query(),
    title: str = Query(min_length=1, max_length=240),
    file_name: str = Query(min_length=1, max_length=240, alias="fileName"),
    language: str = Query(default="", max_length=40),
    content_type_header: str | None = Header(default=None, alias="Content-Type"),
    db: Session = Depends(get_db),
) -> WorkspaceSourceDocumentPayload:
    if category == "CV / Resume":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Application-level CV sources were removed; import and confirm "
                "one canonical Master Resume in My Profile"
            ),
        )
    normalized_title = title.strip()
    if not normalized_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workspace source title must not be blank",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length must be an integer",
            ) from exc
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length must not be negative",
            )
        if parsed_length > MAX_APPLICATION_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Application file must be no larger than 5 MB",
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_APPLICATION_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Application file must be no larger than 5 MB",
            )
        body.extend(chunk)
    content = bytes(body)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Application file must not be empty",
        )

    content_type = workspace_source_content_type(
        category=category,
        file_name=file_name,
        content_type_header=content_type_header,
    )
    safe_file_name = safe_upload_filename(file_name)
    if category == "Application Attachment":
        try:
            safe_file_name, content_type = validate_profile_file_upload(
                kind="supporting_document",
                file_name=file_name,
                content_type=content_type,
                content=content,
            )
        except ProfileFileValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
    if category == "Cover Letter":
        try:
            analyze_docx_source(content, "cover_letter")
        except DocumentSecurityError as exc:
            raise HTTPException(
                status_code=(
                    status.HTTP_413_CONTENT_TOO_LARGE
                    if exc.limit_exceeded
                    else status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=str(exc),
            ) from exc

    content_sha256 = hashlib.sha256(content).hexdigest()
    try:
        require_stored_application(db, application_id)
        now = utc_now()
        record = WorkspaceSourceDocumentRecord(
            id=str(uuid4()),
            application_id=application_id,
            category=category,
            title=normalized_title,
            language=language.strip(),
            file_name=safe_file_name,
            content_type=content_type,
            size_bytes=len(content),
            content_sha256=content_sha256,
            content=content,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.headers.update(private_workspace_file_headers())
        return workspace_source_document_payload(record)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application file already exists",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.get("/workspace-sources/{source_id}/download")
def download_workspace_source_document(
    source_id: str,
    application_id: str = Query(min_length=1, max_length=160, alias="applicationId"),
    db: Session = Depends(get_db),
) -> Response:
    try:
        record = db.scalar(
            select(WorkspaceSourceDocumentRecord).where(
                WorkspaceSourceDocumentRecord.id == source_id,
                WorkspaceSourceDocumentRecord.application_id == application_id,
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace source not found",
            )
        return Response(
            content=record.content,
            media_type=record.content_type,
            headers={
                **private_workspace_file_headers(),
                "Content-Disposition": content_disposition(record.file_name),
                "Content-Length": str(record.size_bytes),
            },
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.delete(
    "/workspace-sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workspace_source_document(
    source_id: str,
    application_id: str = Query(min_length=1, max_length=160, alias="applicationId"),
    db: Session = Depends(get_db),
) -> None:
    try:
        record = db.scalar(
            select(WorkspaceSourceDocumentRecord).where(
                WorkspaceSourceDocumentRecord.id == source_id,
                WorkspaceSourceDocumentRecord.application_id == application_id,
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace source not found",
            )
        db.delete(record)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.post(
    "/templates",
    response_model=DocumentTemplatePayload,
    status_code=status.HTTP_201_CREATED,
)
def create_document_template(
    request: DocumentTemplateCreateRequest,
    db: Session = Depends(get_db),
) -> DocumentTemplatePayload:
    if request.type == "tailored_resume":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Custom resume DOCX templates are not supported; choose "
                "classic_single, modern_single, modern_two_column, swiss_classic, "
                "or swiss_local_german"
            ),
        )
    if not request.file_name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Template must be a .docx file",
        )
    content_type, content = decode_data_url(request.data_url)
    if not content or len(content) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Template must be a non-empty DOCX file under 10 MB",
        )
    try:
        analysis = analyze_docx_source(content, request.type)
    except DocumentSecurityError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_413_CONTENT_TOO_LARGE
                if exc.limit_exceeded
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc

    content_sha256 = analysis.content_sha256
    try:
        duplicate = db.scalar(
            select(DocumentTemplateRecord).where(
                DocumentTemplateRecord.type == request.type,
                DocumentTemplateRecord.content_sha256 == content_sha256,
            )
        )
        if duplicate is not None:
            return document_template_payload(duplicate)
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc

    extracted_text = analysis.extracted_text
    now = utc_now()
    record = DocumentTemplateRecord(
        id=str(uuid4()),
        type=request.type,
        name=request.name.strip(),
        file_name=safe_upload_filename(request.file_name),
        content_type=content_type or DOCX_CONTENT_TYPE,
        content_sha256=content_sha256,
        content=content,
        extracted_text=extracted_text,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
        return document_template_payload(record)
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(DocumentTemplateRecord).where(
                DocumentTemplateRecord.type == request.type,
                DocumentTemplateRecord.content_sha256 == content_sha256,
            )
        )
        if duplicate is not None:
            return document_template_payload(duplicate)
        raise database_unavailable(exc) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_template(template_id: str, db: Session = Depends(get_db)) -> None:
    if is_bundled_resume_template_id(template_id) or is_bundled_cover_letter_template_id(
        template_id
    ):
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail="Bundled document templates cannot be deleted",
        )
    try:
        template = require_template(db, template_id)
        if template.type == "tailored_resume":
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="Bundled resume templates cannot be deleted",
            )
        db.delete(template)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> None:
    try:
        record = require_document(db, document_id)
        if record.type == "tailored_resume":
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail=(
                    "Resume artifacts are immutable and retained read-only; "
                    "historical DOCX files remain available for download"
                ),
            )
        db.delete(record)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


def require_document(db: Session, document_id: str) -> DocumentRecord:
    record = db.scalar(
        select(DocumentRecord)
        .where(DocumentRecord.id == document_id)
        .options(
            selectinload(DocumentRecord.versions),
            selectinload(DocumentRecord.attachments),
            selectinload(DocumentRecord.files),
        )
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return record


def require_template(db: Session, template_id: str) -> DocumentTemplateRecord:
    if is_bundled_resume_template_id(template_id):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Bundled resume templates render FinalResume JSON to PDF only",
        )
    record = db.get(DocumentTemplateRecord, template_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document template not found",
        )
    return record


def require_document_application_ownership(
    record: DocumentRecord,
    application_id: str,
) -> None:
    if any(attachment.application_id == application_id for attachment in record.attachments):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Existing document is not attached to the application",
    )


def document_file_record(
    db: Session,
    document_id: str,
    version: int,
) -> DocumentFileRecord | None:
    return db.scalar(
        select(DocumentFileRecord).where(
            DocumentFileRecord.document_id == document_id,
            DocumentFileRecord.version == version,
        )
    )


def attach_document_record(
    db: Session,
    document: DocumentRecord,
    application_id: str,
) -> None:
    if not db.get(StoredApplicationRecord, application_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    if any(item.application_id == application_id for item in document.attachments):
        return
    document.attachments.append(
        DocumentAttachmentRecord(
            id=str(uuid4()),
            document_id=document.id,
            application_id=application_id,
            created_at=utc_now(),
        )
    )


def require_stored_application(db: Session, application_id: str) -> StoredApplicationRecord:
    application = db.get(StoredApplicationRecord, application_id)
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    return application


def current_version_record(record: DocumentRecord) -> DocumentVersionRecord:
    current = next(
        (version for version in record.versions if version.version == record.current_version),
        None,
    )
    if not current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document has no current version",
        )
    return current


@dataclass(frozen=True)
class DocumentPayloadRelations:
    versions: tuple[DocumentVersionRecord, ...]
    versions_total: int
    application_ids: tuple[str, ...]
    rendered_versions: frozenset[int]
    artifacts_by_version: Mapping[int, DocumentFileRecord]


def initial_document_payloads(
    db: Session,
    records: list[DocumentRecord],
) -> list[DocumentPayload]:
    relations_by_document = load_initial_document_relations(db, records)
    return [
        document_payload(
            record,
            relations=relations_by_document[record.id],
        )
        for record in records
    ]


def load_initial_document_relations(
    db: Session,
    records: list[DocumentRecord],
) -> dict[str, DocumentPayloadRelations]:
    document_ids = [record.id for record in records]
    if not document_ids:
        return {}

    version_counts = dict(
        db.execute(
            select(
                DocumentVersionRecord.document_id,
                func.count(DocumentVersionRecord.id),
            )
            .where(DocumentVersionRecord.document_id.in_(document_ids))
            .group_by(DocumentVersionRecord.document_id)
        ).all()
    )
    ranked_version_ids = (
        select(
            DocumentVersionRecord.id.label("version_id"),
            DocumentVersionRecord.document_id.label("document_id"),
            DocumentVersionRecord.version.label("version"),
            func.row_number()
            .over(
                partition_by=DocumentVersionRecord.document_id,
                order_by=DocumentVersionRecord.version.desc(),
            )
            .label("page_row"),
        )
        .where(DocumentVersionRecord.document_id.in_(document_ids))
        .subquery()
    )
    versions = db.scalars(
        select(DocumentVersionRecord)
        .join(
            ranked_version_ids,
            ranked_version_ids.c.version_id == DocumentVersionRecord.id,
        )
        .where(ranked_version_ids.c.page_row <= DOCUMENT_VERSION_PAGE_SIZE)
        .order_by(DocumentVersionRecord.document_id, DocumentVersionRecord.version)
    ).all()
    versions_by_document: dict[str, list[DocumentVersionRecord]] = defaultdict(list)
    for version in versions:
        versions_by_document[version.document_id].append(version)

    rendered_versions_by_document: dict[str, set[int]] = defaultdict(set)
    artifacts_by_document: dict[
        str,
        dict[int, DocumentFileRecord],
    ] = defaultdict(dict)
    if versions:
        file_rows = db.scalars(
            select(DocumentFileRecord)
            .options(
                load_only(
                    DocumentFileRecord.id,
                    DocumentFileRecord.document_id,
                    DocumentFileRecord.version,
                    DocumentFileRecord.template_id,
                    DocumentFileRecord.file_name,
                    DocumentFileRecord.content_type,
                    DocumentFileRecord.renderer_template_id,
                    DocumentFileRecord.renderer_template_version,
                    DocumentFileRecord.renderer_design_sha256,
                )
            )
            .join(
                ranked_version_ids,
                (ranked_version_ids.c.document_id == DocumentFileRecord.document_id)
                & (ranked_version_ids.c.version == DocumentFileRecord.version),
            )
            .where(ranked_version_ids.c.page_row <= DOCUMENT_VERSION_PAGE_SIZE)
        ).all()
        for artifact in file_rows:
            rendered_versions_by_document[artifact.document_id].add(artifact.version)
            artifacts_by_document[artifact.document_id][artifact.version] = artifact

    application_ids_by_document: dict[str, list[str]] = defaultdict(list)
    for document_id, application_id in db.execute(
        select(
            DocumentAttachmentRecord.document_id,
            DocumentAttachmentRecord.application_id,
        ).where(DocumentAttachmentRecord.document_id.in_(document_ids))
    ).all():
        application_ids_by_document[document_id].append(application_id)

    return {
        record.id: DocumentPayloadRelations(
            versions=tuple(versions_by_document[record.id]),
            versions_total=int(version_counts.get(record.id, 0)),
            application_ids=tuple(application_ids_by_document[record.id]),
            rendered_versions=frozenset(rendered_versions_by_document[record.id]),
            artifacts_by_version=artifacts_by_document[record.id],
        )
        for record in records
    }


def document_payload(
    record: DocumentRecord,
    *,
    version_limit: int | None = None,
    version_offset: int = 0,
    relations: DocumentPayloadRelations | None = None,
) -> DocumentPayload:
    if relations is None:
        rendered_versions = {file.version for file in record.files}
        artifacts_by_version = {file.version: file for file in record.files}
        source_versions = record.versions
        versions_total = len(record.versions)
        application_ids = [item.application_id for item in record.attachments]
    else:
        rendered_versions = set(relations.rendered_versions)
        artifacts_by_version = dict(relations.artifacts_by_version)
        source_versions = relations.versions
        versions_total = relations.versions_total
        application_ids = list(relations.application_ids)
    ordered_versions = sorted(
        source_versions,
        key=lambda version: version.version,
        reverse=True,
    )
    paged_versions = ordered_versions[version_offset:]
    if version_limit is not None:
        paged_versions = paged_versions[:version_limit]
    paged_versions = list(reversed(paged_versions))
    return DocumentPayload(
        id=record.id,
        type=record.type,
        title=record.title,
        job_id=record.job_id,
        application_ids=application_ids,
        current_version=record.current_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        versions=document_version_payloads(
            paged_versions,
            rendered_versions=rendered_versions,
            artifacts_by_version=artifacts_by_version,
            artifact_title=record.title,
        ),
        versions_total=versions_total,
        versions_has_more=version_offset + len(paged_versions) < versions_total,
    )


def document_version_payloads(
    versions: list[DocumentVersionRecord],
    *,
    rendered_versions: set[int],
    artifacts_by_version: dict[int, DocumentFileRecord],
    artifact_title: str,
) -> list[DocumentVersionPayload]:
    return [
        DocumentVersionPayload(
            id=version.id,
            version=version.version,
            content=version.content,
            created_at=version.created_at,
            has_rendered_docx=(
                version.version in artifacts_by_version
                and (
                    not artifacts_by_version[version.version].content_type
                    or artifacts_by_version[version.version].content_type == DOCX_CONTENT_TYPE
                )
            ),
            has_rendered_artifact=version.version in rendered_versions,
            artifact=(
                document_artifact_payload(
                    artifacts_by_version[version.version],
                    artifact_title=artifact_title,
                )
                if version.version in artifacts_by_version
                else None
            ),
        )
        for version in versions
    ]


def document_artifact_payload(
    artifact: DocumentFileRecord,
    *,
    artifact_title: str,
) -> DocumentArtifactPayload:
    content_type = artifact.content_type or DOCX_CONTENT_TYPE
    extension = ".pdf" if content_type == PDF_CONTENT_TYPE else ".docx"
    return DocumentArtifactPayload(
        file_name=artifact.file_name.strip()
        or (f"{safe_filename(artifact_title)}-v{artifact.version}{extension}"),
        content_type=content_type,
        template_id=artifact.renderer_template_id or artifact.template_id,
        template_version=artifact.renderer_template_version,
        design_sha256=artifact.renderer_design_sha256,
    )


def safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.strip())
    normalized = re.sub(r"[^\w.\-]+", "-", normalized, flags=re.UNICODE).strip("-._")
    return normalized[:120] or "rufina-document"


def safe_upload_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.strip())
    normalized = re.sub(r"[^\w.\- ]+", "-", normalized, flags=re.UNICODE)
    return normalized[:240].rstrip(" .") or "template.docx"


def workspace_source_content_type(
    *,
    category: WorkspaceSourceCategory,
    file_name: str,
    content_type_header: str | None,
) -> str:
    normalized_file_name = file_name.strip().casefold()
    normalized_content_type = (content_type_header or "").partition(";")[0].strip().lower()
    unspecified_content_types = {"", "application/octet-stream"}

    if category == "Cover Letter":
        if not normalized_file_name.endswith(".docx"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cover Letter source must be a .docx file",
            )
        if normalized_content_type not in unspecified_content_types | {DOCX_CONTENT_TYPE}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cover Letter Content-Type must identify a DOCX file",
            )
        return DOCX_CONTENT_TYPE

    if category != "Application Attachment":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported workspace source category",
        )

    if normalized_content_type in unspecified_content_types:
        for candidate, extensions in APPLICATION_ATTACHMENT_EXTENSIONS.items():
            if normalized_file_name.endswith(extensions):
                return candidate
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=("Application Attachment must be PDF, DOC, DOCX, PNG, JPEG, or WebP"),
        )

    expected_extensions = APPLICATION_ATTACHMENT_EXTENSIONS.get(normalized_content_type)
    if expected_extensions is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=("Application Attachment must be PDF, DOC, DOCX, PNG, JPEG, or WebP"),
        )
    if not normalized_file_name.endswith(expected_extensions):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Application Attachment file extension does not match Content-Type",
        )
    return normalized_content_type


def content_disposition(filename: str) -> str:
    ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-._")
    ascii_filename = re.sub(r"-+", "-", ascii_filename)
    ascii_filename = ascii_filename or "rufina-document.docx"
    return f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename, safe='')}"


def decode_data_url(value: str) -> tuple[str, bytes]:
    header, separator, payload = value.partition(",")
    if not separator:
        return "", b""
    content_type = header.removeprefix("data:").split(";")[0]
    try:
        if ";base64" in header:
            return content_type, base64.b64decode(payload, validate=True)
        return content_type, payload.encode()
    except (ValueError, TypeError):
        return content_type, b""


def document_template_payload(record: DocumentTemplateRecord) -> DocumentTemplatePayload:
    return DocumentTemplatePayload(
        id=record.id,
        type=record.type,
        name=record.name,
        file_name=record.file_name,
        built_in=is_bundled_cover_letter_template_id(record.id),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def workspace_source_document_payload(
    record: WorkspaceSourceDocumentRecord,
) -> WorkspaceSourceDocumentPayload:
    return WorkspaceSourceDocumentPayload(
        id=record.id,
        application_id=record.application_id,
        category=record.category,
        title=record.title,
        language=record.language,
        file_name=record.file_name,
        file_size=f"{max(1, round(record.size_bytes / 1024))} KB",
        size_bytes=record.size_bytes,
        file_type=record.content_type,
        content_sha256=record.content_sha256,
        uploaded_at=record.updated_at,
        download_url=(
            f"/documents/workspace-sources/{quote(record.id, safe='')}/download"
            f"?applicationId={quote(record.application_id, safe='')}"
        ),
    )


def database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Documents database is unavailable",
    )
