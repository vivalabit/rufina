"""Build the immutable, reproducible input snapshot for a generation run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.models.documents import DocumentTemplateRecord
from app.models.generation import GenerationRequest, GenerationStartRequest
from app.services.cover_letter_template_registry import (
    ensure_bundled_cover_letter_template,
)
from app.services.generation_input import build_generation_input
from app.services.generation_runtime import (
    GenerationExecutionSnapshot,
    snapshot_generation_execution,
)
from app.services.resume_pdf_renderer import resolve_resume_template


class GenerationTemplateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    document_type: str = Field(alias="documentType")
    template_id: str = Field(alias="templateId")
    template_version: str = Field(alias="templateVersion")
    content_sha256: str = Field(alias="contentSha256")
    renderer: str


class GenerationRunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    request: GenerationRequest
    execution: GenerationExecutionSnapshot
    templates: tuple[GenerationTemplateSnapshot, ...]
    created_at: datetime = Field(alias="createdAt")
    fingerprint: str


def build_generation_run_snapshot(
    db: Session,
    *,
    application_id: str,
    start: GenerationStartRequest,
    settings: Any,
    now: datetime | None = None,
) -> GenerationRunSnapshot:
    request = build_generation_input(
        db,
        application_id=application_id,
        document_types=start.document_types,
        language=start.language,
        formatting_parameters=start.formatting_parameters,
        user_preferences=start.user_preferences,
        master_profile_id=start.master_profile_id,
        master_profile_version=start.master_profile_version,
    )
    templates = resolve_template_snapshots(db, request)
    execution = snapshot_generation_execution(settings)
    created_at = now or datetime.now(UTC)
    fingerprint = _snapshot_fingerprint(
        request=request,
        execution=execution,
        templates=templates,
    )
    return GenerationRunSnapshot(
        request=request,
        execution=execution,
        templates=templates,
        created_at=created_at,
        fingerprint=fingerprint,
    )


def resolve_template_snapshots(
    db: Session,
    request: GenerationRequest,
) -> tuple[GenerationTemplateSnapshot, ...]:
    snapshots: list[GenerationTemplateSnapshot] = []
    if "tailored_resume" in request.document_types:
        parameters = request.formatting_parameters.get("tailored_resume")
        values = parameters if isinstance(parameters, dict) else {}
        template_id = str(values.get("templateId") or "classic_single")
        resolved = resolve_resume_template(db, template_id)
        snapshots.append(
            GenerationTemplateSnapshot(
                document_type="tailored_resume",
                template_id=resolved.id,
                template_version=resolved.version,
                content_sha256=resolved.design_sha256,
                renderer="lualatex",
            )
        )
    if "cover_letter" in request.document_types:
        parameters = request.formatting_parameters.get("cover_letter")
        values = parameters if isinstance(parameters, dict) else {}
        requested_id = str(values.get("templateId") or "").strip()
        template = (
            db.get(DocumentTemplateRecord, requested_id)
            if requested_id
            else ensure_bundled_cover_letter_template(db)
        )
        if template is None or template.type != "cover_letter":
            raise ValueError("Cover-letter template not found")
        snapshots.append(
            GenerationTemplateSnapshot(
                document_type="cover_letter",
                template_id=template.id,
                template_version=template.content_sha256[:12],
                content_sha256=template.content_sha256,
                renderer="xelatex",
            )
        )
    return tuple(snapshots)


def _snapshot_fingerprint(
    *,
    request: GenerationRequest,
    execution: GenerationExecutionSnapshot,
    templates: tuple[GenerationTemplateSnapshot, ...],
) -> str:
    payload = {
        "request": request.model_dump(mode="json", by_alias=True),
        "execution": execution.as_dict(),
        "templates": [item.model_dump(mode="json", by_alias=True) for item in templates],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "GenerationRunSnapshot",
    "GenerationTemplateSnapshot",
    "build_generation_run_snapshot",
    "resolve_template_snapshots",
]
