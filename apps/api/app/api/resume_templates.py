from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import bind_request_identity, get_bound_owner_id
from app.core.settings import Settings, get_settings
from app.models.documents import DocumentFileRecord
from app.models.resume_templates import (
    ResumeTemplateDefinitionCreateRequest,
    ResumeTemplateDefinitionDuplicateRequest,
    ResumeTemplateDefinitionRecord,
    ResumeTemplateDefinitionUpdateRequest,
    ResumeTemplateBackupPayload,
    ResumeTemplateDesignTokens,
    ResumeTemplatePayload,
    ResumeTemplatePreviewRequest,
)
from app.services.resume_pdf_renderer import (
    ResolvedResumeTemplate,
    ResumePdfRenderError,
    ResumeTemplateNotFoundError,
    default_bundled_design_tokens,
    resolve_draft_resume_template,
    resolve_resume_template,
)
from app.services.resume_template_preview import (
    PreviewRateLimitExceeded,
    preview_rate_limiter,
    render_resume_template_preview,
)
from app.services.resume_template_registry import (
    ResumeTemplateId,
    get_bundled_resume_template,
    is_bundled_resume_template_id,
    list_bundled_resume_templates,
)


router = APIRouter(dependencies=[Depends(bind_request_identity)])


async def enforce_preview_limits(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            ) from exc
        if declared_size < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            )
        if declared_size > settings.resume_template_preview_max_payload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    "Resume template preview payload exceeds "
                    f"{settings.resume_template_preview_max_payload_bytes} bytes"
                ),
            )
    body = await request.body()
    if len(body) > settings.resume_template_preview_max_payload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "Resume template preview payload exceeds "
                f"{settings.resume_template_preview_max_payload_bytes} bytes"
            ),
        )
    try:
        preview_rate_limiter.consume(
            get_bound_owner_id(),
            limit=settings.resume_template_preview_rate_limit,
            window_seconds=(settings.resume_template_preview_rate_window_seconds),
        )
    except PreviewRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Resume template preview rate limit exceeded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


@router.post("/preview")
def preview_draft_resume_template(
    payload: ResumeTemplatePreviewRequest,
    _limits: None = Depends(enforce_preview_limits),
) -> Response:
    template = resolve_draft_resume_template(
        base_template_id=payload.base_template_id,
        design=payload.design_json,
    )
    return render_preview_response(template)


@router.post("/{template_id}/preview")
def preview_saved_resume_template(
    template_id: str,
    _limits: None = Depends(enforce_preview_limits),
    db: Session = Depends(get_db),
) -> Response:
    try:
        template = resolve_resume_template(db, template_id)
        return render_preview_response(template)
    except ResumeTemplateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.get("", response_model=list[ResumeTemplatePayload])
def list_resume_templates(
    db: Session = Depends(get_db),
) -> list[ResumeTemplatePayload]:
    try:
        return list_resume_template_payloads(db)
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.post(
    "",
    response_model=ResumeTemplatePayload,
    status_code=status.HTTP_201_CREATED,
)
def create_resume_template(
    request: ResumeTemplateDefinitionCreateRequest,
    db: Session = Depends(get_db),
) -> ResumeTemplatePayload:
    try:
        record = build_custom_record(
            name=request.name,
            base_template_id=request.base_template_id,
            design=request.design_json,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return custom_template_payload(record)
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.post(
    "/import",
    response_model=ResumeTemplatePayload,
    status_code=status.HTTP_201_CREATED,
)
def import_resume_template(
    backup: ResumeTemplateBackupPayload,
    db: Session = Depends(get_db),
) -> ResumeTemplatePayload:
    try:
        record = build_custom_record(
            name=backup.name,
            base_template_id=backup.base_template_id,
            design=backup.design_json,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return custom_template_payload(record)
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.get("/{template_id}/export")
def export_resume_template(
    template_id: str,
    db: Session = Depends(get_db),
) -> Response:
    reject_bundled_mutation(template_id, action="exported")
    try:
        record = require_custom_template(db, template_id)
        backup = ResumeTemplateBackupPayload(
            format="rufina.resume-template",
            schema_version=1,
            name=record.name,
            base_template_id=record.base_template_id,
            design_json=ResumeTemplateDesignTokens.model_validate(record.design_json),
        )
        return JSONResponse(
            content=backup.model_dump(mode="json", by_alias=True),
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (f'attachment; filename="{backup_file_name(record.name)}"'),
                "X-Content-Type-Options": "nosniff",
            },
        )
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.get("/{template_id}", response_model=ResumeTemplatePayload)
def get_resume_template(
    template_id: str,
    db: Session = Depends(get_db),
) -> ResumeTemplatePayload:
    if is_bundled_resume_template_id(template_id):
        return bundled_template_payload(template_id)
    try:
        return custom_template_payload(require_custom_template(db, template_id))
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.patch("/{template_id}", response_model=ResumeTemplatePayload)
def update_resume_template(
    template_id: str,
    request: ResumeTemplateDefinitionUpdateRequest,
    db: Session = Depends(get_db),
) -> ResumeTemplatePayload:
    reject_bundled_mutation(template_id, action="modified")
    try:
        record = require_custom_template(db, template_id)
        if request.name is not None:
            record.name = request.name
        if request.base_template_id is not None:
            record.base_template_id = request.base_template_id
        if request.design_json is not None:
            record.design_json = request.design_json.model_dump(mode="json")
        record.version += 1
        record.content_sha256 = definition_content_sha256(
            record.base_template_id,
            ResumeTemplateDesignTokens.model_validate(record.design_json),
        )
        record.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(record)
        return custom_template_payload(record)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume_template(
    template_id: str,
    db: Session = Depends(get_db),
) -> None:
    reject_bundled_mutation(template_id, action="deleted")
    try:
        record = require_custom_template(db, template_id)
        used_artifact_id = db.scalar(
            select(DocumentFileRecord.id)
            .where(DocumentFileRecord.renderer_template_id == record.id)
            .limit(1)
        )
        if used_artifact_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Resume template cannot be deleted because it was used to render a PDF"),
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
    "/{template_id}/duplicate",
    response_model=ResumeTemplatePayload,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_resume_template(
    template_id: str,
    request: ResumeTemplateDefinitionDuplicateRequest | None = None,
    db: Session = Depends(get_db),
) -> ResumeTemplatePayload:
    try:
        if is_bundled_resume_template_id(template_id):
            source = bundled_template_payload(template_id)
            design = default_bundled_design_tokens(source.base_template_id)
        else:
            source_record = require_custom_template(db, template_id)
            source = custom_template_payload(source_record)
            design = ResumeTemplateDesignTokens.model_validate(source_record.design_json)
        duplicate = build_custom_record(
            name=(request.name if request and request.name else f"{source.name} copy"),
            base_template_id=source.base_template_id,
            design=design,
        )
        db.add(duplicate)
        db.commit()
        db.refresh(duplicate)
        return custom_template_payload(duplicate)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


def list_resume_template_payloads(db: Session) -> list[ResumeTemplatePayload]:
    bundled = [
        bundled_template_payload(template.id) for template in list_bundled_resume_templates()
    ]
    custom_records = db.scalars(
        select(ResumeTemplateDefinitionRecord)
        .where(ResumeTemplateDefinitionRecord.owner_id == get_bound_owner_id())
        .order_by(
            ResumeTemplateDefinitionRecord.updated_at.desc(),
            ResumeTemplateDefinitionRecord.name,
        )
    ).all()
    return bundled + [custom_template_payload(record) for record in custom_records]


def require_custom_template(
    db: Session,
    template_id: str,
) -> ResumeTemplateDefinitionRecord:
    record = db.scalar(
        select(ResumeTemplateDefinitionRecord).where(
            ResumeTemplateDefinitionRecord.id == template_id,
            ResumeTemplateDefinitionRecord.owner_id == get_bound_owner_id(),
        )
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume template not found",
        )
    return record


def reject_bundled_mutation(template_id: str, *, action: str) -> None:
    if is_bundled_resume_template_id(template_id):
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail=f"Bundled resume templates cannot be {action}",
        )


def build_custom_record(
    *,
    name: str,
    base_template_id: ResumeTemplateId,
    design: ResumeTemplateDesignTokens,
) -> ResumeTemplateDefinitionRecord:
    now = datetime.now(UTC)
    return ResumeTemplateDefinitionRecord(
        id=str(uuid4()),
        owner_id=get_bound_owner_id(),
        name=name,
        base_template_id=base_template_id,
        design_json=design.model_dump(mode="json"),
        version=1,
        content_sha256=definition_content_sha256(base_template_id, design),
        created_at=now,
        updated_at=now,
    )


def definition_content_sha256(
    base_template_id: str,
    design: ResumeTemplateDesignTokens,
) -> str:
    canonical = json.dumps(
        {
            "baseTemplateId": base_template_id,
            "designJson": design.model_dump(mode="json", by_alias=True),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def backup_file_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return f"{slug or 'resume-template'}.resume-template.local.json"


def render_preview_response(template: ResolvedResumeTemplate) -> Response:
    try:
        pdf = render_resume_template_preview(template)
    except ResumePdfRenderError as exc:
        message = str(exc)
        service_failure = (
            "Chromium" in message or "Playwright" in message or "unavailable" in message
        )
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if service_failure
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=message,
        ) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": ('inline; filename="resume-template-preview.pdf"'),
            "X-Rufina-Template-Id": template.id,
            "X-Rufina-Template-Version": template.version,
            "X-Rufina-Design-Sha256": template.design_sha256,
        },
    )


def bundled_template_payload(template_id: str) -> ResumeTemplatePayload:
    template = get_bundled_resume_template(template_id)
    return ResumeTemplatePayload(
        id=template.id,
        kind="bundled",
        name=template.name,
        description=template.description,
        layout=template.layout,
        columns=template.columns,
        base_template_id=template.id,
        design_json=default_bundled_design_tokens(template.id),
    )


def custom_template_payload(
    record: ResumeTemplateDefinitionRecord,
) -> ResumeTemplatePayload:
    base = get_bundled_resume_template(record.base_template_id)
    return ResumeTemplatePayload(
        id=record.id,
        kind="custom",
        name=record.name,
        description=f"Custom design based on {base.name}.",
        layout=base.layout,
        columns=base.columns,
        base_template_id=base.id,
        design_json=ResumeTemplateDesignTokens.model_validate(record.design_json),
        version=record.version,
        content_sha256=record.content_sha256,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Resume template storage is temporarily unavailable",
    )


__all__ = ["list_resume_template_payloads", "router"]
