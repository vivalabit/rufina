"""Build the immutable, reproducible input snapshot for a generation run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.models.generation import GenerationRequest, GenerationStartRequest
from app.services.document_rendering import (
    COVER_LETTER_TEMPLATE_VERSION,
    DocumentRenderError,
    cover_letter_design_sha256,
    resolve_document_template,
)
from app.services.generation_input import GenerationInputError, build_generation_input
from app.services.generation_runtime import (
    GenerationExecutionSnapshot,
    snapshot_generation_execution,
)
from app.services.resume_pdf_renderer import ResolvedResumeTemplate

DOCUMENT_RENDERER = "chromium"


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


def requested_template_id(request: GenerationRequest) -> str | None:
    """The single design family requested for all documents of a run."""
    selected: list[str] = []
    for document_type in request.document_types:
        parameters = request.formatting_parameters.get(document_type)
        value = parameters.get("templateId") if isinstance(parameters, dict) else None
        if value is not None and not isinstance(value, str):
            raise GenerationInputError(
                "Document template ID must be a string",
                code="document_template_unsupported",
            )
        if value and value.strip():
            selected.append(value.strip())
    if len(set(selected)) > 1:
        raise GenerationInputError(
            "CV and cover letter must use the same document template",
            code="document_template_mismatch",
        )
    return selected[0] if selected else None


def template_snapshots(
    template: ResolvedResumeTemplate,
    document_types: tuple[str, ...] | list[str],
) -> tuple[GenerationTemplateSnapshot, ...]:
    return tuple(
        GenerationTemplateSnapshot(
            document_type=document_type,
            template_id=template.id,
            template_version=(
                template.version
                if document_type == "tailored_resume"
                else COVER_LETTER_TEMPLATE_VERSION
            ),
            content_sha256=(
                template.design_sha256
                if document_type == "tailored_resume"
                else cover_letter_design_sha256(template)
            ),
            renderer=DOCUMENT_RENDERER,
        )
        for document_type in document_types
    )


def resolve_template_snapshots(
    db: Session,
    request: GenerationRequest,
) -> tuple[GenerationTemplateSnapshot, ...]:
    """Pin the gallery template every document of the run starts with.

    The template only decides the first rendering. A finished run can be
    rendered again in any other template without a new run.
    """
    try:
        template = resolve_document_template(requested_template_id(request), db=db)
    except DocumentRenderError as exc:
        raise GenerationInputError(str(exc), code=exc.code) from exc
    return template_snapshots(template, request.document_types)


def run_request(input_snapshot: dict[str, Any]) -> GenerationRequest:
    """Read the frozen request of a run, including runs of earlier pipeline versions."""
    try:
        return GenerationRequest.model_validate(input_snapshot.get("request"))
    except ValidationError as exc:
        raise GenerationInputError(
            "Persisted generation input snapshot is invalid",
            code="invalid_snapshot",
        ) from exc


def run_created_at(input_snapshot: dict[str, Any]) -> datetime:
    value = input_snapshot.get("createdAt") or input_snapshot.get("created_at")
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.now(UTC)


def run_template_id(input_snapshot: dict[str, Any]) -> str | None:
    templates = input_snapshot.get("templates")
    if isinstance(templates, list) and templates and isinstance(templates[0], dict):
        value = templates[0].get("templateId") or templates[0].get("template_id")
        return value if isinstance(value, str) else None
    return None


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
    "DOCUMENT_RENDERER",
    "GenerationRunSnapshot",
    "GenerationTemplateSnapshot",
    "build_generation_run_snapshot",
    "requested_template_id",
    "resolve_template_snapshots",
    "run_created_at",
    "run_request",
    "run_template_id",
    "template_snapshots",
]
