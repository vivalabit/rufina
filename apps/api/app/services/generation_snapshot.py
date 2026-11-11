"""Build the immutable, reproducible input snapshot for a generation run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.models.generation import GenerationRequest, GenerationStartRequest
from app.services.generation_input import GenerationInputError, build_generation_input
from app.services.generation_resume_templates import (
    LEGACY_GENERATION_RESUME_TEMPLATE_IDS,
    resolve_generation_resume_template,
)
from app.services.generation_runtime import (
    GenerationExecutionSnapshot,
    snapshot_generation_execution,
)


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
    # One design family applies to every document in a run. Missing selections
    # inherit the explicitly selected family, including cover-letter-only runs.
    selected: dict[str, GenerationTemplateSnapshot] = {}
    for document_type in request.document_types:
        parameters = request.formatting_parameters.get(document_type)
        values = parameters if isinstance(parameters, dict) else {}
        template_id = values.get("templateId")
        if template_id is not None and not isinstance(template_id, str):
            raise GenerationInputError(
                "Document template ID must be a string",
                code=("resume_template_unsupported" if document_type == "tailored_resume"
                      else "cover_letter_template_unsupported"),
            )
        if template_id and template_id.strip():
            selected[document_type] = (
                _resume_template_snapshot(template_id)
                if document_type == "tailored_resume"
                else _cover_letter_template_snapshot(template_id)
            )
    if len({item.template_id for item in selected.values()}) > 1:
        raise GenerationInputError(
            "CV and cover letter must use the same document template",
            code="document_template_mismatch",
        )
    family = next(iter(selected.values())).template_id if selected else None
    return tuple(
        _resume_template_snapshot(family) if document_type == "tailored_resume"
        else _cover_letter_template_snapshot(family)
        for document_type in request.document_types
    )


def resolve_run_document_template_id(snapshot: GenerationRunSnapshot) -> str:
    templates = [
        resolve_run_resume_template(snapshot) if document_type == "tailored_resume"
        else resolve_run_cover_letter_template(snapshot)
        for document_type in snapshot.request.document_types
    ]
    if len({item.template_id for item in templates}) != 1:
        raise GenerationInputError(
            "CV and cover letter must use the same document template",
            code="document_template_mismatch",
        )
    return templates[0].template_id


def resolve_run_cover_letter_template(snapshot: GenerationRunSnapshot) -> GenerationTemplateSnapshot:
    pinned = next(
        (item for item in snapshot.templates if item.document_type == "cover_letter"), None,
    )
    if pinned is None:
        raise GenerationInputError(
            "The generation snapshot has no cover-letter template",
            code="cover_letter_template_missing",
        )
    try:
        actual = _cover_letter_template_snapshot(pinned.template_id)
    except GenerationInputError:
        actual = None
    # Historical UUID templates described a DOCX that the LaTeX renderer did
    # not use. Never silently label new output with that unrelated design hash.
    if actual != pinned:
        raise GenerationInputError(
            "The selected cover-letter template changed after this run started. "
            "Start a new generation run to use the current template.",
            code="cover_letter_template_changed",
        )
    return pinned


def resolve_run_resume_template(snapshot: GenerationRunSnapshot) -> GenerationTemplateSnapshot:
    """Resolve the pinned renderer, without modifying the immutable run input."""
    pinned = next(
        (item for item in snapshot.templates if item.document_type == "tailored_resume"),
        None,
    )
    if pinned is None:
        raise GenerationInputError(
            "The generation snapshot has no resume template",
            code="resume_template_missing",
        )
    if _is_legacy_resume_template_snapshot(pinned):
        # Old snapshots pinned unrelated HTML designs. Keep their historical
        # data unchanged, but new output metadata must identify the Banking
        # renderer actually used when recovering the run.
        return _resume_template_snapshot(None)
    actual = _resume_template_snapshot(pinned.template_id)
    if pinned != actual:
        raise GenerationInputError(
            "The selected resume template changed after this run started. "
            "Start a new generation run to use the current template.",
            code="resume_template_changed",
        )
    return pinned


def _is_legacy_resume_template_snapshot(template: GenerationTemplateSnapshot) -> bool:
    if template.renderer != "lualatex":
        return False
    if template.template_id in LEGACY_GENERATION_RESUME_TEMPLATE_IDS:
        return True
    # Before template selection, saved custom HTML designs had UUID IDs and
    # positive integer revisions. Only accept that historical persisted shape;
    # new run creation still rejects custom and unknown template IDs.
    try:
        identifier = UUID(template.template_id)
    except ValueError:
        return False
    return (
        str(identifier) == template.template_id
        and template.template_version.isascii()
        and template.template_version.isdecimal()
        and int(template.template_version) > 0
    )


def _resume_template_snapshot(template_id: str | None) -> GenerationTemplateSnapshot:
    try:
        template = resolve_generation_resume_template(template_id)
    except ValueError as exc:
        raise GenerationInputError(str(exc), code="resume_template_unsupported") from exc
    return GenerationTemplateSnapshot(
        document_type="tailored_resume",
        template_id=template.id,
        template_version=template.version,
        content_sha256=template.content_sha256,
        renderer=template.renderer,
    )


def _cover_letter_template_snapshot(template_id: str | None) -> GenerationTemplateSnapshot:
    try:
        template = resolve_generation_resume_template(template_id)
    except ValueError as exc:
        raise GenerationInputError(str(exc), code="cover_letter_template_unsupported") from exc
    version = "1.0.0"
    digest = hashlib.sha256(
        f"cover_letter\0{version}\0{template.content_sha256}".encode()
    ).hexdigest()
    return GenerationTemplateSnapshot(
        document_type="cover_letter",
        template_id=template.id,
        template_version=version,
        content_sha256=digest,
        renderer="xelatex",
    )


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
    "resolve_run_resume_template",
    "resolve_run_cover_letter_template",
    "resolve_run_document_template_id",
    "resolve_template_snapshots",
]
