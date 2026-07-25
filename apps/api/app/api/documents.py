import base64
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, load_only, selectinload

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.database import get_db
from app.core.identity import bind_request_identity
from app.core.settings import Settings, get_settings
from app.models.applications import StoredApplicationRecord
from app.models.assistant import (
    AssistantApplicationContext,
    AssistantCandidateConfirmation,
    AssistantJobContext,
    AssistantSourceDocument,
)
from app.models.documents import (
    BundledResumeTemplatePayload,
    DocumentArtifactPayload,
    DocumentAttachRequest,
    DocumentAttachmentRecord,
    DocumentCreateRequest,
    DocumentFileRecord,
    DocumentGenerationArtifactRecord,
    DocumentGenerationProvenanceRecord,
    DocumentPackPayload,
    DocumentPackRequest,
    DocumentPackValidationRequest,
    DocumentPackValidationPayload,
    DocumentPayload,
    DocumentRecord,
    DocumentRestoreRequest,
    DocumentTemplateCreateRequest,
    DocumentTemplatePayload,
    DocumentTemplatePreflightPayload,
    DocumentTemplatePreflightRequest,
    DocumentTemplateRecord,
    DocumentUpdateRequest,
    DocumentVersionGenerationProvenanceRecord,
    DocumentVersionPagePayload,
    DocumentVersionPayload,
    DocumentVersionRecord,
    DocumentVersionValidationRecord,
    WorkspaceSourceDocumentCreateRequest,
    WorkspaceSourceDocumentPayload,
    WorkspaceSourceDocumentRecord,
    utc_now,
)
from app.models.profile import ProfilePayload
from app.services.assistant import (
    analyze_openclaw_assistant_context,
    build_source_document_context,
)
from app.services.document_analysis import analyze_docx_source
from app.services.document_export import build_document_from_template
from app.services.generation_context import (
    AuthoritativeApplicationGenerationContext,
    AuthoritativeGenerationContext,
    GenerationContextError,
    load_authoritative_application_generation_context,
    load_authoritative_generation_context,
)
from app.services.document_security import DocumentSecurityError
from app.services.document_validation import (
    DocumentValidationError,
    validate_generated_document,
)
from app.services.document_preflight import analyze_document_template
from app.services.resume_template_registry import (
    is_bundled_resume_template_id,
    list_bundled_resume_templates,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_CONTENT_TYPE = "application/pdf"
MAX_TEMPLATE_BYTES = 10_000_000
DOCUMENT_VERSION_PAGE_SIZE = 20


@router.get("", response_model=list[DocumentPayload])
def list_documents(
    job_id: str | None = Query(default=None, alias="jobId"),
    application_id: str | None = Query(default=None, alias="applicationId"),
    db: Session = Depends(get_db),
) -> list[DocumentPayload]:
    try:
        statement = (
            select(DocumentRecord)
            .order_by(DocumentRecord.updated_at.desc())
        )
        if job_id is not None:
            statement = statement.where(DocumentRecord.job_id == job_id)
        if application_id is not None:
            statement = statement.join(DocumentAttachmentRecord).where(
                DocumentAttachmentRecord.application_id == application_id
            )
        records = db.scalars(statement).unique().all()
        return initial_document_payloads(
            db,
            records,
            application_id=application_id,
        )
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
            detail=(
                "Legacy DOCX resume creation was removed; run the three-stage "
                "resume-tailoring pipeline and render finalResume as PDF"
            ),
        )
    try:
        generation_artifact = (
            require_generation_artifact(
                db,
                document_type=request.type,
                artifact_id=request.generation_artifact_id,
                application_id=request.application_id,
                expected_job_id=request.job_id,
            )
            if request.generation_artifact_id
            else None
        )
        if generation_artifact and (request.content is not None or request.template_id is not None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Generated documents accept generationArtifactId instead of client content or template",
            )
        content = generation_artifact.result_content if generation_artifact else request.content
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Document content or generationArtifactId is required",
            )
        application_id = (
            generation_artifact.application_id if generation_artifact else request.application_id
        )
        job_id = generation_artifact.job_id if generation_artifact else request.job_id
        template_id = generation_artifact.template_id if generation_artifact else request.template_id
        now = utc_now()
        document_id = str(uuid4())
        record = DocumentRecord(
            id=document_id,
            type=request.type,
            title=request.title.strip(),
            job_id=job_id,
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
        if generation_artifact:
            assert generation_artifact.generation_model is not None
            set_current_generation_provenance(
                record,
                generation_artifact.generation_fingerprint,
                generation_artifact.generation_model,
                generation_artifact.input_versions,
                now,
            )
            append_version_generation_provenance(
                record,
                1,
                generation_artifact.generation_fingerprint,
                generation_artifact.generation_model,
                generation_artifact.input_versions,
                now,
            )
        db.add(record)
        db.flush()
        if template_id:
            template = require_template(db, template_id)
            if template.type != request.type:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Document template type does not match document type",
                )
            try:
                rendered_content = build_document_from_template(
                    template_content=(
                        generation_artifact.template_content
                        if generation_artifact
                        else template.content
                    ),
                    content=content,
                    document_type=request.type,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            if generation_artifact and request.type != "cover_letter":
                validation = validate_document_or_422(
                    template_content=generation_artifact.template_content,
                    rendered_content=rendered_content,
                    generated_content=content,
                    document_type=request.type,
                    evidence=generation_artifact.validation_evidence,
                )
                append_document_validation(record, 1, validation, now)
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
        if application_id:
            attach_document_record(db, record, application_id)
        if generation_artifact:
            generation_artifact.consumed_at = now
        db.commit()
        return document_payload(
            require_document(db, document_id),
            current_generation_fingerprint=(
                generation_artifact.generation_fingerprint
                if generation_artifact
                else None
            ),
        )
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.post(
    "/packs/validate-resume",
    response_model=DocumentPackValidationPayload,
)
def validate_resume_pack_item(
    _request: DocumentPackValidationRequest,
) -> DocumentPackValidationPayload:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Legacy DOCX resume pack validation was removed; use the validated "
            "PDF artifact returned by resume tailoring"
        ),
    )


@router.post(
    "/packs",
    response_model=DocumentPackPayload,
    status_code=status.HTTP_201_CREATED,
)
def create_document_pack(
    _request: DocumentPackRequest,
) -> DocumentPackPayload:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Legacy DOCX application packs were removed; save the tailored PDF "
            "artifact and cover letter independently"
        ),
    )


@router.get(
    "/packs/{pack_job_id}",
    response_model=DocumentPackPayload,
)
def get_document_pack_status(
    pack_job_id: str,
    application_id: str = Query(min_length=1, max_length=160, alias="applicationId"),
) -> DocumentPackPayload:
    del pack_job_id, application_id
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Legacy DOCX application packs were removed",
    )


@router.get(
    "/resume-templates",
    response_model=list[BundledResumeTemplatePayload],
)
def list_resume_templates() -> list[BundledResumeTemplatePayload]:
    return [
        BundledResumeTemplatePayload(
            id=template.id,
            name=template.name,
            description=template.description,
            layout=template.layout,
            columns=template.columns,
        )
        for template in list_bundled_resume_templates()
    ]


@router.get("/{document_id}", response_model=DocumentPayload)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentPayload:
    try:
        record = require_document(db, document_id)
        return document_payload(
            record,
            current_generation_fingerprint=(
                authoritative_current_generation_fingerprint(db, record)
            ),
            version_limit=DOCUMENT_VERSION_PAGE_SIZE,
        )
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
        total = db.scalar(
            select(func.count()).select_from(DocumentVersionRecord).where(
                DocumentVersionRecord.document_id == document_id
            )
        ) or 0
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
                        DocumentFileRecord.source_ats_final_review_id,
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
        artifacts_by_version = {
            artifact.version: artifact for artifact in artifacts
        }
        validations = (
            db.scalars(
                select(DocumentVersionValidationRecord).where(
                    DocumentVersionValidationRecord.document_id == document_id,
                    DocumentVersionValidationRecord.version.in_(version_numbers),
                )
            ).all()
            if version_numbers
            else []
        )
        return DocumentVersionPagePayload(
            items=document_version_payloads(
                versions,
                rendered_versions=set(artifacts_by_version),
                artifacts_by_version=artifacts_by_version,
                include_artifact_details=False,
                artifact_title=record.title,
                validations_by_version={
                    validation.version: validation for validation in validations
                },
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
                detail=(
                    "Tailored resume artifacts are immutable; generate a new "
                    "three-stage PDF instead"
                ),
            )
        fields = request.model_fields_set
        generation_artifact = (
            require_generation_artifact(
                db,
                artifact_id=request.generation_artifact_id,
                document_type=record.type,
                application_id=request.application_id,
                expected_job_id=request.job_id,
            )
            if request.generation_artifact_id
            else None
        )
        has_provenance = generation_artifact is not None
        if generation_artifact and ({"content", "template_id", "job_id"} & fields):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Generated documents accept generationArtifactId instead of client content, template, or job",
            )
        if generation_artifact:
            require_document_application_ownership(
                record,
                generation_artifact.application_id,
            )
        if request.application_id:
            require_document_application_ownership(record, request.application_id)
        if "template_id" in fields and (
            "content" not in fields or request.content is None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Document template requires document content",
            )
        if "title" in fields and request.title is not None:
            record.title = request.title.strip()
        if "job_id" in fields:
            record.job_id = request.job_id
        generated_content = (
            generation_artifact.result_content if generation_artifact else request.content
        )
        if ("content" in fields or generation_artifact) and generated_content is not None:
            current = current_version_record(record)
            if current.content != generated_content or has_provenance or "template_id" in fields:
                now = utc_now()
                current_provenance = record.generation_provenance
                if current_provenance and not any(
                    provenance.version == record.current_version
                    for provenance in record.version_generation_provenance
                ):
                    append_version_generation_provenance(
                        record,
                        record.current_version,
                        current_provenance.generation_fingerprint,
                        current_provenance.generation_model,
                        current_provenance.input_versions,
                        now,
                    )
                next_version = record.current_version + 1
                record.versions.append(
                    DocumentVersionRecord(
                        id=str(uuid4()),
                        document_id=record.id,
                        version=next_version,
                        content=generated_content,
                        created_at=now,
                    )
                )
                current_file = document_file_record(db, record.id, record.current_version)
                if generation_artifact:
                    template_id = generation_artifact.template_id
                elif "template_id" in fields:
                    template_id = request.template_id
                else:
                    template_id = current_file.template_id if current_file else None
                if has_provenance and not template_id:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="Document template is required for generated documents",
                    )
                if template_id:
                    template = require_template(db, template_id)
                    if template.type != record.type:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Document template type does not match document type",
                        )
                    try:
                        rendered_content = build_document_from_template(
                            template_content=(
                                generation_artifact.template_content
                                if generation_artifact
                                else template.content
                            ),
                            content=generated_content,
                            document_type=record.type,
                        )
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc),
                        ) from exc
                    if has_provenance and record.type != "cover_letter":
                        assert generation_artifact is not None
                        validation = validate_document_or_422(
                            template_content=generation_artifact.template_content,
                            rendered_content=rendered_content,
                            generated_content=generated_content,
                            document_type=record.type,
                            evidence=generation_artifact.validation_evidence,
                        )
                        append_document_validation(
                            record,
                            next_version,
                            validation,
                            now,
                        )
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
                    if generation_artifact:
                        record.job_id = generation_artifact.job_id
                        attach_document_record(db, record, generation_artifact.application_id)
                if has_provenance:
                    assert generation_artifact is not None
                    assert generation_artifact.generation_model is not None
                    set_current_generation_provenance(
                        record,
                        generation_artifact.generation_fingerprint,
                        generation_artifact.generation_model,
                        generation_artifact.input_versions,
                        now,
                    )
                else:
                    record.generation_provenance = None
                current_provenance = record.generation_provenance
                if current_provenance:
                    append_version_generation_provenance(
                        record,
                        next_version,
                        current_provenance.generation_fingerprint,
                        current_provenance.generation_model,
                        current_provenance.input_versions,
                        now,
                    )
                record.current_version = next_version
                if generation_artifact:
                    generation_artifact.consumed_at = now
        record.updated_at = utc_now()
        db.commit()
        updated = require_document(db, document_id)
        return document_payload(
            updated,
            current_generation_fingerprint=authoritative_current_generation_fingerprint(
                db,
                updated,
                application_id=(
                    generation_artifact.application_id
                    if generation_artifact
                    else request.application_id
                ),
            ),
        )
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
                detail=(
                    "Tailored resume artifacts are read-only; generate a new "
                    "three-stage PDF instead of restoring a version"
                ),
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
                    renderer_template_version=(
                        source_file.renderer_template_version
                    ),
                    final_resume_json=source_file.final_resume_json,
                    stage_results=source_file.stage_results,
                    provenance=source_file.provenance,
                    content=source_file.content,
                    created_at=now,
                )
            )
        source_provenance = next(
            (
                provenance
                for provenance in record.version_generation_provenance
                if provenance.version == source.version
            ),
            None,
        )
        if source_provenance:
            set_current_generation_provenance(
                record,
                source_provenance.generation_fingerprint,
                source_provenance.generation_model,
                source_provenance.input_versions,
                now,
            )
            append_version_generation_provenance(
                record,
                next_version,
                source_provenance.generation_fingerprint,
                source_provenance.generation_model,
                source_provenance.input_versions,
                now,
            )
        else:
            record.generation_provenance = None
        source_validation = next(
            (
                validation
                for validation in record.version_validations
                if validation.version == source.version
            ),
            None,
        )
        if source_validation:
            append_document_validation(
                record,
                next_version,
                {
                    "factual": source_validation.factual_report,
                    "visual": source_validation.visual_report,
                    "diff": source_validation.diff_items,
                },
                now,
            )
        record.current_version = next_version
        record.updated_at = now
        db.commit()
        restored = require_document(db, document_id)
        return document_payload(
            restored,
            current_generation_fingerprint=authoritative_current_generation_fingerprint(
                db,
                restored,
            ),
        )
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
        return document_payload(
            attached,
            current_generation_fingerprint=authoritative_current_generation_fingerprint(
                db,
                attached,
                application_id=request.application_id,
            ),
        )
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
            (
                item
                for item in record.attachments
                if item.application_id == application_id
            ),
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


@router.get("/templates/library", response_model=list[DocumentTemplatePayload])
def list_document_templates(db: Session = Depends(get_db)) -> list[DocumentTemplatePayload]:
    try:
        records = db.scalars(
            select(DocumentTemplateRecord)
            .where(DocumentTemplateRecord.type == "cover_letter")
            .order_by(DocumentTemplateRecord.updated_at.desc())
        ).all()
        return [document_template_payload(record) for record in records]
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.post(
    "/templates/preflight",
    response_model=DocumentTemplatePreflightPayload,
)
def preflight_document_template(
    request: DocumentTemplatePreflightRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentTemplatePreflightPayload:
    if request.type == "tailored_resume":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Custom resume DOCX templates are not supported; choose "
                "classic_single, modern_single, or modern_two_column"
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

    ai_context = None
    warnings: list[str] = []
    if request.application_id:
        try:
            now = utc_now()
            transient_template = DocumentTemplateRecord(
                id=str(uuid4()),
                type=request.type,
                name=request.name.strip(),
                file_name=safe_upload_filename(request.file_name),
                content_type=DOCX_CONTENT_TYPE,
                content_sha256=hashlib.sha256(content).hexdigest(),
                content=content,
                extracted_text="",
                created_at=now,
                updated_at=now,
            )
            generation_context = load_authoritative_generation_context(
                db,
                application_id=request.application_id,
                template_id=transient_template.id,
                document_type=request.type,
                template_override=transient_template,
            )
            profile, job, application, source, confirmations = (
                assistant_preflight_inputs(generation_context)
            )
            ai_context = analyze_openclaw_assistant_context(
                message_characters=request.prompt_characters,
                context_kind="application",
                profile=profile,
                job=job,
                application=application,
                source_documents=[source],
                candidate_confirmations=confirmations,
                max_prompt_chars=settings.openclaw_assistant_max_prompt_chars,
            )
            source_context = dict(report["sourceContext"])
            actual_source_context = build_source_document_context([source])[0]
            source_elements = actual_source_context.get("paragraphs", [])
            actual_source_characters = len(
                json.dumps(
                    actual_source_context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            metadata_characters = max(
                0,
                actual_source_characters - source_context["includedCharacters"],
            )
            source_context["includedElements"] = len(source_elements)
            source_context["omittedElements"] = max(
                0,
                source_context["totalElements"] - len(source_elements),
            )
            source_context["includedCharacters"] = actual_source_characters
            source_context["estimatedCharacters"] += metadata_characters
            source_context["truncated"] = source_context["omittedElements"] > 0
            omitted_source_characters = max(
                0,
                source_context["estimatedCharacters"]
                - source_context["includedCharacters"],
            )
            ai_context["estimatedCharacters"] += omitted_source_characters
            ai_context["source"] = source_context
            ai_context["truncated"] = bool(
                ai_context["truncated"] or source_context["truncated"]
            )
        except GenerationContextError as exc:
            warnings.append(f"AI context could not be estimated: {exc}")

    return DocumentTemplatePreflightPayload(
        supported=True,
        template=None,
        editable_count=report["editableCount"],
        immutable_count=report["immutableCount"],
        immutable_elements=report["immutableElements"],
        rejected_elements=report["rejectedElements"],
        ai_context=ai_context,
        warnings=warnings,
    )


@router.get(
    "/workspace-sources/library",
    response_model=list[WorkspaceSourceDocumentPayload],
)
def list_workspace_source_documents(
    application_id: str = Query(min_length=1, max_length=160, alias="applicationId"),
    db: Session = Depends(get_db),
) -> list[WorkspaceSourceDocumentPayload]:
    try:
        require_stored_application(db, application_id)
        records = db.scalars(
            select(WorkspaceSourceDocumentRecord)
            .where(WorkspaceSourceDocumentRecord.application_id == application_id)
            .order_by(WorkspaceSourceDocumentRecord.updated_at.desc())
        ).all()
        return [workspace_source_document_payload(record) for record in records]
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.post(
    "/workspace-sources",
    response_model=WorkspaceSourceDocumentPayload,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_source_document(
    request: WorkspaceSourceDocumentCreateRequest,
    db: Session = Depends(get_db),
) -> WorkspaceSourceDocumentPayload:
    if request.category == "CV / Resume":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Application-level CV sources were removed; import and confirm "
                "one canonical Master Resume in My Profile"
            ),
        )
    if not request.file_name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workspace source must be a .docx file",
        )
    _, content = decode_data_url(request.data_url)
    if not content or len(content) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Workspace source must be a non-empty DOCX file under 10 MB",
        )
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

    now = utc_now()
    record = WorkspaceSourceDocumentRecord(
        id=str(uuid4()),
        application_id=request.application_id,
        category=request.category,
        title=request.title.strip(),
        language=request.language.strip(),
        file_name=safe_upload_filename(request.file_name),
        content_type=DOCX_CONTENT_TYPE,
        content=content,
        created_at=now,
        updated_at=now,
    )
    try:
        require_stored_application(db, request.application_id)
        db.add(record)
        db.commit()
        db.refresh(record)
        return workspace_source_document_payload(record)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
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
                "classic_single, modern_single, or modern_two_column"
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
    if is_bundled_resume_template_id(template_id):
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail="Bundled resume templates cannot be deleted",
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


def set_current_generation_provenance(
    record: DocumentRecord,
    generation_fingerprint: str,
    generation_model: str,
    input_versions: dict[str, object],
    created_at: datetime,
) -> None:
    provenance = record.generation_provenance
    if provenance is None:
        provenance = DocumentGenerationProvenanceRecord(document_id=record.id)
        record.generation_provenance = provenance
    provenance.generation_fingerprint = generation_fingerprint
    provenance.generation_model = generation_model.strip()
    provenance.generation_backend = generation_backend_from_input_versions(input_versions)
    provenance.input_versions = input_versions
    provenance.created_at = created_at


def append_version_generation_provenance(
    record: DocumentRecord,
    version: int,
    generation_fingerprint: str,
    generation_model: str,
    input_versions: dict[str, object],
    created_at: datetime,
) -> None:
    record.version_generation_provenance.append(
        DocumentVersionGenerationProvenanceRecord(
            document_id=record.id,
            version=version,
            generation_fingerprint=generation_fingerprint,
            generation_model=generation_model.strip(),
            generation_backend=generation_backend_from_input_versions(input_versions),
            input_versions=input_versions,
            created_at=created_at,
        )
    )


def generation_backend_from_input_versions(input_versions: dict[str, object]) -> str:
    backend = input_versions.get("backend")
    if isinstance(backend, str) and backend in {"openclaw_codex", "openai_api", "local"}:
        return backend
    generation_artifact = input_versions.get("generationArtifact")
    if isinstance(generation_artifact, dict):
        backend = generation_artifact.get("backend")
        if isinstance(backend, str) and backend in {
            "openclaw_codex",
            "openai_api",
            "local",
        }:
            return backend
    return "openclaw_codex"


def validate_document_or_422(
    *,
    template_content: bytes,
    rendered_content: bytes,
    generated_content: str,
    document_type: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    try:
        return validate_generated_document(
            template_content=template_content,
            rendered_content=rendered_content,
            generated_content=generated_content,
            document_type=document_type,
            evidence=evidence,
        )
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def append_document_validation(
    record: DocumentRecord,
    version: int,
    validation: dict[str, object],
    created_at: datetime,
) -> None:
    record.version_validations.append(
        DocumentVersionValidationRecord(
            document_id=record.id,
            version=version,
            factual_report=validation.get("factual", {}),
            visual_report=validation.get("visual", {}),
            diff_items=validation.get("diff", []),
            created_at=created_at,
        )
    )


def require_generation_artifact(
    db: Session,
    *,
    artifact_id: str,
    document_type: str,
    application_id: str | None = None,
    expected_job_id: str | None = None,
) -> DocumentGenerationArtifactRecord:
    artifact = db.scalar(
        select(DocumentGenerationArtifactRecord)
        .where(DocumentGenerationArtifactRecord.id == artifact_id)
        .with_for_update()
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation artifact was not found",
        )
    if artifact.status != "completed" or not artifact.result_content or not artifact.generation_model:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation artifact is not complete",
        )
    if artifact.consumed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation artifact has already been used",
        )
    expires_at = artifact.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=utc_now().tzinfo)
    if expires_at <= utc_now():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Generation artifact has expired",
        )
    if artifact.document_type != document_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Generation artifact document type does not match",
        )
    if application_id and artifact.application_id != application_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation artifact does not match the application",
        )
    if expected_job_id and artifact.job_id != expected_job_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation artifact does not match the vacancy",
        )
    return artifact


def require_document(db: Session, document_id: str) -> DocumentRecord:
    record = db.scalar(
        select(DocumentRecord)
        .where(DocumentRecord.id == document_id)
        .options(
            selectinload(DocumentRecord.versions),
            selectinload(DocumentRecord.attachments),
            selectinload(DocumentRecord.generation_provenance),
            selectinload(DocumentRecord.version_generation_provenance),
            selectinload(DocumentRecord.version_validations),
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


def load_generation_context_or_http(
    db: Session,
    *,
    application_id: str,
    template_id: str,
    document_type: str,
    expected_job_id: str | None = None,
) -> AuthoritativeGenerationContext:
    try:
        return load_authoritative_generation_context(
            db,
            application_id=application_id,
            template_id=template_id,
            document_type=document_type,
            expected_job_id=expected_job_id,
        )
    except GenerationContextError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def single_attachment_application_id(record: DocumentRecord) -> str | None:
    application_ids = {attachment.application_id for attachment in record.attachments}
    if len(application_ids) != 1:
        return None
    return next(iter(application_ids))


def require_document_application_ownership(
    record: DocumentRecord,
    application_id: str,
) -> None:
    if any(
        attachment.application_id == application_id for attachment in record.attachments
    ):
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
    provenance: DocumentGenerationProvenanceRecord | None
    rendered_versions: frozenset[int]
    artifacts_by_version: Mapping[int, DocumentFileRecord]
    artifact_details_loaded: bool
    validations_by_version: Mapping[int, DocumentVersionValidationRecord]
    current_template_id: str | None


def initial_document_payloads(
    db: Session,
    records: list[DocumentRecord],
    *,
    application_id: str | None = None,
) -> list[DocumentPayload]:
    relations_by_document = load_initial_document_relations(db, records)
    current_fingerprints = batch_current_generation_fingerprints(
        db,
        records,
        relations_by_document,
        application_id=application_id,
    )
    return [
        document_payload(
            record,
            relations=relations_by_document[record.id],
            current_generation_fingerprint=current_fingerprints.get(record.id),
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
    current_template_by_document: dict[str, str] = {}
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
                    DocumentFileRecord.source_ats_final_review_id,
                )
            )
            .join(
                ranked_version_ids,
                (
                    ranked_version_ids.c.document_id
                    == DocumentFileRecord.document_id
                )
                & (ranked_version_ids.c.version == DocumentFileRecord.version),
            )
            .where(ranked_version_ids.c.page_row <= DOCUMENT_VERSION_PAGE_SIZE)
        ).all()
        current_versions = {record.id: record.current_version for record in records}
        for artifact in file_rows:
            rendered_versions_by_document[artifact.document_id].add(
                artifact.version
            )
            artifacts_by_document[artifact.document_id][
                artifact.version
            ] = artifact
            if (
                artifact.version == current_versions[artifact.document_id]
                and artifact.template_id
            ):
                current_template_by_document[
                    artifact.document_id
                ] = artifact.template_id

    validations_by_document: dict[
        str,
        dict[int, DocumentVersionValidationRecord],
    ] = defaultdict(dict)
    if versions:
        validations = db.scalars(
            select(DocumentVersionValidationRecord)
            .join(
                ranked_version_ids,
                (
                    ranked_version_ids.c.document_id
                    == DocumentVersionValidationRecord.document_id
                )
                & (
                    ranked_version_ids.c.version
                    == DocumentVersionValidationRecord.version
                ),
            )
            .where(ranked_version_ids.c.page_row <= DOCUMENT_VERSION_PAGE_SIZE)
        ).all()
        for validation in validations:
            validations_by_document[validation.document_id][validation.version] = validation

    application_ids_by_document: dict[str, list[str]] = defaultdict(list)
    for document_id, application_id in db.execute(
        select(
            DocumentAttachmentRecord.document_id,
            DocumentAttachmentRecord.application_id,
        ).where(DocumentAttachmentRecord.document_id.in_(document_ids))
    ).all():
        application_ids_by_document[document_id].append(application_id)

    provenance_by_document = {
        provenance.document_id: provenance
        for provenance in db.scalars(
            select(DocumentGenerationProvenanceRecord).where(
                DocumentGenerationProvenanceRecord.document_id.in_(document_ids)
            )
        ).all()
    }
    return {
        record.id: DocumentPayloadRelations(
            versions=tuple(versions_by_document[record.id]),
            versions_total=int(version_counts.get(record.id, 0)),
            application_ids=tuple(application_ids_by_document[record.id]),
            provenance=provenance_by_document.get(record.id),
            rendered_versions=frozenset(rendered_versions_by_document[record.id]),
            artifacts_by_version=artifacts_by_document[record.id],
            artifact_details_loaded=False,
            validations_by_version=validations_by_document[record.id],
            current_template_id=current_template_by_document.get(record.id),
        )
        for record in records
    }


def batch_current_generation_fingerprints(
    db: Session,
    records: list[DocumentRecord],
    relations_by_document: Mapping[str, DocumentPayloadRelations],
    *,
    application_id: str | None,
) -> dict[str, str]:
    candidate_application_by_document: dict[str, str] = {}
    template_ids: set[str] = set()
    fingerprints: dict[str, str] = {}
    for record in records:
        relations = relations_by_document[record.id]
        if relations.provenance is None:
            continue
        current_artifact = relations.artifacts_by_version.get(
            record.current_version
        )
        if (
            current_artifact is not None
            and current_artifact.content_type == PDF_CONTENT_TYPE
            and current_artifact.renderer_template_id
        ):
            fingerprints[record.id] = (
                relations.provenance.generation_fingerprint
            )
            continue
        if not relations.current_template_id:
            continue
        resolved_application_id = application_id
        if resolved_application_id is None and len(relations.application_ids) == 1:
            resolved_application_id = relations.application_ids[0]
        if not resolved_application_id:
            continue
        candidate_application_by_document[record.id] = resolved_application_id
        template_ids.add(relations.current_template_id)

    template_metadata = {
        row.id: {
            "id": row.id,
            "type": row.type,
            "name": row.name,
            "fileName": row.file_name,
            "contentType": row.content_type,
            "updatedAt": row.updated_at,
            "contentSha256": row.content_sha256,
        }
        for row in db.execute(
            select(
                DocumentTemplateRecord.id,
                DocumentTemplateRecord.type,
                DocumentTemplateRecord.name,
                DocumentTemplateRecord.file_name,
                DocumentTemplateRecord.content_type,
                DocumentTemplateRecord.updated_at,
                DocumentTemplateRecord.content_sha256,
            ).where(DocumentTemplateRecord.id.in_(template_ids))
        ).all()
    } if template_ids else {}

    application_contexts: dict[
        str,
        AuthoritativeApplicationGenerationContext | None,
    ] = {}
    for resolved_application_id in set(candidate_application_by_document.values()):
        try:
            application_contexts[resolved_application_id] = (
                load_authoritative_application_generation_context(
                    db,
                    application_id=resolved_application_id,
                )
            )
        except GenerationContextError:
            application_contexts[resolved_application_id] = None

    for record in records:
        resolved_application_id = candidate_application_by_document.get(record.id)
        if not resolved_application_id:
            continue
        context = application_contexts.get(resolved_application_id)
        template_id = relations_by_document[record.id].current_template_id
        source_document = template_metadata.get(template_id or "")
        if (
            context is None
            or context.job_id != record.job_id
            or source_document is None
            or source_document["type"] != record.type
        ):
            continue
        fingerprints[record.id] = context.provenance_for_source_document(
            {key: value for key, value in source_document.items() if key != "type"}
        ).generation_fingerprint
    return fingerprints


def authoritative_current_generation_fingerprint(
    db: Session,
    record: DocumentRecord,
    *,
    application_id: str | None = None,
) -> str | None:
    if record.generation_provenance is None:
        return None
    current_file = document_file_record(db, record.id, record.current_version)
    if current_file is None:
        return None
    if (
        current_file.content_type == PDF_CONTENT_TYPE
        and current_file.renderer_template_id
    ):
        return record.generation_provenance.generation_fingerprint
    if not current_file.template_id:
        return None
    resolved_application_id = application_id or single_attachment_application_id(record)
    if not resolved_application_id:
        return None
    try:
        context = load_authoritative_generation_context(
            db,
            application_id=resolved_application_id,
            template_id=current_file.template_id,
            document_type=record.type,
            expected_job_id=record.job_id,
        )
    except GenerationContextError:
        return None
    return context.provenance().generation_fingerprint


def document_payload(
    record: DocumentRecord,
    *,
    current_generation_fingerprint: str | None = None,
    version_limit: int | None = None,
    version_offset: int = 0,
    relations: DocumentPayloadRelations | None = None,
) -> DocumentPayload:
    if relations is None:
        provenance = record.generation_provenance
        rendered_versions = {file.version for file in record.files}
        artifacts_by_version = {file.version: file for file in record.files}
        validations_by_version = {
            validation.version: validation for validation in record.version_validations
        }
        source_versions = record.versions
        versions_total = len(record.versions)
        application_ids = [item.application_id for item in record.attachments]
        artifact_details_loaded = True
    else:
        provenance = relations.provenance
        rendered_versions = set(relations.rendered_versions)
        artifacts_by_version = dict(relations.artifacts_by_version)
        validations_by_version = dict(relations.validations_by_version)
        source_versions = relations.versions
        versions_total = relations.versions_total
        application_ids = list(relations.application_ids)
        artifact_details_loaded = relations.artifact_details_loaded
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
        generation_fingerprint=provenance.generation_fingerprint if provenance else None,
        current_generation_fingerprint=current_generation_fingerprint,
        generation_model=provenance.generation_model if provenance else None,
        generation_backend=provenance.generation_backend if provenance else None,
        input_versions=provenance.input_versions if provenance else {},
        versions=document_version_payloads(
            paged_versions,
            rendered_versions=rendered_versions,
            artifacts_by_version=artifacts_by_version,
            include_artifact_details=artifact_details_loaded,
            artifact_title=record.title,
            validations_by_version=validations_by_version,
        ),
        versions_total=versions_total,
        versions_has_more=version_offset + len(paged_versions) < versions_total,
    )


def document_version_payloads(
    versions: list[DocumentVersionRecord],
    *,
    rendered_versions: set[int],
    artifacts_by_version: dict[int, DocumentFileRecord],
    include_artifact_details: bool,
    artifact_title: str,
    validations_by_version: dict[int, DocumentVersionValidationRecord],
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
                    or artifacts_by_version[version.version].content_type
                    == DOCX_CONTENT_TYPE
                )
            ),
            has_rendered_artifact=version.version in rendered_versions,
            artifact=(
                document_artifact_payload(
                    artifacts_by_version[version.version],
                    include_details=include_artifact_details,
                    artifact_title=artifact_title,
                )
                if version.version in artifacts_by_version
                else None
            ),
            factual_validation=(
                validations_by_version[version.version].factual_report
                if version.version in validations_by_version
                else {}
            ),
            visual_validation=(
                validations_by_version[version.version].visual_report
                if version.version in validations_by_version
                else {}
            ),
            diff=(
                validations_by_version[version.version].diff_items
                if version.version in validations_by_version
                else []
            ),
        )
        for version in versions
    ]


def document_artifact_payload(
    artifact: DocumentFileRecord,
    *,
    include_details: bool,
    artifact_title: str,
) -> DocumentArtifactPayload:
    content_type = artifact.content_type or DOCX_CONTENT_TYPE
    extension = ".pdf" if content_type == PDF_CONTENT_TYPE else ".docx"
    return DocumentArtifactPayload(
        file_name=artifact.file_name.strip()
        or (
            f"{safe_filename(artifact_title)}-v"
            f"{artifact.version}{extension}"
        ),
        content_type=content_type,
        template_id=artifact.renderer_template_id or artifact.template_id,
        template_version=artifact.renderer_template_version,
        source_ats_final_review_id=artifact.source_ats_final_review_id,
        final_resume_json=(
            artifact.final_resume_json if include_details else None
        ),
        stage_results=(
            artifact.stage_results if include_details else None
        ),
        provenance=(
            artifact.provenance if include_details else None
        ),
    )


def safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.strip())
    normalized = re.sub(r"[^\w.\-]+", "-", normalized, flags=re.UNICODE).strip("-._")
    return normalized[:120] or "rufina-document"


def safe_upload_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.strip())
    normalized = re.sub(r"[^\w.\- ]+", "-", normalized, flags=re.UNICODE)
    return normalized[:240].rstrip(" .") or "template.docx"


def content_disposition(filename: str) -> str:
    ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-._")
    ascii_filename = re.sub(r"-+", "-", ascii_filename)
    ascii_filename = ascii_filename or "rufina-document.docx"
    return (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


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
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def workspace_source_document_payload(
    record: WorkspaceSourceDocumentRecord,
) -> WorkspaceSourceDocumentPayload:
    encoded_content = base64.b64encode(record.content).decode()
    return WorkspaceSourceDocumentPayload(
        id=record.id,
        application_id=record.application_id,
        category=record.category,
        title=record.title,
        language=record.language,
        file_name=record.file_name,
        file_size=f"{max(1, round(len(record.content) / 1024))} KB",
        file_type=record.content_type,
        uploaded_at=record.updated_at,
        data_url=f"data:{record.content_type};base64,{encoded_content}",
    )


def assistant_preflight_inputs(
    context: AuthoritativeGenerationContext,
) -> tuple[
    ProfilePayload,
    AssistantJobContext,
    AssistantApplicationContext,
    AssistantSourceDocument,
    list[AssistantCandidateConfirmation],
]:
    profile = ProfilePayload.model_validate(context.profile)
    job_data = dict(context.vacancy)
    job_data["aiMatch"] = {"applicationGuide": context.application_guide}
    job = AssistantJobContext.model_validate(job_data)
    application_data = dict(context.application)
    application_data["job"] = job.model_dump(by_alias=True)
    application = AssistantApplicationContext.model_validate(application_data)
    confirmations = [
        AssistantCandidateConfirmation(
            questionId=confirmation.question_id,
            requirement=confirmation.requirement,
            question=confirmation.question,
            answer=(
                confirmation.response.upper()
                + (
                    f": {confirmation.example_text}"
                    if confirmation.example_text
                    else ""
                )
            ),
        )
        for confirmation in context.confirmations
    ]
    encoded_template = base64.b64encode(context.template.content).decode("ascii")
    source = AssistantSourceDocument(
        id=context.template.id,
        title=context.template.name,
        category="Cover Letter",
        fileName=context.template.file_name,
        dataUrl=(
            f"data:{context.template.content_type};base64,{encoded_template}"
        ),
    )
    return profile, job, application, source, confirmations


def database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Documents database is unavailable",
    )
