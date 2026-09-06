from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models.profile import CandidateMatchSnapshotRecord, ProfilePayload
from app.services.ai_backend import (
    AIBackend,
    AIBackendError,
    AIRequest,
    create_configured_ai_backend,
    generate_with_retries,
)
from app.services.ai_match import (
    MATCHER_VERSION,
    build_candidate_snapshot,
    build_candidate_snapshot_hash,
    build_profile_files_fingerprint,
    normalize_list,
    parse_number,
)
from app.services.profile_files import enrich_profile_with_files
from app.services.resume_import import (
    extract_json_object,
    extract_json_objects,
    extract_openclaw_text_payloads,
    summarize_openclaw_error,
)


class CandidateSnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateMatchSnapshot:
    profile_input_hash: str
    profile_hash: str
    source: str
    model: str
    data: dict[str, Any]
    provider_error: str | None = None


LIST_FIELDS = {
    "roles",
    "skills",
    "domains",
    "locations",
    "work_formats",
    "employment_types",
    "industries",
    "seniority",
    "languages",
    "company_sizes",
    "priorities",
    "no_preference",
    "dealbreakers",
}

SUMMARY_LIST_FIELDS = {"experience", "education"}
STRING_FIELDS = {
    "current_role",
    "desired_role",
    "headline",
    "salary_currency",
    "work_authorization",
    "preference_notes",
    "additional_notes",
}


def get_candidate_match_snapshot(
    db: Session,
    *,
    profile: ProfilePayload,
    settings: Settings | None = None,
    allow_openclaw: bool = False,
    strict_openclaw: bool = False,
    allow_ai: bool | None = None,
    strict_ai: bool | None = None,
) -> CandidateMatchSnapshot:
    profile = enrich_profile_with_files(db, profile)
    ai_enabled = allow_openclaw if allow_ai is None else allow_ai
    ai_required = strict_openclaw if strict_ai is None else strict_ai
    profile_input_hash = build_profile_input_hash(profile)
    expected_source = backend_snapshot_source(settings.ai_backend_mode) if settings else "local"
    expected_model = candidate_snapshot_model(settings) if settings else "local"
    existing_record = latest_snapshot_record(
        db,
        profile_input_hash=profile_input_hash,
        source=expected_source if settings else None,
        model=expected_model if settings else None,
    )
    if existing_record:
        return record_to_snapshot(existing_record)

    fallback_snapshot = empty_candidate_snapshot() if ai_required else build_candidate_snapshot(profile)
    if ai_enabled and settings and settings.openclaw_ai_match_enabled:
        try:
            facade = create_candidate_snapshot_ai_facade(settings)
            snapshot_data = facade.build(
                profile=profile,
                fallback_snapshot=fallback_snapshot,
            )
            source = backend_snapshot_source(facade.backend.name)
            model = facade.model
            provider_error = None
        except CandidateSnapshotError as exc:
            if ai_required:
                raise
            snapshot_data = fallback_snapshot
            source = "local"
            model = "local"
            provider_error = str(exc)[:240]
    elif ai_required:
        raise CandidateSnapshotError("AI candidate snapshot is required but disabled")
    else:
        snapshot_data = fallback_snapshot
        source = "local"
        model = "local"
        provider_error = None

    snapshot_data = normalize_candidate_snapshot(snapshot_data, fallback_snapshot)
    profile_hash = build_candidate_snapshot_hash(snapshot_data)
    snapshot = CandidateMatchSnapshot(
        profile_input_hash=profile_input_hash,
        profile_hash=profile_hash,
        source=source,
        model=model,
        data=snapshot_data,
        provider_error=provider_error,
    )

    if ai_enabled:
        db.add(snapshot_to_record(snapshot))

    return snapshot


def empty_candidate_snapshot() -> dict[str, Any]:
    return {
        "roles": [],
        "current_role": "",
        "desired_role": "",
        "headline": "",
        "skills": [],
        "domains": [],
        "experience": [],
        "education": [],
        "locations": [],
        "work_formats": [],
        "employment_types": [],
        "industries": [],
        "seniority": [],
        "salary_min": 0,
        "salary_currency": "",
        "work_authorization": "",
        "languages": [],
        "company_sizes": [],
        "priorities": [],
        "preference_notes": "",
        "no_preference": [],
        "dealbreakers": [],
        "additional_notes": "",
        "evidence": {
            "resume": False,
            "resume_file_name": "",
            "linkedin": False,
            "github": False,
            "portfolio": False,
            "documents": 0,
            "profile_files_hash": "",
        },
    }


def latest_snapshot_record(
    db: Session,
    *,
    profile_input_hash: str,
    source: str | None = None,
    model: str | None = None,
) -> CandidateMatchSnapshotRecord | None:
    query = db.query(CandidateMatchSnapshotRecord).filter(
        CandidateMatchSnapshotRecord.profile_input_hash == profile_input_hash,
        CandidateMatchSnapshotRecord.matcher_version == MATCHER_VERSION,
    )
    if source is not None:
        query = query.filter(CandidateMatchSnapshotRecord.source == source)
    if model is not None:
        query = query.filter(CandidateMatchSnapshotRecord.model == model)
    return (
        query
        .order_by(CandidateMatchSnapshotRecord.created_at.desc(), CandidateMatchSnapshotRecord.id.desc())
        .first()
    )


def snapshot_to_record(snapshot: CandidateMatchSnapshot) -> CandidateMatchSnapshotRecord:
    return CandidateMatchSnapshotRecord(
        id=uuid4().hex,
        profile_input_hash=snapshot.profile_input_hash,
        profile_hash=snapshot.profile_hash,
        matcher_version=MATCHER_VERSION,
        source=snapshot.source,
        model=snapshot.model,
        data=snapshot.data,
        provider_error=snapshot.provider_error,
        created_at=datetime.now(UTC),
    )


def record_to_snapshot(record: CandidateMatchSnapshotRecord) -> CandidateMatchSnapshot:
    return CandidateMatchSnapshot(
        profile_input_hash=record.profile_input_hash,
        profile_hash=record.profile_hash,
        source=record.source,
        model=record.model,
        data=record.data,
        provider_error=record.provider_error,
    )


def build_profile_input_hash(profile: ProfilePayload) -> str:
    payload = json.dumps(
        {
            "version": MATCHER_VERSION,
            "profile": profile.model_dump(),
            "profile_files_hash": build_profile_files_fingerprint(profile),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateSnapshotAIFacade:
    backend: AIBackend
    model: str
    agent_id: str
    thinking: str
    timeout_seconds: int
    max_attempts: int
    retry_backoff_seconds: float

    def build(
        self,
        *,
        profile: ProfilePayload,
        fallback_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return build_snapshot_with_ai(
            profile=profile,
            fallback_snapshot=fallback_snapshot,
            backend=self.backend,
            model=self.model,
            agent_id=self.agent_id,
            thinking=self.thinking,
            timeout_seconds=self.timeout_seconds,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
        )


def candidate_snapshot_model(settings: Settings) -> str:
    return (
        settings.openai_api_model
        if settings.ai_backend_mode == "openai_api"
        else settings.openclaw_ai_match_model
    )


def create_candidate_snapshot_ai_facade(settings: Settings) -> CandidateSnapshotAIFacade:
    return CandidateSnapshotAIFacade(
        backend=create_configured_ai_backend(
            settings,
            sync_runner=subprocess.run,
            openclaw_prompt_transport="file",
        ),
        model=candidate_snapshot_model(settings),
        agent_id=settings.openclaw_agent_id,
        thinking=settings.ai_reasoning_for(settings.openclaw_ai_match_thinking),
        timeout_seconds=settings.ai_timeout_for(
            settings.openclaw_ai_match_timeout_seconds
        ),
        max_attempts=settings.ai_max_attempts_for(1),
        retry_backoff_seconds=settings.ai_retry_backoff_for(0),
    )


def build_snapshot_with_ai(
    *,
    profile: ProfilePayload,
    fallback_snapshot: dict[str, Any],
    backend: AIBackend,
    model: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
    max_attempts: int,
    retry_backoff_seconds: float,
) -> dict[str, Any]:
    prompt = build_openclaw_candidate_snapshot_prompt(profile, fallback_snapshot)
    try:
        result = generate_with_retries(
            backend,
            AIRequest(
                prompt=prompt,
                model=model,
                agent_id=agent_id,
                thinking=thinking,
                timeout_seconds=timeout_seconds,
                structured=True,
            ),
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
    except AIBackendError as exc:
        if exc.code == "runtime_missing":
            raise CandidateSnapshotError(
                "The configured AI runtime is unavailable."
            ) from exc
        if exc.code == "timeout":
            raise CandidateSnapshotError("AI candidate snapshot timed out") from exc
        message = (
            summarize_openclaw_error(str(exc))
            if backend.name == "openclaw_codex"
            else "AI candidate snapshot failed"
        )
        raise CandidateSnapshotError(message) from exc
    except FileNotFoundError as exc:
        raise CandidateSnapshotError("The configured AI runtime is unavailable.") from exc

    snapshot = (
        result.structured_data
        if isinstance(result.structured_data, dict)
        else extract_openclaw_candidate_snapshot_payload(result.raw_response)
    )
    if isinstance(snapshot, dict) and isinstance(snapshot.get("candidate"), dict):
        snapshot = snapshot["candidate"]
    if not snapshot:
        raise CandidateSnapshotError("The AI backend did not return a candidate snapshot")
    return snapshot


def build_snapshot_with_openclaw(
    *,
    profile: ProfilePayload,
    fallback_snapshot: dict[str, Any],
    settings: Settings,
    backend: AIBackend | None = None,
) -> dict[str, Any]:
    facade = create_candidate_snapshot_ai_facade(settings)
    if backend is not None:
        facade = CandidateSnapshotAIFacade(
            backend=backend,
            model=facade.model,
            agent_id=facade.agent_id,
            thinking=facade.thinking,
            timeout_seconds=facade.timeout_seconds,
            max_attempts=facade.max_attempts,
            retry_backoff_seconds=facade.retry_backoff_seconds,
        )
    return facade.build(profile=profile, fallback_snapshot=fallback_snapshot)


def backend_snapshot_source(backend: str) -> str:
    return backend


def build_openclaw_candidate_snapshot_prompt(
    profile: ProfilePayload,
    fallback_snapshot: dict[str, Any],
) -> str:
    primary_resume = profile.runtime_primary_resume
    resume_text = (
        str(primary_resume.get("extracted_text") or "")[:50_000]
        if isinstance(primary_resume, dict)
        else ""
    )
    profile_payload = profile.model_dump(
        exclude={
            "resume_file_name",
            "resume_file_size",
            "resume_updated_at",
        }
    )
    profile_payload["avatar_url"] = "[attached]" if profile.avatar_url.startswith("data:") else profile.avatar_url
    payload = json.dumps(
        {
            "profile": profile_payload,
            "profile_files": {
                "primary_resume": runtime_profile_file_prompt_metadata(primary_resume),
                "supporting_documents": [
                    runtime_profile_file_prompt_metadata(document)
                    for document in profile.runtime_supporting_documents
                    if isinstance(document, dict)
                ],
            },
            "resume_text": resume_text,
            "fallback_snapshot": fallback_snapshot,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return (
        "Normalize this candidate for deterministic job matching.\n"
        "Return ONLY one valid JSON object, no markdown and no prose.\n"
        "Use the resume/profile evidence; do not invent facts.\n"
        "Return shape: {\"candidate\":{...}} where candidate has the same keys as fallback_snapshot.\n"
        "Keep arrays concise and deduplicated. Normalize aliases, seniority, locations, work formats, "
        "salary currency, skills, domains, priorities, dealbreakers, and evidence.\n"
        f"Input JSON:\n{payload}"
    )


def runtime_profile_file_prompt_metadata(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    metadata_fields = {
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
    }
    return {
        field: field_value
        for field, field_value in value.items()
        if field in metadata_fields
        and isinstance(field_value, (str, int, float, bool))
    }


def extract_openclaw_candidate_snapshot_payload(value: str) -> dict[str, Any]:
    for payload in extract_json_objects(value):
        candidate = payload.get("candidate")
        if isinstance(candidate, dict):
            return candidate

        if looks_like_candidate_snapshot(payload):
            return payload

        for text in extract_openclaw_text_payloads(payload):
            final_payload = extract_json_object(text)
            candidate = final_payload.get("candidate")
            if isinstance(candidate, dict):
                return candidate
            if looks_like_candidate_snapshot(final_payload):
                return final_payload

        result = payload.get("result")
        if not isinstance(result, dict):
            continue

        for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
            final_text = result.get(key)
            if isinstance(final_text, str):
                final_payload = extract_json_object(final_text)
                candidate = final_payload.get("candidate")
                if isinstance(candidate, dict):
                    return candidate
                if looks_like_candidate_snapshot(final_payload):
                    return final_payload

    return {}


def looks_like_candidate_snapshot(value: dict[str, Any]) -> bool:
    return isinstance(value.get("roles"), list) and isinstance(value.get("skills"), list)


def normalize_candidate_snapshot(
    snapshot: dict[str, Any],
    fallback_snapshot: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(fallback_snapshot)

    for field in LIST_FIELDS:
        if field in snapshot:
            normalized[field] = normalize_list(snapshot[field])

    for field in SUMMARY_LIST_FIELDS:
        if isinstance(snapshot.get(field), list):
            normalized[field] = [
                item
                for item in snapshot[field]
                if isinstance(item, dict)
            ][:12]

    for field in STRING_FIELDS:
        if field in snapshot:
            normalized[field] = str(snapshot.get(field) or "").strip()[:500]

    if "salary_min" in snapshot:
        normalized["salary_min"] = parse_number(snapshot.get("salary_min"))

    evidence = snapshot.get("evidence")
    if isinstance(evidence, dict):
        normalized_evidence = dict(fallback_snapshot.get("evidence") or {})
        normalized_evidence.update(
            {
                key: value
                for key, value in evidence.items()
                if isinstance(key, str) and isinstance(value, (bool, int, str))
            }
        )
        normalized["evidence"] = normalized_evidence

    return normalized
