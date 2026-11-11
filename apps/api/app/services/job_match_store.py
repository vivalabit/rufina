from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.ai_models import AI_SOURCES
from app.core.identity import get_bound_owner_id
from app.models.ai_match import AiMatchMetadata
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.services.ai_match import (
    MATCHER_VERSION,
    build_cache_key,
    build_job_snapshot,
    build_job_snapshot_hash,
)


def hydrate_job_data(
    db: Session,
    *,
    job_id: str,
    job_data: dict[str, Any],
    profile_hash: str,
) -> dict[str, Any]:
    next_job_data = strip_ai_match(job_data)
    vacancy_hash = build_job_snapshot_hash(
        build_job_snapshot({**next_job_data, "id": job_id})
    )
    match_record = latest_match_record(
        db,
        job_id=job_id,
        profile_hash=profile_hash,
        vacancy_hash=vacancy_hash,
    )
    if match_record:
        next_job_data["match"] = match_record.score
        next_job_data["aiMatch"] = authoritative_match_to_ai_match(match_record)
        return next_job_data

    return next_job_data


def latest_match_record(
    db: Session,
    *,
    job_id: str,
    profile_hash: str,
    vacancy_hash: str,
) -> JobMatchRecord | None:
    record = (
        db.query(JobMatchRecord)
        .filter(
            JobMatchRecord.job_id == job_id,
            JobMatchRecord.profile_hash == profile_hash,
            JobMatchRecord.vacancy_hash == vacancy_hash,
            JobMatchRecord.matcher_version == MATCHER_VERSION,
            JobMatchRecord.source.in_(AI_SOURCES),
            JobMatchRecord.provider_error.is_(None),
        )
        .order_by(JobMatchRecord.created_at.desc(), JobMatchRecord.id.desc())
        .first()
    )
    if record is None or record.source != record.backend:
        return None
    expected_cache_key = build_cache_key(
        profile_version=profile_hash,
        vacancy_version=vacancy_hash,
        model=record.model,
        backend=record.backend,
        prompt_version=record.prompt_version,
    )
    return record if record.cache_key == expected_cache_key else None


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

    ai_match = job.get("aiMatch")
    vacancy_hash = build_job_snapshot_hash(build_job_snapshot({**job_data, "id": job_id}))
    match_record = None
    if isinstance(ai_match, dict) and should_insert_match_record(
        db,
        job_id,
        profile_hash,
        vacancy_hash,
        ai_match,
    ):
        match_record = build_match_record(
            job_id=job_id,
            profile_hash=profile_hash,
            ai_match=ai_match,
        )

    if record:
        record.data = job_data
    else:
        db.add(StoredJobRecord(id=job_id, data=job_data))

    if match_record is not None:
        db.add(match_record)


def should_insert_match_record(
    db: Session,
    job_id: str,
    profile_hash: str,
    vacancy_hash: str,
    ai_match: dict[str, Any],
) -> bool:
    normalized = normalize_ai_match(ai_match)
    if normalized["version"] != MATCHER_VERSION:
        raise ValueError("AI match version is not current")
    if normalized["profileHash"] != profile_hash:
        raise ValueError("AI match profile version does not match the persisted profile version")
    if normalized["vacancyHash"] != vacancy_hash:
        raise ValueError("AI match vacancy version does not match the persisted vacancy version")
    if normalized.get("providerError"):
        raise ValueError("A failed AI match cannot be persisted as a suitability score")
    expected_cache_key = build_cache_key(
        profile_version=profile_hash,
        vacancy_version=vacancy_hash,
        model=normalized["model"],
        backend=normalized["backend"],
        prompt_version=normalized["promptVersion"],
    )
    if normalized["source"] != normalized["backend"]:
        raise ValueError("AI match source does not match its backend")
    if normalized["cacheKey"] != expected_cache_key:
        raise ValueError("AI match cache key does not match its scoring inputs")
    latest = latest_match_record(
        db,
        job_id=job_id,
        profile_hash=profile_hash,
        vacancy_hash=vacancy_hash,
    )
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
    updated_at = (
        str(ai_match.get("updatedAt") or "").strip()
        or (fallback_updated_at or datetime.now(UTC)).isoformat()
    )
    normalized = {
        "version": ai_match.get("version"),
        "profileHash": ai_match.get("profileHash"),
        "vacancyHash": ai_match.get("vacancyHash"),
        "model": ai_match.get("model"),
        "backend": ai_match.get("backend"),
        "promptVersion": ai_match.get("promptVersion"),
        "cacheKey": ai_match.get("cacheKey"),
        "source": ai_match.get("source"),
        "score": ai_match.get("score"),
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
