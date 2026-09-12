from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.identity import get_bound_owner_id
from app.models.ai_match import AiMatchMetadata
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.services.ai_match import MATCHER_VERSION


def hydrate_job_data(
    db: Session,
    *,
    job_id: str,
    job_data: dict[str, Any],
    profile_hash: str,
) -> dict[str, Any]:
    next_job_data = strip_ai_match(job_data)
    match_record = latest_match_record(db, job_id=job_id, profile_hash=profile_hash)
    if match_record:
        next_job_data["match"] = match_record.score
        next_job_data["aiMatch"] = authoritative_match_to_ai_match(match_record)
        return next_job_data

    return next_job_data


def latest_match_record(db: Session, *, job_id: str, profile_hash: str) -> JobMatchRecord | None:
    return (
        db.query(JobMatchRecord)
        .filter(
            JobMatchRecord.job_id == job_id,
            JobMatchRecord.profile_hash == profile_hash,
            JobMatchRecord.matcher_version == MATCHER_VERSION,
            JobMatchRecord.source.in_(("openclaw_codex", "openai_api", "local")),
        )
        .order_by(JobMatchRecord.created_at.desc(), JobMatchRecord.id.desc())
        .first()
    )


def authoritative_match_record(
    db: Session,
    *,
    owner_id: str,
    job_id: str,
    profile_hash: str,
    vacancy_hash: str,
    model: str,
    backend: str,
    prompt_version: str,
    matcher_version: str,
) -> JobMatchRecord | None:
    return (
        db.query(JobMatchRecord)
        .filter(
            JobMatchRecord.owner_id == owner_id,
            JobMatchRecord.job_id == job_id,
            JobMatchRecord.profile_hash == profile_hash,
            JobMatchRecord.vacancy_hash == vacancy_hash,
            JobMatchRecord.model == model,
            JobMatchRecord.backend == backend,
            JobMatchRecord.prompt_version == prompt_version,
            JobMatchRecord.matcher_version == matcher_version,
        )
        .order_by(JobMatchRecord.created_at.desc(), JobMatchRecord.id.desc())
        .first()
    )


def latest_job_match_record(db: Session, *, job_id: str) -> JobMatchRecord | None:
    return (
        db.query(JobMatchRecord)
        .filter(
            JobMatchRecord.job_id == job_id,
            JobMatchRecord.matcher_version == MATCHER_VERSION,
        )
        .order_by(JobMatchRecord.created_at.desc(), JobMatchRecord.id.desc())
        .first()
    )


def has_job_match_record(db: Session, *, job_id: str) -> bool:
    return db.query(JobMatchRecord.id).filter(JobMatchRecord.job_id == job_id).first() is not None


def authoritative_match_to_ai_match(record: JobMatchRecord) -> dict[str, Any]:
    ai_match = match_record_to_ai_match(record)
    encoded = json.dumps(
        ai_match,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **ai_match,
        "revision": record.id,
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
    }


def strip_job_state(job_data: dict[str, Any]) -> dict[str, Any]:
    next_job_data = dict(job_data)
    next_job_data.pop("archived", None)
    next_job_data.pop("archivedAt", None)
    next_job_data.pop("archived_at", None)
    return next_job_data


def strip_ai_match(job_data: dict[str, Any]) -> dict[str, Any]:
    next_job_data = strip_job_state(job_data)
    next_job_data.pop("aiMatch", None)
    return next_job_data


def persist_job_and_match(db: Session, *, job: dict[str, Any], profile_hash: str) -> None:
    job_id = str(job.get("id") or "")
    if not job_id:
        return

    job_data = strip_ai_match(job)
    record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
    if record and record.status != "active":
        return
    if record:
        record.data = job_data
    else:
        db.add(StoredJobRecord(id=job_id, data=job_data))

    ai_match = job.get("aiMatch")
    if isinstance(ai_match, dict) and should_insert_match_record(
        db, job_id, profile_hash, ai_match
    ):
        db.add(build_match_record(job_id=job_id, profile_hash=profile_hash, ai_match=ai_match))


def should_insert_match_record(
    db: Session,
    job_id: str,
    profile_hash: str,
    ai_match: dict[str, Any],
) -> bool:
    latest = latest_match_record(db, job_id=job_id, profile_hash=profile_hash)
    if not latest:
        return True

    return match_record_to_ai_match(latest) != normalize_ai_match(ai_match, latest.created_at)


def build_match_record(job_id: str, profile_hash: str, ai_match: dict[str, Any]) -> JobMatchRecord:
    normalized = normalize_ai_match(ai_match)
    return JobMatchRecord(
        id=uuid4().hex,
        job_id=job_id,
        profile_hash=profile_hash,
        vacancy_hash=normalized["vacancyHash"],
        model=normalized["model"],
        backend=normalized["backend"],
        prompt_version=normalized["promptVersion"],
        matcher_version=normalized["version"],
        cache_key=normalized["cacheKey"],
        score=normalized["score"],
        source=normalized["source"],
        provider_error=normalized.get("providerError"),
        created_at=parse_match_updated_at(ai_match) or datetime.now(UTC),
    )


def normalize_ai_match(
    ai_match: dict[str, Any],
    fallback_updated_at: datetime | None = None,
) -> dict[str, Any]:
    score = clamp_int(ai_match.get("score"), 0)
    updated_at = (
        str(ai_match.get("updatedAt") or "").strip()
        or (fallback_updated_at or datetime.now(UTC)).isoformat()
    )
    source = str(ai_match.get("source") or "openclaw_codex")
    if source not in {"openclaw_codex", "openai_api", "local"}:
        source = "local"
    backend = str(ai_match.get("backend") or source)
    if backend not in {"openclaw_codex", "openai_api", "local"}:
        backend = source
    normalized = {
        "version": str(ai_match.get("version") or MATCHER_VERSION),
        "profileHash": str(ai_match.get("profileHash") or ""),
        "vacancyHash": str(ai_match.get("vacancyHash") or ""),
        "model": str(ai_match.get("model") or ""),
        "backend": backend,
        "promptVersion": str(ai_match.get("promptVersion") or ""),
        "cacheKey": str(ai_match.get("cacheKey") or ""),
        "source": source,
        "score": score,
        "updatedAt": updated_at,
    }
    provider_error = ai_match.get("providerError")
    if provider_error:
        normalized["providerError"] = str(provider_error)[:240]
    return AiMatchMetadata.model_validate(normalized).model_dump(by_alias=True, exclude_none=True)


def match_record_to_ai_match(record: JobMatchRecord) -> dict[str, Any]:
    ai_match = {
        "version": record.matcher_version,
        "profileHash": record.profile_hash,
        "vacancyHash": record.vacancy_hash,
        "model": record.model,
        "backend": record.backend,
        "promptVersion": record.prompt_version,
        "cacheKey": record.cache_key,
        "source": record.source,
        "score": record.score,
        "updatedAt": serialize_datetime(record.created_at),
    }
    if record.provider_error:
        ai_match["providerError"] = record.provider_error
    return AiMatchMetadata.model_validate(ai_match).model_dump(by_alias=True, exclude_none=True)


def parse_match_updated_at(ai_match: dict[str, Any]) -> datetime | None:
    value = ai_match.get("updatedAt")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def clamp_int(value: Any, default: int) -> int:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, number))
