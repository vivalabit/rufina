from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from pydantic import ValidationError

from app.core.settings import Settings
from app.models.resume import MasterResume, ResumeSourceExtraction
from app.services.ai_backend import (
    AIBackend,
    AIBackendError,
    AIRequest,
    create_configured_ai_backend,
)


MAX_MASTER_IMPORT_CONTEXT_CHARACTERS = 120_000
CURRENT_END_DATE_MARKERS = {
    "present",
    "current",
    "now",
    "ongoing",
    "today",
    "aktuell",
    "gegenwart",
    "heute",
    "сейчас",
    "по настоящее время",
    "дотепер",
    "нині",
}


class MasterResumeImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class MasterResumeImportOutcome:
    master_resume: MasterResume
    model: str
    backend: str


@dataclass(frozen=True)
class MasterResumeImportAIFacade:
    backend: AIBackend
    model: str
    agent_id: str
    thinking: str
    timeout_seconds: int

    def import_source(
        self,
        *,
        source: ResumeSourceExtraction,
        master_resume_id: str,
    ) -> MasterResumeImportOutcome:
        return import_master_resume_with_ai(
            source=source,
            master_resume_id=master_resume_id,
            backend=self.backend,
            model=self.model,
            agent_id=self.agent_id,
            thinking=self.thinking,
            timeout_seconds=self.timeout_seconds,
        )


def create_master_resume_import_ai_facade(
    settings: Settings,
) -> MasterResumeImportAIFacade:
    return MasterResumeImportAIFacade(
        backend=create_configured_ai_backend(settings),
        model=(
            settings.openai_api_model
            if settings.ai_backend_mode == "openai_api"
            else ""
        ),
        agent_id=settings.openclaw_agent_id,
        thinking=settings.ai_reasoning_for(
            settings.openclaw_resume_import_thinking
        ),
        timeout_seconds=settings.ai_timeout_for(
            settings.openclaw_resume_import_timeout_seconds
        ),
    )


def import_master_resume_with_ai(
    *,
    source: ResumeSourceExtraction,
    master_resume_id: str,
    backend: AIBackend,
    model: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
) -> MasterResumeImportOutcome:
    prompt = build_master_resume_import_prompt(
        source=source,
        master_resume_id=master_resume_id,
    )
    try:
        # This is deliberately one generation request. Vacancy-specific resume
        # diagnosis, experience rewriting, and ATS review are separate workflows.
        result = backend.generate(
            AIRequest(
                prompt=prompt,
                model=model,
                agent_id=agent_id,
                thinking=thinking,
                timeout_seconds=timeout_seconds,
                session_id=f"agent:{agent_id}:master-resume-import-{uuid4().hex}",
                structured=True,
                response_model=MasterResume,
            )
        )
    except AIBackendError as exc:
        if exc.code == "runtime_missing":
            message = "The configured AI runtime is unavailable"
        elif exc.code == "timeout":
            message = "Master resume import timed out"
        else:
            message = "AI master resume import failed"
        raise MasterResumeImportError(message) from exc

    payload = result.structured_data
    if not isinstance(payload, dict):
        raise MasterResumeImportError(
            "AI master resume import did not return structured data"
        )
    payload = normalize_master_resume_payload(payload)
    try:
        master_resume = MasterResume.model_validate(payload)
    except ValidationError as exc:
        raise MasterResumeImportError(
            "AI master resume import returned an invalid MasterResume"
        ) from exc

    validate_master_resume_source_evidence(
        master_resume,
        source=source,
        expected_master_resume_id=master_resume_id,
    )
    return MasterResumeImportOutcome(
        master_resume=master_resume,
        model=result.model,
        backend=result.backend,
    )


def normalize_master_resume_payload(payload: dict[str, object]) -> dict[str, object]:
    """Normalize equivalent current-role date representations before validation."""
    normalized = deepcopy(payload)
    experiences = normalized.get("experiences")
    if not isinstance(experiences, list):
        return normalized

    for experience in experiences:
        if not isinstance(experience, dict) or experience.get("isCurrent") is not True:
            continue
        end_date = experience.get("endDate")
        if (
            isinstance(end_date, str)
            and end_date.strip().casefold() in CURRENT_END_DATE_MARKERS
        ):
            experience["endDate"] = ""
    return normalized


def build_master_resume_import_prompt(
    *,
    source: ResumeSourceExtraction,
    master_resume_id: str,
) -> str:
    master_resume_schema = json.dumps(
        MasterResume.model_json_schema(by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    source_payload = {
        "sourceFormat": source.source_format,
        "layout": source.layout,
        "pageCount": source.page_count,
        "fragments": [
            {
                "id": fragment.id,
                "order": fragment.order,
                "pageNumber": fragment.page_number,
                "columnIndex": fragment.column_index,
                "text": fragment.text,
            }
            for fragment in source.fragments
        ],
    }
    compact_source = json.dumps(
        source_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(compact_source) > MAX_MASTER_IMPORT_CONTEXT_CHARACTERS:
        raise MasterResumeImportError(
            "Resume source is too large for one master-resume import request"
        )

    return (
        "ONE-TIME MASTER RESUME IMPORT. Parse the supplied source fragments into one "
        "vacancy-independent canonical MasterResume. This request is not a vacancy "
        "analysis, experience rewrite, ATS review, or tailored-resume generation.\n"
        "Return only a JSON object matching the provided MasterResume schema.\n"
        f'Use the exact top-level id "{master_resume_id}" and schemaVersion "1.0".\n'
        "Rules:\n"
        "- Preserve facts and the source language; never tailor wording to a vacancy.\n"
        "- Never invent names, employers, titles, dates, metrics, technologies, "
        "credentials, proficiency levels, or achievements.\n"
        "- Preserve distinct roles, degrees, projects, certifications, and languages.\n"
        "- For a current role set isCurrent to true and endDate to an empty string; "
        "never put Present, Current, or an equivalent marker in endDate.\n"
        "- Use concise stable IDs containing only letters, digits, dot, underscore, "
        "colon, slash, or hyphen; all item IDs must be unique.\n"
        "- Every summary, bullet, skill, certification, language, and additional item "
        "must cite one or more exact fragment IDs in evidenceIds.\n"
        "- Include in evidence only cited fragments. Each evidence item must use the "
        "exact fragment id, type 'source', and the fragment's exact text.\n"
        "- Do not cite a fragment for wording it does not support.\n"
        "- If a date or optional field is absent, keep it empty; never infer it.\n"
        "- sectionOrder must list every non-empty section exactly once and no empty "
        "section. Allowed values: summary, experience, skills, education, projects, "
        "certifications, languages, additional.\n"
        "- Keep arrays empty when the source has no supported content for that section.\n"
        "MASTER_RESUME_JSON_SCHEMA:\n"
        f"{master_resume_schema}\n"
        "SOURCE_FRAGMENTS_JSON:\n"
        f"{compact_source}"
    )


def validate_master_resume_source_evidence(
    master_resume: MasterResume,
    *,
    source: ResumeSourceExtraction,
    expected_master_resume_id: str,
) -> None:
    if master_resume.id != expected_master_resume_id:
        raise MasterResumeImportError(
            "AI master resume import changed the server-assigned resume ID"
        )

    fragments_by_id = {fragment.id: fragment for fragment in source.fragments}
    for evidence in master_resume.evidence:
        fragment = fragments_by_id.get(evidence.id)
        if fragment is None:
            raise MasterResumeImportError(
                f'AI master resume import cited unknown source fragment "{evidence.id}"'
            )
        if evidence.type != "source":
            raise MasterResumeImportError(
                "Master resume import evidence must use type source"
            )
        if evidence.text != fragment.text:
            raise MasterResumeImportError(
                f'AI master resume import changed source evidence "{evidence.id}"'
            )
        if (
            evidence.claim_type is not None
            or evidence.experience_id is not None
            or evidence.source_id is not None
        ):
            raise MasterResumeImportError(
                "Master resume import source evidence cannot add claim metadata"
            )


__all__ = [
    "MAX_MASTER_IMPORT_CONTEXT_CHARACTERS",
    "MasterResumeImportAIFacade",
    "MasterResumeImportError",
    "MasterResumeImportOutcome",
    "build_master_resume_import_prompt",
    "create_master_resume_import_ai_facade",
    "import_master_resume_with_ai",
    "normalize_master_resume_payload",
    "validate_master_resume_source_evidence",
]
