from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import bind_request_identity, get_bound_owner_id
from app.models.documents import DocumentFileRecord
from app.models.resume_templates import (
    ResumeTemplateDefinitionCreateRequest,
    ResumeTemplateDefinitionDuplicateRequest,
    ResumeTemplateDefinitionRecord,
    ResumeTemplateDefinitionUpdateRequest,
    ResumeTemplateDesignTokens,
    ResumeTemplatePayload,
)
from app.services.resume_template_registry import (
    ResumeTemplateId,
    get_bundled_resume_template,
    is_bundled_resume_template_id,
    list_bundled_resume_templates,
)


router = APIRouter(dependencies=[Depends(bind_request_identity)])


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
                detail=(
                    "Resume template cannot be deleted because it was used "
                    "to render a PDF"
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
            design = ResumeTemplateDesignTokens.model_validate(
                source_record.design_json
            )
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
        bundled_template_payload(template.id)
        for template in list_bundled_resume_templates()
    ]
    custom_records = db.scalars(
        select(ResumeTemplateDefinitionRecord)
        .where(
            ResumeTemplateDefinitionRecord.owner_id == get_bound_owner_id()
        )
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


def default_bundled_design_tokens(
    template_id: ResumeTemplateId,
) -> ResumeTemplateDesignTokens:
    defaults: dict[ResumeTemplateId, dict[str, object]] = {
        "classic_single": {
            "accentColor": "#2B2B2B",
            "fontFamily": "Georgia",
            "fontScale": 1.0,
            "density": "standard",
            "pageMargins": {"top": 15, "right": 15, "bottom": 15, "left": 15},
            "headingStyle": "underlined",
            "skillsStyle": "inline",
            "sidebarWidth": 0,
            "sidebarSections": [],
        },
        "modern_single": {
            "accentColor": "#176B87",
            "fontFamily": "Inter",
            "fontScale": 1.0,
            "density": "standard",
            "pageMargins": {"top": 14, "right": 14, "bottom": 14, "left": 14},
            "headingStyle": "accent-rule",
            "skillsStyle": "pills",
            "sidebarWidth": 0,
            "sidebarSections": [],
        },
        "modern_two_column": {
            "accentColor": "#243B53",
            "fontFamily": "Inter",
            "fontScale": 1.0,
            "density": "compact",
            "pageMargins": {"top": 12, "right": 12, "bottom": 12, "left": 12},
            "headingStyle": "accent-rule",
            "skillsStyle": "pills",
            "sidebarWidth": 32,
            "sidebarSections": ["skills", "languages", "certifications"],
        },
    }
    return ResumeTemplateDesignTokens.model_validate(defaults[template_id])


def database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Resume template storage is temporarily unavailable",
    )


__all__ = ["list_resume_template_payloads", "router"]
