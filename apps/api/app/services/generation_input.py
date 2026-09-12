"""Build authoritative generator input without depending on vacancy analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.applications import StoredApplicationRecord
from app.models.documents import DocumentType
from app.models.generation import (
    GenerationApplicationSnapshot,
    GenerationMasterProfileVersion,
    GenerationRequest,
    GenerationVacancySnapshot,
    without_internal_generation_context,
)
from app.models.jobs import StoredJobRecord, is_job_state_placeholder
from app.models.resume import MasterResume, ResumeMasterRecord, ResumeMasterVersionRecord

MAX_VACANCY_DESCRIPTION_LENGTH = 200_000


class GenerationInputError(ValueError):
    """A stable, user-presentable failure while resolving generation sources."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def build_generation_input(
    db: Session,
    *,
    application_id: str,
    document_types: Sequence[DocumentType],
    language: str,
    formatting_parameters: Mapping[str, JsonValue],
    user_preferences: str,
    master_profile_id: str | None = None,
    master_profile_version: int | None = None,
) -> GenerationRequest:
    """Resolve and validate a self-contained request for a document generator.

    Application and vacancy revisions plus the immutable master-profile version
    and hash are copied into the request. No match record, preparation analysis,
    or questionnaire is read by this function.
    """

    application = db.scalar(
        select(StoredApplicationRecord).where(StoredApplicationRecord.id == application_id)
    )
    if application is None:
        raise GenerationInputError(
            "Application not found.",
            code="application_not_found",
        )
    application_data = _require_json_object(
        application.data,
        message="Application data is unavailable.",
        code="application_data_missing",
    )
    job_id = _application_job_id(application_data)
    if not job_id:
        raise GenerationInputError(
            "Application does not reference a vacancy.",
            code="application_vacancy_missing",
        )

    vacancy = db.scalar(select(StoredJobRecord).where(StoredJobRecord.id == job_id))
    if vacancy is None or is_job_state_placeholder(vacancy):
        raise GenerationInputError(
            "The vacancy referenced by the application is unavailable.",
            code="vacancy_not_found",
        )
    vacancy_data = _require_json_object(
        vacancy.data,
        message="Vacancy data is unavailable.",
        code="vacancy_data_missing",
    )
    vacancy_data["id"] = vacancy.id
    _require_vacancy_identity(vacancy_data)
    full_description = build_full_vacancy_description(vacancy_data)

    master, version = _load_master_profile_version(
        db,
        master_profile_id=master_profile_id,
        master_profile_version=master_profile_version,
    )
    master_data = _validated_master_profile_data(master, version)

    clean_application_data = without_internal_generation_context(application_data)
    clean_vacancy_data = without_internal_generation_context(vacancy_data)
    return GenerationRequest(
        application=GenerationApplicationSnapshot(
            id=application.id,
            revision=application.revision,
            data=clean_application_data,
        ),
        vacancy=GenerationVacancySnapshot(
            id=vacancy.id,
            revision=vacancy.revision,
            full_description=full_description,
            data=clean_vacancy_data,
        ),
        master_profile_version=GenerationMasterProfileVersion(
            id=master.id,
            version=version.version,
            content_sha256=version.content_sha256,
            data=master_data,
        ),
        document_types=tuple(document_types),
        language=language,
        formatting_parameters=dict(formatting_parameters),
        user_preferences=user_preferences,
    )


def build_full_vacancy_description(data: Mapping[str, Any]) -> str:
    """Build one lossless readable description from normalized vacancy fields."""

    if any(
        _is_missing_description_placeholder(value)
        for field in ("fullDescription", "description", "jobDescription", "overview")
        for value in _text_values(data.get(field))
    ):
        raise GenerationInputError(
            "Vacancy has no full description; refresh it from the source or add one manually.",
            code="vacancy_description_missing",
        )

    sections: list[tuple[str, list[str]]] = []
    for label, fields in (
        ("Description", ("fullDescription", "description", "jobDescription")),
        ("Overview", ("overview",)),
        ("Responsibilities", ("responsibilities",)),
        ("Requirements", ("requirements",)),
    ):
        values: list[str] = []
        for field in fields:
            values.extend(_text_values(data.get(field)))
        values = _unique_text(values)
        if values:
            sections.append((label, values))

    if not sections:
        raise GenerationInputError(
            "Vacancy description is incomplete; add an overview, responsibilities, or requirements.",
            code="vacancy_description_missing",
        )

    for label, fields in (
        ("Skills", ("skills",)),
        ("Company", ("companyInfo",)),
    ):
        values = _unique_text([item for field in fields for item in _text_values(data.get(field))])
        if values:
            sections.append((label, values))

    description = "\n\n".join(
        f"{label}\n" + "\n".join(value if len(values) == 1 else f"- {value}" for value in values)
        for label, values in sections
    )
    if len(description) > MAX_VACANCY_DESCRIPTION_LENGTH:
        raise GenerationInputError(
            "Vacancy description is too large for document generation.",
            code="vacancy_description_too_large",
        )
    return description


def _load_master_profile_version(
    db: Session,
    *,
    master_profile_id: str | None,
    master_profile_version: int | None,
) -> tuple[ResumeMasterRecord, ResumeMasterVersionRecord]:
    master_query = select(ResumeMasterRecord)
    if master_profile_id is not None:
        master_query = master_query.where(ResumeMasterRecord.id == master_profile_id)
    else:
        master_query = master_query.order_by(
            ResumeMasterRecord.updated_at.desc(),
            ResumeMasterRecord.created_at.desc(),
        ).limit(1)
    master = db.scalar(master_query)
    if master is None:
        raise GenerationInputError(
            "Confirmed Master Resume not found.",
            code="master_profile_not_found",
        )

    version_number = (
        master_profile_version if master_profile_version is not None else master.current_version
    )
    version = db.scalar(
        select(ResumeMasterVersionRecord).where(
            ResumeMasterVersionRecord.resume_master_id == master.id,
            ResumeMasterVersionRecord.version == version_number,
        )
    )
    if version is None:
        raise GenerationInputError(
            f"Master Resume version {version_number} is unavailable.",
            code="master_profile_version_not_found",
        )
    return master, version


def _validated_master_profile_data(
    master: ResumeMasterRecord,
    version: ResumeMasterVersionRecord,
) -> dict[str, JsonValue]:
    if _canonical_json_sha256(version.data) != version.content_sha256:
        raise GenerationInputError(
            "Master Resume version failed its integrity check.",
            code="master_profile_integrity_error",
        )
    try:
        profile = MasterResume.model_validate(version.data)
    except ValidationError as exc:
        raise GenerationInputError(
            "Master Resume version is invalid.",
            code="master_profile_invalid",
        ) from exc
    if profile.id != master.id:
        raise GenerationInputError(
            "Master Resume version does not match its profile.",
            code="master_profile_integrity_error",
        )
    return profile.model_dump(mode="json", by_alias=True)


def _application_job_id(data: Mapping[str, Any]) -> str:
    job = data.get("job")
    if isinstance(job, dict):
        job_id = str(job.get("id") or "").strip()
        if job_id:
            return job_id
    return str(data.get("jobId") or data.get("job_id") or "").strip()


def _require_vacancy_identity(data: Mapping[str, Any]) -> None:
    missing = [
        label
        for label, key in (("title", "title"), ("company", "company"))
        if not str(data.get(key) or "").strip()
    ]
    if missing:
        raise GenerationInputError(
            f"Vacancy is missing required data: {', '.join(missing)}.",
            code="vacancy_data_incomplete",
        )


def _require_json_object(value: Any, *, message: str, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GenerationInputError(message, code=code)
    return dict(value)


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, (list, tuple)):
        return [normalized for item in value if (normalized := str(item).strip())]
    return []


def _unique_text(values: Sequence[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.casefold().split())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(value)
    return unique


def _is_missing_description_placeholder(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return (
        "open the source vacancy to review the full description" in normalized
        or "open the source job to review the full description" in normalized
    )


def _canonical_json_sha256(data: Mapping[str, Any]) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "GenerationInputError",
    "build_full_vacancy_description",
    "build_generation_input",
]
