from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

from app.core.settings import Settings
from app.models.ai_match import AiMatchMetadata, AiMatchScore
from app.models.profile import ProfilePayload
from app.services.ai_backend import (
    AIBackend,
    AIBackendError,
    AIRequest,
    OpenClawCodexBackend,
    create_configured_ai_backend,
)
from app.services.resume_import import (
    extract_json_objects,
    extract_openclaw_text_payloads,
    summarize_openclaw_error,
)

MATCHER_VERSION = "ai-match-v6"
MATCH_PROMPT_VERSION = "ai-match-prompt-v8"
DEFAULT_AI_MATCH_MODEL = "openai/gpt-6.1-sol"
DEFAULT_AI_MATCH_MAX_ATTEMPTS = 2
MAX_AI_MATCH_TEXT_LENGTH = 500
JOB_ADDED_AT_FIELDS = ("addedAt", "importedAt", "createdAt", "created_at")
RUNTIME_PROFILE_FILE_FINGERPRINT_FIELDS = (
    "id",
    "kind",
    "title",
    "category",
    "language",
    "issuer",
    "notes",
    "file_name",
    "size_bytes",
    "content_type",
    "content_sha256",
)

SKILL_ALIASES = {
    "ai": "artificial intelligence",
    "ar": "augmented reality",
    "backend": "back end",
    "back-end": "back end",
    "computer vision": "computer vision",
    "ci cd": "ci/cd",
    "cv": "computer vision",
    "devops": "development operations",
    "front-end": "front end",
    "frontend": "front end",
    "gen ai": "generative artificial intelligence",
    "gen-ai": "generative artificial intelligence",
    "genai": "generative artificial intelligence",
    "generative ai": "generative artificial intelligence",
    "gpt": "large language model",
    "js": "javascript",
    "large language models": "large language model",
    "llms": "large language model",
    "llm": "large language model",
    "ml": "machine learning",
    "ml ops": "machine learning operations",
    "ml-ops": "machine learning operations",
    "mlops": "machine learning operations",
    "nlp": "natural language processing",
    "node": "node",
    "node.js": "node",
    "nodejs": "node",
    "react.js": "react",
    "reactjs": "react",
    "ts": "typescript",
    "vr": "virtual reality",
    "xr": "extended reality",
}

CURRENCY_ALIASES = {
    "CHF": {"chf", "fr", "sfr", "swiss franc", "swiss francs"},
    "EUR": {"eur", "euro", "euros", "€"},
    "GBP": {"gbp", "pound", "pounds", "£"},
    "USD": {"usd", "dollar", "dollars", "$"},
}
SENIORITY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "lead",
        ("principal", "staff", "lead", "manager", "head", "director", "vp", "chief", "architect"),
    ),
    ("senior", ("senior", "sr", "experienced", "expert", "advanced")),
    ("mid", ("mid", "mid level", "mid-level", "intermediate", "regular", "professional")),
    ("junior", ("junior", "jr", "entry", "entry level", "graduate", "new grad", "associate")),
    ("intern", ("intern", "internship", "trainee", "apprentice", "working student", "student")),
)


class AiMatchError(RuntimeError):
    pass


# Backward-compatible name for the locked OpenClaw matching surface.
OpenClawAiMatchError = AiMatchError


StrictText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_AI_MATCH_TEXT_LENGTH),
]


class StrictAiMatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class AiMatchResult(AiMatchScore):
    id: StrictText


class AiMatchPayload(StrictAiMatchModel):
    matches: list[AiMatchResult] = Field(min_length=1)


# Compatibility aliases for existing integrations and tests.
OpenClawAiMatchResult = AiMatchResult
OpenClawAiMatchPayload = AiMatchPayload


@dataclass(frozen=True)
class VacancyMatchingAIFacade:
    backend: AIBackend
    command: str
    agent_id: str
    thinking: str
    timeout_seconds: int
    enabled: bool
    max_jobs: int
    model: str
    max_attempts: int
    retry_backoff_seconds: float

    def match(
        self,
        profile: ProfilePayload,
        jobs: list[dict[str, Any]],
        *,
        force: bool = False,
        candidate_snapshot: dict[str, Any] | None = None,
        profile_version: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        return calculate_ai_matches(
            profile,
            jobs,
            command=self.command,
            agent_id=self.agent_id,
            thinking=self.thinking,
            timeout_seconds=self.timeout_seconds,
            openclaw_enabled=self.enabled,
            openclaw_max_jobs=self.max_jobs,
            model=self.model,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
            force=force,
            candidate_snapshot=candidate_snapshot,
            profile_version=profile_version,
            backend=self.backend,
            progress_callback=progress_callback,
        )


def create_vacancy_matching_ai_facade(settings: Settings) -> VacancyMatchingAIFacade:
    return VacancyMatchingAIFacade(
        backend=create_configured_ai_backend(settings),
        command=settings.openclaw_command,
        agent_id=settings.openclaw_agent_id,
        thinking=settings.ai_match_reasoning_value(),
        timeout_seconds=settings.ai_match_timeout_seconds_value(),
        enabled=settings.openclaw_ai_match_enabled,
        max_jobs=settings.ai_match_batch_size_value(),
        model=settings.ai_match_model_value(),
        max_attempts=settings.ai_match_max_attempts_value(),
        retry_backoff_seconds=settings.ai_retry_backoff_for(0),
    )


def calculate_ai_matches(
    profile: ProfilePayload,
    jobs: list[dict[str, Any]],
    *,
    command: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
    openclaw_enabled: bool,
    openclaw_max_jobs: int,
    model: str = DEFAULT_AI_MATCH_MODEL,
    max_attempts: int = DEFAULT_AI_MATCH_MAX_ATTEMPTS,
    retry_backoff_seconds: float = 0,
    force: bool = False,
    candidate_snapshot: dict[str, Any] | None = None,
    profile_version: str | None = None,
    backend: AIBackend | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    if not openclaw_enabled:
        raise AiMatchError("AI vacancy matching is required but disabled")
    if openclaw_max_jobs <= 0:
        raise AiMatchError("AI vacancy matching requires a positive job batch size")

    profile_snapshot = candidate_snapshot or build_candidate_snapshot(profile)
    resolved_profile_version = profile_version or build_profile_input_hash(profile)
    backend_source = backend.name if backend is not None else "openclaw_codex"
    ordered_jobs: list[dict[str, Any] | tuple[dict[str, Any], dict[str, Any], str]] = []
    now = datetime.now(UTC).isoformat()
    jobs_to_score: list[tuple[dict[str, Any], dict[str, Any], str]] = []

    for job in jobs:
        if not isinstance(job, dict):
            continue

        job_snapshot = build_job_snapshot(job)
        vacancy_version = build_job_snapshot_hash(job_snapshot)
        cache_key = build_cache_key(
            profile_version=resolved_profile_version,
            vacancy_version=vacancy_version,
            model=model,
            prompt_version=MATCH_PROMPT_VERSION,
            backend=backend_source,
        )
        cached_match = job.get("aiMatch")
        if (
            not force
            and is_cached_match_valid(
                cached_match,
                cache_key,
                profile_version=resolved_profile_version,
                vacancy_version=vacancy_version,
                model=model,
                backend=backend_source,
                prompt_version=MATCH_PROMPT_VERSION,
            )
        ):
            ordered_jobs.append(job)
            continue

        scored_job = (job, job_snapshot, cache_key)
        jobs_to_score.append(scored_job)
        ordered_jobs.append(scored_job)

    if not jobs_to_score:
        return [item for item in ordered_jobs if isinstance(item, dict)]

    by_id: dict[str, dict[str, Any]] = {}
    for start in range(0, len(jobs_to_score), openclaw_max_jobs):
        chunk = jobs_to_score[start : start + openclaw_max_jobs]
        chunk_snapshots = [job_snapshot for _, job_snapshot, _ in chunk]
        correction_feedback: str | None = None
        for attempt in range(max(1, max_attempts)):
            try:
                openclaw_results = score_with_openclaw(
                    profile_snapshot=profile_snapshot,
                    jobs=chunk_snapshots,
                    command=command,
                    agent_id=agent_id,
                    thinking=thinking,
                    timeout_seconds=timeout_seconds,
                    model=model,
                    correction_feedback=correction_feedback,
                    backend=backend,
                )
                openclaw_results = validate_openclaw_batch(
                    openclaw_results,
                    expected_job_ids=[job["id"] for job in chunk_snapshots],
                )
                break
            except OpenClawAiMatchError as exc:
                if attempt + 1 >= max(1, max_attempts):
                    raise
                correction_feedback = str(exc)
                if retry_backoff_seconds > 0:
                    time.sleep(retry_backoff_seconds * (2**attempt))
        by_id.update(
            {
                result["id"]: result
                for result in openclaw_results
                if isinstance(result.get("id"), str)
            }
        )
        if progress_callback is not None:
            progress_callback(
                min(start + len(chunk), len(jobs_to_score)),
                len(jobs_to_score),
            )

    scored_ids = {job_snapshot["id"] for _, job_snapshot, _ in jobs_to_score}
    missing_ids = sorted(scored_ids - set(by_id))
    if missing_ids:
        raise AiMatchError(f"AI backend did not return matches for: {', '.join(missing_ids[:8])}")

    return [
        item
        if isinstance(item, dict)
        else apply_match_result(
            item[0],
            normalize_openclaw_result(
                by_id[item[1]["id"]],
                item[0],
                backend_source=backend_source,
            ),
            item[2],
            now,
            profile_hash=resolved_profile_version,
            vacancy_hash=build_job_snapshot_hash(item[1]),
            model=model,
            prompt_version=MATCH_PROMPT_VERSION,
        )
        for item in ordered_jobs
    ]


def build_profile_files_fingerprint(profile: ProfilePayload) -> str:
    primary_resume = profile.runtime_primary_resume
    supporting_documents = profile.runtime_supporting_documents
    if not isinstance(primary_resume, dict) and not supporting_documents:
        return ""

    def fingerprint_metadata(
        value: dict[str, Any],
        *,
        include_extracted_text: bool,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for field in RUNTIME_PROFILE_FILE_FINGERPRINT_FIELDS:
            field_value = value.get(field)
            if isinstance(field_value, (str, int, float, bool)) and field_value != "":
                metadata[field] = field_value
        if include_extracted_text:
            extracted_text = str(value.get("extracted_text") or "")
            metadata["extracted_text_sha256"] = hashlib.sha256(
                extracted_text.encode("utf-8")
            ).hexdigest()
        return metadata

    material = {
        "primary_resume": (
            fingerprint_metadata(primary_resume, include_extracted_text=True)
            if isinstance(primary_resume, dict)
            else None
        ),
        "supporting_documents": sorted(
            (
                fingerprint_metadata(document, include_extracted_text=False)
                for document in supporting_documents
                if isinstance(document, dict)
            ),
            key=lambda item: (
                str(item.get("id") or ""),
                str(item.get("content_sha256") or ""),
            ),
        ),
    }
    serialized = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_profile_input_hash(profile: ProfilePayload) -> str:
    """Version the source profile, including files, before AI normalization."""

    payload = json.dumps(
        {
            "profile": profile.model_dump(),
            "profile_files_hash": build_profile_files_fingerprint(profile),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_candidate_snapshot(profile: ProfilePayload) -> dict[str, Any]:
    preferences = parse_json_object(profile.job_preferences)
    experience_entries = parse_json_list(profile.experience)
    education_entries = parse_json_list(profile.education)
    primary_resume = profile.runtime_primary_resume
    supporting_documents = profile.runtime_supporting_documents
    resume_text = (
        str(primary_resume.get("extracted_text") or "")[:50_000]
        if isinstance(primary_resume, dict)
        else ""
    )
    skills = normalize_list(parse_lines(profile.skills))
    roles = normalize_list(
        [
            profile.current_role,
            profile.desired_role,
            *normalize_list(preferences.get("desired_roles", [])),
            *[entry.get("title", "") for entry in experience_entries if isinstance(entry, dict)],
        ]
    )
    domains = extract_keywords(
        " ".join(
            [
                profile.headline,
                profile.additional_notes,
                resume_text,
                *skills,
                *[
                    str(entry.get("description", ""))
                    for entry in experience_entries
                    if isinstance(entry, dict)
                ],
            ]
        )
    )[:20]

    return {
        "roles": roles[:12],
        "current_role": profile.current_role.strip(),
        "desired_role": profile.desired_role.strip(),
        "headline": profile.headline.strip()[:500],
        "skills": skills[:80],
        "domains": domains,
        "experience": summarize_experience(experience_entries),
        "education": summarize_education(education_entries),
        "locations": normalize_list(
            [profile.location, *normalize_list(preferences.get("locations", []))]
        ),
        "work_formats": normalize_list(
            [profile.work_format, *normalize_list(preferences.get("work_formats", []))]
        ),
        "employment_types": normalize_list(preferences.get("employment_types", [])),
        "industries": normalize_list(preferences.get("industries", [])),
        "seniority": normalize_list(preferences.get("seniority", [])),
        "salary_min": parse_number(preferences.get("salary_min", "")),
        "salary_currency": normalize_currency(preferences.get("salary_currency") or "CHF") or "CHF",
        "work_authorization": str(preferences.get("work_authorization") or "").strip(),
        "languages": normalize_list(preferences.get("languages", [])),
        "company_sizes": normalize_list(preferences.get("company_sizes", [])),
        "priorities": normalize_list(preferences.get("priorities", [])),
        "preference_notes": str(preferences.get("notes") or "").strip()[:500],
        "no_preference": normalize_list(preferences.get("no_preference", [])),
        "dealbreakers": normalize_list(parse_lines(profile.dealbreakers)),
        "additional_notes": profile.additional_notes.strip()[:500],
        "evidence": {
            "resume": isinstance(primary_resume, dict),
            "resume_file_name": (
                str(primary_resume.get("file_name") or "")
                if isinstance(primary_resume, dict)
                else ""
            ),
            "linkedin": bool(profile.linkedin),
            "github": bool(profile.github),
            "portfolio": bool(profile.portfolio or profile.personal_site),
            "documents": len(supporting_documents),
            "profile_files_hash": build_profile_files_fingerprint(profile),
        },
    }


def build_job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    requirements = normalize_list(job.get("requirements", []))
    responsibilities = normalize_list(job.get("responsibilities", []))
    skills = normalize_list(job.get("skills", []))
    overview = str(job.get("overview") or "")
    title = str(job.get("title") or "")
    company = str(job.get("company") or "")
    location = str(job.get("location") or "")
    employment_type = str(job.get("type") or "")
    experience = str(job.get("experience") or "")
    text = " ".join(
        [
            title,
            company,
            location,
            employment_type,
            experience,
            overview,
            *requirements,
            *responsibilities,
            *skills,
        ]
    )

    return {
        "id": str(job.get("id") or ""),
        "title": title.strip(),
        "company": company.strip(),
        "location": location.strip(),
        "employment_type": employment_type.strip(),
        "salary": str(job.get("salary") or "").strip(),
        "salary_amount": parse_job_salary(job),
        "salary_currency": parse_job_salary_currency(job),
        "experience": experience.strip(),
        "department": str(job.get("department") or "").strip(),
        "overview": overview.strip()[:4000],
        "requirements": requirements[:16],
        "responsibilities": responsibilities[:12],
        "skills": skills[:40],
        "keywords": extract_keywords(text)[:40],
        "source_url": str(job.get("sourceUrl") or job.get("applyUrl") or "").strip(),
    }


def score_with_openclaw(
    *,
    profile_snapshot: dict[str, Any],
    jobs: list[dict[str, Any]],
    command: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
    model: str = DEFAULT_AI_MATCH_MODEL,
    correction_feedback: str | None = None,
    backend: AIBackend | None = None,
) -> list[dict[str, Any]]:
    if not jobs:
        return []

    prompt = build_openclaw_ai_match_prompt(
        profile_snapshot,
        jobs,
        correction_feedback=correction_feedback,
    )
    selected_backend = backend or OpenClawCodexBackend(
        command=command,
        sync_runner=subprocess.run,
    )
    try:
        result = selected_backend.generate(
            AIRequest(
                prompt=prompt,
                model=model,
                agent_id=agent_id,
                thinking=thinking,
                timeout_seconds=timeout_seconds,
                structured=True,
                response_model=AiMatchPayload,
            )
        )
    except AIBackendError as exc:
        if exc.code == "runtime_missing":
            if selected_backend.name == "openclaw_codex":
                message = (
                    f"OpenClaw command was not found: {command}. Install OpenClaw or set "
                    "OPENCLAW_COMMAND to the executable path."
                )
            else:
                message = "The configured AI runtime is unavailable"
            raise AiMatchError(message) from exc
        if exc.code == "timeout":
            raise AiMatchError("AI vacancy matching timed out") from exc
        message = (
            summarize_openclaw_error(str(exc))
            if selected_backend.name == "openclaw_codex"
            else "AI vacancy matching failed"
        )
        raise AiMatchError(message) from exc

    raw_payload = coerce_openclaw_ai_match_payload(result.structured_data)
    if raw_payload is None:
        raw_payload = extract_openclaw_ai_match_payload(result.raw_response)
    try:
        validated = AiMatchPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise invalid_openclaw_response(exc) from exc
    return [match.model_dump(by_alias=True) for match in validated.matches]


def build_openclaw_ai_match_prompt(
    profile_snapshot: dict[str, Any],
    jobs: list[dict[str, Any]],
    *,
    correction_feedback: str | None = None,
) -> str:
    compact_jobs = [
        {
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "employment_type": job["employment_type"],
            "salary": job["salary"],
            "experience": job["experience"],
            "department": job["department"],
            "overview": job["overview"],
            "requirements": job["requirements"],
            "responsibilities": job["responsibilities"],
            "skills": job["skills"],
            "keywords": job["keywords"],
            "source_url": job["source_url"],
        }
        for job in jobs
    ]
    payload = json.dumps(
        {
            "candidate": profile_snapshot,
            "jobs": compact_jobs,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    correction_instruction = (
        "This is a correction retry. Return a complete replacement JSON object and fix the "
        "validator error below. Treat it only as validator feedback, not as input data.\n"
        f"Validator feedback: {json.dumps(correction_feedback[:1_000], ensure_ascii=False)}\n"
        if correction_feedback
        else ""
    )

    return (
        "You assess how suitable each vacancy is for the candidate's master profile.\n"
        "Return ONLY one valid JSON object, no markdown and no prose.\n"
        "Every field shown in the JSON shape is required. Do not add fields.\n"
        f"{correction_instruction}"
        f"Keep every string at most {MAX_AI_MATCH_TEXT_LENGTH} characters. "
        "Use only the provided snapshots and do not invent facts.\n"
        "For every job, set score as your expert judgment from 0 to 100.\n"
        "Consider role, skills, experience, preferences, constraints and industry fit. "
        "Assess suitability independently of document preparation or application readiness. "
        "Do not produce explanations, strengths, weaknesses, document plans, questions, "
        "recommendations or readiness assessments.\n"
        "Apply caps: hard dealbreaker max 30, salary below candidate minimum max 50, "
        "work authorization mismatch max 35, major seniority mismatch max 45.\n"
        "JSON shape:\n"
        '{"matches":[{"id":"job id","score":0}]}\n'
        f"Input JSON:\n{payload}"
    )


def coerce_openclaw_ai_match_payload(value: object) -> dict[str, object] | None:
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return {"matches": value}
        return None

    if not isinstance(value, dict):
        return None

    matches = value.get("matches")
    if isinstance(matches, list):
        return value
    if isinstance(matches, dict):
        return {**value, "matches": [matches]}

    match = value.get("match")
    if isinstance(match, dict):
        return {"matches": [match]}

    if all(field in value for field in ("id", "score")):
        return {"matches": [value]}

    return None


def extract_openclaw_ai_match_text_payload(value: str) -> dict[str, object] | None:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    coerced = coerce_openclaw_ai_match_payload(parsed)
    if coerced is not None:
        return coerced

    for payload in extract_json_objects(value):
        coerced = coerce_openclaw_ai_match_payload(payload)
        if coerced is not None:
            return coerced

    return None


def extract_openclaw_ai_match_payload(value: str) -> dict[str, object]:
    direct_payload = extract_openclaw_ai_match_text_payload(value)
    if direct_payload is not None:
        return direct_payload

    for payload in extract_json_objects(value):
        coerced = coerce_openclaw_ai_match_payload(payload)
        if coerced is not None:
            return coerced

        for text in extract_openclaw_text_payloads(payload):
            final_payload = extract_openclaw_ai_match_text_payload(text)
            if final_payload is not None:
                return final_payload

        result = payload.get("result")
        if not isinstance(result, dict):
            continue

        coerced = coerce_openclaw_ai_match_payload(result)
        if coerced is not None:
            return coerced

        for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
            final_text = result.get(key)
            if isinstance(final_text, str):
                final_payload = extract_openclaw_ai_match_text_payload(final_text)
                if final_payload is not None:
                    return final_payload

        nested_result = result.get("result")
        if isinstance(nested_result, dict):
            coerced = coerce_openclaw_ai_match_payload(nested_result)
            if coerced is not None:
                return coerced

            for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                final_text = nested_result.get(key)
                if isinstance(final_text, str):
                    final_payload = extract_openclaw_ai_match_text_payload(final_text)
                    if final_payload is not None:
                        return final_payload

    return {}


def normalize_openclaw_result(
    result: dict[str, Any],
    current_job: dict[str, Any],
    *,
    backend_source: str = "openclaw_codex",
) -> dict[str, Any]:
    validated = validate_openclaw_result(result, current_job)
    return {
        "score": validated.score,
        "source": backend_source,
        "backend": backend_source,
    }


def validate_openclaw_result(
    result: dict[str, Any],
    current_job: dict[str, Any],
) -> OpenClawAiMatchResult:
    job_id = str(result.get("id") or current_job.get("id") or "unknown")
    try:
        validated = OpenClawAiMatchResult.model_validate(result)
    except ValidationError as exc:
        raise invalid_openclaw_response(exc, job_id=job_id) from exc
    if validated.id != str(current_job.get("id") or ""):
        raise OpenClawAiMatchError(
            f"OpenClaw returned an invalid match for {job_id}: result ID does not match vacancy"
        )
    return validated


def validate_openclaw_batch(
    results: list[dict[str, Any]],
    *,
    expected_job_ids: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(results, list) or any(not isinstance(result, dict) for result in results):
        raise OpenClawAiMatchError("OpenClaw returned an invalid matches array")
    validated = [validate_openclaw_result(result, {"id": result.get("id")}) for result in results]
    result_ids = [result.id for result in validated]
    if len(result_ids) != len(set(result_ids)):
        raise OpenClawAiMatchError("OpenClaw returned duplicate match IDs")
    if set(result_ids) != set(expected_job_ids):
        missing = sorted(set(expected_job_ids) - set(result_ids))
        unexpected = sorted(set(result_ids) - set(expected_job_ids))
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing[:8])}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected[:8])}")
        raise OpenClawAiMatchError(
            "OpenClaw returned a mismatched match set"
            + (f" ({'; '.join(details)})" if details else "")
        )
    return [result.model_dump(by_alias=True) for result in validated]


def invalid_openclaw_response(
    exc: ValidationError,
    *,
    job_id: str = "payload",
) -> OpenClawAiMatchError:
    first_error = exc.errors(include_url=False, include_input=False)[0]
    location = ".".join(str(part) for part in first_error["loc"]) or "response"
    return OpenClawAiMatchError(
        f"OpenClaw returned an invalid match for {job_id}: {location}: {first_error['msg']}"
    )


def apply_match_result(
    job: dict[str, Any],
    result: dict[str, Any],
    cache_key: str,
    updated_at: str,
    *,
    profile_hash: str,
    vacancy_hash: str,
    model: str,
    prompt_version: str,
) -> dict[str, Any]:
    next_job = dict(job)
    score = result["score"]
    next_job["match"] = score
    next_job["aiMatch"] = AiMatchMetadata.model_validate(
        {
            "version": MATCHER_VERSION,
            "profileHash": profile_hash,
            "vacancyHash": vacancy_hash,
            "model": model,
            "backend": result.get("backend", result.get("source", "openclaw_codex")),
            "promptVersion": prompt_version,
            "cacheKey": cache_key,
            "source": result.get("source", "openclaw_codex"),
            "score": score,
            "updatedAt": updated_at,
        }
    ).model_dump(by_alias=True, exclude_none=True)
    return next_job


def build_cache_key(
    *,
    profile_version: str,
    vacancy_version: str,
    model: str = DEFAULT_AI_MATCH_MODEL,
    prompt_version: str = MATCH_PROMPT_VERSION,
    backend: str = "openclaw_codex",
) -> str:
    payload = json.dumps(
        {
            "version": MATCHER_VERSION,
            "promptVersion": prompt_version,
            "model": model,
            "backend": backend,
            "profileVersion": profile_version,
            "vacancyVersion": vacancy_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_job_snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_profile_hash(profile: ProfilePayload) -> str:
    return build_profile_input_hash(profile)


def build_candidate_snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        {"version": MATCHER_VERSION, "candidate": snapshot},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_cached_match_valid(
    value: Any,
    cache_key: str,
    *,
    profile_version: str,
    vacancy_version: str,
    model: str,
    backend: str,
    prompt_version: str,
) -> bool:
    try:
        match = AiMatchMetadata.model_validate(value)
    except ValidationError:
        return False

    return (
        match.version == MATCHER_VERSION
        and match.cache_key == cache_key
        and re.fullmatch(r"[a-f0-9]{64}", match.cache_key, re.IGNORECASE) is not None
        and match.provider_error is None
        and match.profile_hash == profile_version
        and re.fullmatch(r"[a-f0-9]{64}", match.profile_hash, re.IGNORECASE) is not None
        and match.vacancy_hash == vacancy_version
        and re.fullmatch(r"[a-f0-9]{64}", match.vacancy_hash, re.IGNORECASE) is not None
        and match.model == model
        and match.backend == backend
        and match.source == backend
        and match.prompt_version == prompt_version
    )


def infer_seniority(text: str) -> str:
    normalized = normalize_text(text).replace(".", " ").replace("-", " ").replace("/", " ")
    padded = f" {normalized} "
    for seniority, terms in SENIORITY_PATTERNS:
        if any(
            f" {normalize_text(term).replace('.', ' ').replace('-', ' ').replace('/', ' ')} "
            in padded
            for term in terms
        ):
            return seniority
    return ""


def summarize_experience(entries: list[Any]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        summary.append(
            {
                "title": str(entry.get("title") or "")[:160],
                "company": str(entry.get("company") or "")[:120],
                "employment_type": str(entry.get("employment_type") or "")[:80],
                "description": str(entry.get("description") or "")[:500],
            }
        )
    return summary[:12]


def summarize_education(entries: list[Any]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        summary.append(
            {
                "credential": str(entry.get("credential") or "")[:160],
                "field_of_study": str(entry.get("field_of_study") or "")[:120],
                "institution": str(entry.get("institution") or "")[:120],
            }
        )
    return summary[:8]


def parse_job_salary(job: dict[str, Any]) -> int:
    amounts = [
        parse_number(job.get("salaryAverage", "")),
        parse_number(job.get("salaryMax", "")),
        parse_number(job.get("salary", "")),
    ]
    return max(amounts)


def parse_job_salary_currency(job: dict[str, Any]) -> str:
    explicit_currency = normalize_currency(job.get("salaryCurrency") or job.get("salary_currency"))
    if explicit_currency:
        return explicit_currency

    salary_text = " ".join(
        str(job.get(field) or "") for field in ("salary", "salaryAverage", "salaryMin", "salaryMax")
    )
    return normalize_currency(salary_text)


def normalize_currency(value: Any) -> str:
    normalized = normalize_text(str(value or ""))
    raw_value = str(value or "")
    for currency, aliases in CURRENCY_ALIASES.items():
        if any(alias in raw_value for alias in aliases if alias in {"€", "£", "$"}):
            return currency
        if any(f" {normalize_text(alias)} " in f" {normalized} " for alias in aliases):
            return currency
    return ""


def parse_number(value: Any) -> int:
    if value is None:
        return 0
    raw_value = str(value)
    normalized_value = re.sub(r"(?<=\d)[\s'](?=\d{3}\b)", "", raw_value)
    matches = re.findall(r"\d+(?:[,.]\d+)?", normalized_value)
    if not matches:
        return 0
    numbers = []
    for match in matches:
        cleaned = re.sub(r"[,.]", "", match)
        try:
            amount = int(cleaned)
        except ValueError:
            continue
        if amount < 1000 and re.search(r"\d\s*k\b", raw_value, re.IGNORECASE):
            amount *= 1000
        numbers.append(amount)
    return max(numbers, default=0)


def parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value.strip() else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value) if value.strip() else []
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def parse_lines(value: str) -> list[str]:
    return [
        line.strip(" \t-•*")
        for line in value.replace("\r", "\n").replace(",", "\n").split("\n")
        if line.strip(" \t-•*")
    ]


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [item for item in value if isinstance(item, str)]
    else:
        values = []
    return list(dict.fromkeys(item.strip() for item in values if item and item.strip()))


def extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}", canonical_term(text))
    blocked = {
        "and",
        "are",
        "for",
        "from",
        "job",
        "role",
        "the",
        "this",
        "with",
        "you",
        "your",
    }
    keywords = [word for word in words if word not in blocked and len(word) > 2]
    return list(dict.fromkeys(keywords))


def canonical_term(value: str) -> str:
    normalized = normalize_text(value)
    for alias, canonical in sorted(
        SKILL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        normalized = re.sub(rf"\b{re.escape(alias)}\b", canonical, normalized)
    return normalized


def normalize_text(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./-]+", " ", ascii_value.lower())).strip()
