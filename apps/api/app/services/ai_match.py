from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from app.core.settings import Settings
from app.models.profile import ProfilePayload
from app.services.ai_backend import (
    AIBackend,
    AIBackendError,
    AIRequest,
    OpenClawCodexBackend,
    create_configured_ai_backend,
)
from app.services.experience_evidence import build_atomic_experience_evidence
from app.services.resume_import import (
    extract_json_objects,
    extract_openclaw_text_payloads,
    summarize_openclaw_error,
)

MATCHER_VERSION = "ai-match-v3"
MATCH_PROMPT_VERSION = "ai-match-prompt-v6"
DEFAULT_AI_MATCH_MODEL = "openai/gpt-5.6-terra"
DEFAULT_AI_MATCH_MAX_ATTEMPTS = 2
MAX_AI_MATCH_TEXT_LENGTH = 500
MAX_REASON_COUNT = 3
MAX_GAP_COUNT = 3
MAX_EVIDENCE_MATRIX_COUNT = 8
MAX_CLARIFICATION_QUESTION_COUNT = 3
JOB_ADDED_AT_FIELDS = ("addedAt", "importedAt", "createdAt", "created_at")

WEIGHTS = {
    "role_fit": 20,
    "skills_fit": 30,
    "experience_fit": 15,
    "preferences_fit": 15,
    "constraints_fit": 10,
    "industry_fit": 5,
    "evidence_fit": 5,
}

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
EVIDENCE_IMPORTANCE_ALIASES = {
    "required": "required",
    "mandatory": "required",
    "must have": "required",
    "essential": "required",
    "prerequisite": "required",
    "erforderlich": "required",
    "zwingend": "required",
    "pflicht": "required",
    "preferred": "preferred",
    "optional": "preferred",
    "nice to have": "preferred",
    "desired": "preferred",
    "bonus": "preferred",
    "bevorzugt": "preferred",
    "wünschenswert": "preferred",
    "von vorteil": "preferred",
}
SENIORITY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lead", ("principal", "staff", "lead", "manager", "head", "director", "vp", "chief", "architect")),
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
OptionalEvidenceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_AI_MATCH_TEXT_LENGTH),
]


class StrictAiMatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class AiMatchBreakdown(StrictAiMatchModel):
    role_fit: int = Field(ge=0, le=WEIGHTS["role_fit"])
    skills_fit: int = Field(ge=0, le=WEIGHTS["skills_fit"])
    experience_fit: int = Field(ge=0, le=WEIGHTS["experience_fit"])
    preferences_fit: int = Field(ge=0, le=WEIGHTS["preferences_fit"])
    constraints_fit: int = Field(ge=0, le=WEIGHTS["constraints_fit"])
    industry_fit: int = Field(ge=0, le=WEIGHTS["industry_fit"])
    evidence_fit: int = Field(ge=0, le=WEIGHTS["evidence_fit"])


class AiMatchEvidence(StrictAiMatchModel):
    requirement: StrictText
    importance: Literal["required", "preferred"]
    status: Literal["verified", "transferable", "needs_confirmation", "missing"]
    evidence: OptionalEvidenceText
    action: StrictText
    source_ids: list[StrictText] = Field(alias="sourceIds", max_length=8)

    @model_validator(mode="after")
    def require_evidence_for_supported_status(self) -> "AiMatchEvidence":
        if self.status in {"verified", "transferable"} and not self.evidence:
            raise ValueError(f"evidence is required when status is {self.status}")
        if self.status in {"verified", "transferable"} and not self.source_ids:
            raise ValueError(f"sourceIds are required when status is {self.status}")
        if self.status in {"needs_confirmation", "missing"} and self.source_ids:
            raise ValueError(f"sourceIds must be empty when status is {self.status}")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("sourceIds must not contain duplicates")
        return self


class AiMatchClarificationQuestion(StrictAiMatchModel):
    id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=80,
            pattern=r"^[a-z0-9][a-z0-9_-]*$",
        ),
    ]
    requirement: StrictText
    question: StrictText
    why: StrictText
    claim_if_confirmed: StrictText = Field(alias="claimIfConfirmed")
    blocking: bool


class AiMatchResumePlan(StrictAiMatchModel):
    target_headline: StrictText = Field(alias="targetHeadline")
    summary_focus: StrictText = Field(alias="summaryFocus")
    evidence_to_lead: list[StrictText] = Field(alias="evidenceToLead", max_length=4)
    bullet_strategy: list[StrictText] = Field(alias="bulletStrategy", min_length=1, max_length=4)


class AiMatchCoverLetterPlan(StrictAiMatchModel):
    opening_angle: StrictText = Field(alias="openingAngle")
    proof_points: list[StrictText] = Field(alias="proofPoints", max_length=3)
    motivation_angle: StrictText = Field(alias="motivationAngle")


class AiMatchApplicationGuide(StrictAiMatchModel):
    language: Literal["English", "German"]
    positioning: StrictText
    readiness: Literal["ready", "needs_confirmation", "weak_fit"]
    role_mission: StrictText = Field(alias="roleMission")
    hiring_priorities: list[StrictText] = Field(alias="hiringPriorities", min_length=1, max_length=4)
    must_have: list[StrictText] = Field(alias="mustHave", max_length=6)
    nice_to_have: list[StrictText] = Field(alias="niceToHave", max_length=5)
    hard_constraints: list[StrictText] = Field(alias="hardConstraints", max_length=4)
    evidence_matrix: list[AiMatchEvidence] = Field(alias="evidenceMatrix", min_length=1, max_length=MAX_EVIDENCE_MATRIX_COUNT)
    clarification_questions: list[AiMatchClarificationQuestion] = Field(
        alias="clarificationQuestions",
        min_length=MAX_CLARIFICATION_QUESTION_COUNT,
        max_length=MAX_CLARIFICATION_QUESTION_COUNT,
    )
    resume_plan: AiMatchResumePlan = Field(alias="resumePlan")
    cover_letter_plan: AiMatchCoverLetterPlan = Field(alias="coverLetterPlan")
    cv_improvements: list[StrictText] = Field(alias="cvImprovements", max_length=4)
    cover_letter_strategy: list[StrictText] = Field(alias="coverLetterStrategy", max_length=3)
    risks: list[StrictText] = Field(max_length=3)
    keywords: list[StrictText] = Field(max_length=8)
    application_questions: list[StrictText] = Field(alias="applicationQuestions", max_length=3)
    final_checklist: list[StrictText] = Field(alias="finalChecklist", min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_readiness_consistency(self) -> "AiMatchApplicationGuide":
        question_ids = [question.id for question in self.clarification_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("clarification question IDs must be unique")

        unresolved = any(
            evidence.status in {"needs_confirmation", "missing"}
            for evidence in self.evidence_matrix
        )
        if not all(question.blocking for question in self.clarification_questions):
            raise ValueError("all document improvement questions must be blocking")
        if self.readiness == "ready" and unresolved:
            raise ValueError("ready analysis cannot contain unresolved evidence")
        if self.readiness == "needs_confirmation" and not unresolved:
            raise ValueError(
                "needs_confirmation requires unresolved evidence"
            )
        return self


class AiMatchResult(StrictAiMatchModel):
    id: StrictText
    score: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]
    breakdown: AiMatchBreakdown
    reasons: list[StrictText] = Field(min_length=1, max_length=MAX_REASON_COUNT)
    gaps: list[StrictText] = Field(max_length=MAX_GAP_COUNT)
    application_guide: AiMatchApplicationGuide = Field(alias="applicationGuide")

    @model_validator(mode="after")
    def validate_score_consistency(self) -> "AiMatchResult":
        breakdown_total = sum(self.breakdown.model_dump().values())
        if abs(self.score - breakdown_total) > 20:
            raise ValueError("score differs from the breakdown total by more than 20 points")
        return self


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
            backend=self.backend,
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
    backend: AIBackend | None = None,
) -> list[dict[str, Any]]:
    if not openclaw_enabled:
        raise AiMatchError("AI vacancy matching is required but disabled")
    if openclaw_max_jobs <= 0:
        raise AiMatchError("AI vacancy matching requires a positive job batch size")

    profile_snapshot = candidate_snapshot or build_candidate_snapshot(profile)
    backend_source = backend.name if backend is not None else "openclaw_codex"
    evidence_catalog = build_ai_match_evidence_catalog(profile)
    ordered_jobs: list[dict[str, Any] | tuple[dict[str, Any], dict[str, Any], str]] = []
    now = datetime.now(UTC).isoformat()
    jobs_to_score: list[tuple[dict[str, Any], dict[str, Any], str]] = []

    for job in jobs:
        if not isinstance(job, dict):
            continue

        job_snapshot = build_job_snapshot(job)
        cache_key = build_cache_key(
            profile_snapshot,
            job_snapshot,
            model=model,
            prompt_version=MATCH_PROMPT_VERSION,
            evidence_sources=list(evidence_catalog.values()),
            backend=backend_source,
        )
        cached_match = job.get("aiMatch")
        if not force and is_cached_match_valid(cached_match, cache_key) and cached_match.get("source") == backend_source:
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
                    evidence_sources=list(evidence_catalog.values()),
                    correction_feedback=correction_feedback,
                    backend=backend,
                )
                openclaw_results = validate_openclaw_batch(
                    openclaw_results,
                    expected_job_ids=[job["id"] for job in chunk_snapshots],
                    evidence_catalog=evidence_catalog,
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

    scored_ids = {job_snapshot["id"] for _, job_snapshot, _ in jobs_to_score}
    missing_ids = sorted(scored_ids - set(by_id))
    if missing_ids:
        raise AiMatchError(
            f"AI backend did not return matches for: {', '.join(missing_ids[:8])}"
        )

    return [
        item
        if isinstance(item, dict)
        else apply_match_result(
            item[0],
            normalize_openclaw_result(
                by_id[item[1]["id"]],
                item[0],
                evidence_catalog=evidence_catalog,
                backend_source=backend_source,
            ),
            item[2],
            now,
            profile_hash=build_candidate_snapshot_hash(profile_snapshot),
            vacancy_hash=build_job_snapshot_hash(item[1]),
            model=model,
            prompt_version=MATCH_PROMPT_VERSION,
        )
        for item in ordered_jobs
    ]


def build_candidate_snapshot(profile: ProfilePayload) -> dict[str, Any]:
    preferences = parse_json_object(profile.job_preferences)
    experience_entries = parse_json_list(profile.experience)
    education_entries = parse_json_list(profile.education)
    documents = parse_json_list(profile.documents)
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
        "locations": normalize_list([profile.location, *normalize_list(preferences.get("locations", []))]),
        "work_formats": normalize_list([profile.work_format, *normalize_list(preferences.get("work_formats", []))]),
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
            "resume": bool(profile.resume_file_name and profile.resume_data_url),
            "resume_file_name": profile.resume_file_name,
            "linkedin": bool(profile.linkedin),
            "github": bool(profile.github),
            "portfolio": bool(profile.portfolio or profile.personal_site),
            "documents": len(documents),
        },
    }


def build_ai_match_evidence_catalog(profile: ProfilePayload) -> dict[str, dict[str, str]]:
    field_labels = {
        "current_role": "Profile · current role",
        "desired_role": "Profile · desired role",
        "location": "Profile · location",
        "work_format": "Profile · work format",
        "headline": "Profile · headline",
        "skills": "Profile · skills",
        "education": "Profile · education",
        "job_preferences": "Profile · job preferences",
        "dealbreakers": "Profile · dealbreakers",
        "additional_notes": "Profile · additional notes",
    }
    catalog = {
        f"profile:{field}": {
            "id": f"profile:{field}",
            "label": label,
            "excerpt": str(getattr(profile, field) or "").strip()[:2_000],
        }
        for field, label in field_labels.items()
        if str(getattr(profile, field) or "").strip()
    }
    for claim in build_atomic_experience_evidence(profile.experience):
        claim_type = str(claim.get("claimType") or "experience").replace("_", " ")
        source_id = claim["id"]
        catalog[source_id] = {
            "id": source_id,
            "label": f"Experience · {claim_type}",
            "excerpt": claim["text"][:2_000],
        }
    return catalog


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
    text = " ".join([title, company, location, employment_type, experience, overview, *requirements, *responsibilities, *skills])

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
    evidence_sources: list[dict[str, str]] | None = None,
    correction_feedback: str | None = None,
    backend: AIBackend | None = None,
) -> list[dict[str, Any]]:
    if not jobs:
        return []

    prompt = build_openclaw_ai_match_prompt(
        profile_snapshot,
        jobs,
        evidence_sources=evidence_sources or [],
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
    payload = normalize_openclaw_ai_match_payload(raw_payload)
    try:
        validated = AiMatchPayload.model_validate(payload)
    except ValidationError as exc:
        raise invalid_openclaw_response(exc) from exc
    return [match.model_dump(by_alias=True) for match in validated.matches]


def build_openclaw_ai_match_prompt(
    profile_snapshot: dict[str, Any],
    jobs: list[dict[str, Any]],
    *,
    evidence_sources: list[dict[str, str]] | None = None,
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
            "candidateEvidenceSources": evidence_sources or [],
            "jobs": compact_jobs,
            "breakdownMaxScores": WEIGHTS,
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
        "You score job fit for a personal job search app.\n"
        "Return ONLY one valid JSON object, no markdown and no prose.\n"
        "Every field shown in the JSON shape is required. Use [] for empty lists. "
        "Do not add fields.\n"
        "Keep every enum token exactly as shown in the JSON shape, in English, even when the "
        "applicationGuide prose is German.\n"
        f"{correction_instruction}"
        f"Keep every string at most {MAX_AI_MATCH_TEXT_LENGTH} characters. Evidence must be a short "
        f"exact excerpt of at most {MAX_AI_MATCH_TEXT_LENGTH} characters, never the whole source.\n"
        "Use only the provided snapshots. Do not invent missing evidence.\n"
        "For every job, set score as your expert judgment from 0 to 100.\n"
        "Score is the final AI assessment, not an arithmetic sum of breakdown values.\n"
        "Breakdown is a structured explanation with category scores capped by breakdownMaxScores; "
        "it must be internally consistent, but it is not the formula for score. The score must be "
        "within 20 points of the breakdown total.\n"
        "Apply caps: hard dealbreaker max 30, salary below candidate minimum max 50, "
        "work authorization mismatch max 35, major seniority mismatch max 45.\n"
        "JSON shape:\n"
        '{"matches":[{"id":"job id","score":0,"confidence":"low|medium|high",'
        '"breakdown":{"role_fit":0,"skills_fit":0,"experience_fit":0,"preferences_fit":0,'
        '"constraints_fit":0,"industry_fit":0,"evidence_fit":0},'
        '"reasons":["max 3 short reasons"],"gaps":["max 3 short gaps"],'
        '"applicationGuide":{"language":"English|German","positioning":"one short sentence",'
        '"readiness":"ready|needs_confirmation|weak_fit",'
        '"roleMission":"one sentence explaining what problem this hire must solve",'
        '"hiringPriorities":["max 4 ranked outcomes"],'
        '"mustHave":["max 6 mandatory requirements"],"niceToHave":["max 5 preferred requirements"],'
        '"hardConstraints":["max 4 location, language, authorization, education or schedule constraints"],'
        '"evidenceMatrix":[{"requirement":"short requirement","importance":"required|preferred",'
        '"status":"verified|transferable|needs_confirmation|missing",'
        '"evidence":"exact source excerpt or empty string","action":"honest application action",'
        '"sourceIds":["exact candidateEvidenceSources id"]}],'
        '"clarificationQuestions":[{"id":"stable short id","requirement":"skill or requirement",'
        '"question":"one focused question asking for useful missing detail","why":"how the answer improves the CV and/or cover letter",'
        '"claimIfConfirmed":"exact claim that may be used only after confirmation","blocking":true}],'
        '"resumePlan":{"targetHeadline":"truthful target headline","summaryFocus":"one sentence",'
        '"evidenceToLead":["max 4 verified proof points"],"bulletStrategy":["max 4 concrete rewrites"]},'
        '"coverLetterPlan":{"openingAngle":"specific opening angle","proofPoints":["max 3 verified proof points"],'
        '"motivationAngle":"company or role-specific motivation without invented facts"},'
        '"cvImprovements":["max 4 specific changes"],'
        '"coverLetterStrategy":["max 3 specific points"],"risks":["max 3 risks or unsupported claims"],'
        '"keywords":["max 8 short vacancy terms supported by candidate evidence"],'
        '"applicationQuestions":["max 3 likely questions with truthful answer points"],'
        '"finalChecklist":["max 4 concrete checks"]}}]}\n'
        "First identify the vacancy's core mission and separate mandatory requirements from preferences "
        "and hard constraints. Then map each important requirement to exact candidate evidence. "
        "Use needs_confirmation only when the requirement matters and the candidate plausibly may have "
        "the skill, but the provided evidence is insufficient. For example, if a data role requires Excel "
        "and the profile mentions reporting but not Excel, ask which concrete Excel features were used. "
        "Always return exactly three ranked, blocking clarificationQuestions whose truthful answers would "
        "most improve the tailored CV, the cover letter, or both. Questions may close an important evidence "
        "gap or strengthen existing evidence with a concrete project, scope, outcome, metric, technology, "
        "responsibility, motivation, or transferable example. Prefer details that can become strong, "
        "specific document content. Ask one thing per question; never combine eligibility, availability, "
        "skills, or examples in a multi-part question. Never ask for a fact already present, generic "
        "self-assessment, or information that cannot improve either document. Set blocking=true for all "
        "three questions. Rank the highest-impact question first. "
        "Detect whether each vacancy is written primarily in English or German. Write every applicationGuide "
        "value in that vacancy language. Make all advice specific enough to reuse directly when tailoring the candidate's CV and "
        "cover letter. Creativity is allowed in positioning and wording, never in facts. Never suggest an "
        "unsupported claim, metric, skill, certification, title, or experience. Keywords must either be "
        "supported or explicitly marked needs_confirmation in evidenceMatrix.\n"
        "For verified or transferable evidence, copy an exact excerpt from candidateEvidenceSources "
        "into evidence and cite its exact id in sourceIds. Use an empty sourceIds list for "
        "needs_confirmation and missing. Never mark evidence verified from the vacancy text alone.\n"
        "Set readiness=ready only when every evidenceMatrix item is verified or transferable. "
        "Set readiness=needs_confirmation when important evidence remains unresolved. Set "
        "readiness=weak_fit when the verified fit is too weak to recommend normal tailoring. "
        "The three document-improvement questions are required for every readiness value and do not by "
        "themselves determine readiness.\n"
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


def normalize_openclaw_ai_match_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    """Repair safe, deterministic model-output variations before strict validation."""
    matches = payload.get("matches")
    if not isinstance(matches, list):
        return payload

    for match in matches:
        if not isinstance(match, dict):
            continue
        guide = match.get("applicationGuide")
        if not isinstance(guide, dict):
            continue
        evidence_matrix = guide.get("evidenceMatrix")
        if not isinstance(evidence_matrix, list):
            continue
        for item in evidence_matrix:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence")
            if isinstance(evidence, str) and len(evidence.strip()) > MAX_AI_MATCH_TEXT_LENGTH:
                item["evidence"] = evidence.strip()[:MAX_AI_MATCH_TEXT_LENGTH]
            importance = item.get("importance")
            if isinstance(importance, str):
                normalized_importance = " ".join(
                    importance.strip().casefold().replace("_", " ").replace("-", " ").split()
                )
                canonical_importance = EVIDENCE_IMPORTANCE_ALIASES.get(normalized_importance)
                if canonical_importance:
                    item["importance"] = canonical_importance

    return payload


def normalize_openclaw_result(
    result: dict[str, Any],
    current_job: dict[str, Any],
    *,
    evidence_catalog: dict[str, dict[str, str]] | None = None,
    backend_source: str = "openclaw_codex",
) -> dict[str, Any]:
    fallback = current_job.get("aiMatch", {}) if isinstance(current_job.get("aiMatch"), dict) else {}
    validated = validate_openclaw_result(result, current_job)
    normalized = validated.model_dump(by_alias=True)
    guide = normalized["applicationGuide"]
    for item in guide["evidenceMatrix"]:
        item["sources"] = [
            evidence_catalog[source_id]
            for source_id in item["sourceIds"]
            if evidence_catalog and source_id in evidence_catalog
        ]
    return {
        "score": normalized["score"],
        "source": backend_source,
        "backend": backend_source,
        "confidence": normalized["confidence"],
        "breakdown": normalized["breakdown"],
        "reasons": normalized["reasons"],
        "gaps": normalized["gaps"],
        "applicationGuide": guide,
        "heuristicScore": clamp_round(fallback.get("heuristicScore", current_job.get("match", 0))),
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
    evidence_catalog: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(results, list) or any(not isinstance(result, dict) for result in results):
        raise OpenClawAiMatchError("OpenClaw returned an invalid matches array")
    validated = [
        validate_openclaw_result(result, {"id": result.get("id")})
        for result in results
    ]
    if evidence_catalog is not None:
        validate_ai_match_evidence_sources(validated, evidence_catalog)
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


def validate_ai_match_evidence_sources(
    results: list[OpenClawAiMatchResult],
    evidence_catalog: dict[str, dict[str, str]],
) -> None:
    for result in results:
        for evidence in result.application_guide.evidence_matrix:
            if evidence.status not in {"verified", "transferable"}:
                continue
            unknown_ids = [source_id for source_id in evidence.source_ids if source_id not in evidence_catalog]
            if unknown_ids:
                raise OpenClawAiMatchError(
                    f"OpenClaw returned unknown evidence source IDs for {result.id}: "
                    f"{', '.join(unknown_ids)}"
                )
            normalized_excerpt = " ".join(evidence.evidence.casefold().split())
            source_texts = [
                " ".join(evidence_catalog[source_id]["excerpt"].casefold().split())
                for source_id in evidence.source_ids
            ]
            if not any(normalized_excerpt in source_text for source_text in source_texts):
                raise OpenClawAiMatchError(
                    f"OpenClaw evidence excerpt for {result.id} is not present in its cited sources"
                )


def invalid_openclaw_response(
    exc: ValidationError,
    *,
    job_id: str = "payload",
) -> OpenClawAiMatchError:
    first_error = exc.errors(include_url=False, include_input=False)[0]
    location = ".".join(str(part) for part in first_error["loc"]) or "response"
    return OpenClawAiMatchError(
        f"OpenClaw returned an invalid match for {job_id}: "
        f"{location}: {first_error['msg']}"
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
    score = clamp_round(result.get("score", next_job.get("match", 0)))
    next_job["match"] = score
    next_job["aiMatch"] = {
        "version": MATCHER_VERSION,
        "profileHash": profile_hash,
        "vacancyHash": vacancy_hash,
        "model": model,
        "backend": result.get("backend", result.get("source", "openclaw_codex")),
        "promptVersion": prompt_version,
        "cacheKey": cache_key,
        "source": result.get("source", "openclaw_codex"),
        "score": score,
        "confidence": normalize_confidence(result.get("confidence", "low")),
        "breakdown": result.get("breakdown", {}),
        "reasons": normalize_string_list(result.get("reasons"), MAX_REASON_COUNT),
        "gaps": normalize_string_list(result.get("gaps"), MAX_GAP_COUNT),
        "applicationGuide": result["applicationGuide"],
        "heuristicScore": clamp_round(result.get("heuristicScore", score)),
        "updatedAt": updated_at,
    }
    return next_job


def detect_job_language(job: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(job.get("title") or ""),
            str(job.get("overview") or ""),
            *normalize_list(job.get("requirements", [])),
            *normalize_list(job.get("responsibilities", [])),
        ]
    ).lower()
    german_markers = (
        " der ",
        " die ",
        " das ",
        " und ",
        " oder ",
        " mit ",
        " für ",
        " bei ",
        " wir ",
        " sie ",
        " deine ",
        " ihr ",
        " aufgaben",
        "anforderungen",
        "erfahrung",
        "kenntnisse",
        "bewerbung",
        "deutsch",
    )
    english_markers = (
        " the ",
        " and ",
        " or ",
        " with ",
        " for ",
        " we ",
        " you ",
        " your ",
        "responsibilities",
        "requirements",
        "experience",
        "skills",
        "application",
    )
    padded = f" {text} "
    german_score = sum(padded.count(marker) for marker in german_markers)
    english_score = sum(padded.count(marker) for marker in english_markers)
    return "German" if german_score > english_score else "English"


def build_cache_key(
    profile_snapshot: dict[str, Any],
    job_snapshot: dict[str, Any],
    *,
    model: str = DEFAULT_AI_MATCH_MODEL,
    prompt_version: str = MATCH_PROMPT_VERSION,
    evidence_sources: list[dict[str, str]] | None = None,
    backend: str = "openclaw_codex",
) -> str:
    payload = json.dumps(
        {
            "version": MATCHER_VERSION,
            "promptVersion": prompt_version,
            "model": model,
            "backend": backend,
            "candidate": profile_snapshot,
            "candidateEvidenceSources": evidence_sources or [],
            "job": job_snapshot,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_job_snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_profile_hash(profile: ProfilePayload) -> str:
    return build_candidate_snapshot_hash(build_candidate_snapshot(profile))


def build_candidate_snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        {"version": MATCHER_VERSION, "candidate": snapshot},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_cached_match_valid(value: Any, cache_key: str) -> bool:
    application_guide = value.get("applicationGuide") if isinstance(value, dict) else None
    return (
        isinstance(value, dict)
        and value.get("version") == MATCHER_VERSION
        and value.get("cacheKey") == cache_key
        and isinstance(value.get("score"), int)
        and isinstance(application_guide, dict)
        and application_guide.get("language") in {"English", "German"}
        and bool(str(application_guide.get("positioning") or "").strip())
    )


def infer_seniority(text: str) -> str:
    normalized = normalize_text(text).replace(".", " ").replace("-", " ").replace("/", " ")
    padded = f" {normalized} "
    for seniority, terms in SENIORITY_PATTERNS:
        if any(f" {normalize_text(term).replace('.', ' ').replace('-', ' ').replace('/', ' ')} " in padded for term in terms):
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
        str(job.get(field) or "")
        for field in ("salary", "salaryAverage", "salaryMin", "salaryMax")
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


def normalize_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:180] for item in value if str(item).strip()][:limit]


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
    for alias, canonical in sorted(SKILL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"\b{re.escape(alias)}\b", canonical, normalized)
    return normalized


def normalize_text(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./-]+", " ", ascii_value.lower())).strip()


def normalize_confidence(value: Any) -> str:
    return str(value).lower() if str(value).lower() in {"low", "medium", "high"} else "low"


def clamp_round(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, round(number)))
