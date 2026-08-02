from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jobs import DiscoveredVacancyRecord
from app.models.parsers import ParsedJob
from app.services.job_screening_store import build_screening_vacancy_hash
from app.services.vacancy_search import canonical_job_url, job_identity


@dataclass(frozen=True)
class DiscoveredVacancySnapshot:
    job: ParsedJob
    job_id: str
    vacancy_hash: str
    is_new: bool
    content_changed: bool


@dataclass(frozen=True)
class DiscoveredVacancyUpsertResult:
    vacancies: list[DiscoveredVacancySnapshot] = field(default_factory=list)
    jobs_discovered_new: int = 0
    jobs_discovered_updated: int = 0
    jobs_already_observed: int = 0


def upsert_discovered_vacancies(
    db: Session,
    *,
    jobs: list[ParsedJob],
    run_id: str,
    seen_at: datetime | None = None,
    max_description_chars: int = 12_000,
) -> DiscoveredVacancyUpsertResult:
    observed_at = as_utc(seen_at or datetime.now(UTC))
    records = list(db.scalars(select(DiscoveredVacancyRecord)).all())
    by_id = {record.id: record for record in records}
    by_url_hash = {record.url_hash: record for record in records if record.url_hash}
    by_identity_hash = {record.identity_hash: record for record in records if record.identity_hash}
    snapshots: list[DiscoveredVacancySnapshot] = []
    new_count = 0
    updated_count = 0
    observed_count = 0

    for job in jobs:
        normalized_job = job.model_copy(update={"source": normalize_source(job.source)})
        proposed_id = stable_job_id(normalized_job)
        canonical_url = canonical_job_url(normalized_job.url or normalized_job.apply_url)
        url_hash = sha256_text(canonical_url) if canonical_url else ""
        identity = job_identity(normalized_job)
        identity_hash = sha256_text(identity) if identity else ""
        record = by_id.get(proposed_id)
        if record is None and url_hash:
            record = by_url_hash.get(url_hash)
        if record is None and identity_hash:
            record = by_identity_hash.get(identity_hash)

        job_id = record.id if record is not None else proposed_id
        vacancy_hash = build_screening_vacancy_hash(
            compact_screening_data(normalized_job, job_id=job_id),
            max_description_chars=max_description_chars,
        )
        snapshot_data = normalized_job.model_dump(mode="json")
        is_new = record is None
        content_changed = bool(record and record.vacancy_hash != vacancy_hash)

        if record is None:
            record = DiscoveredVacancyRecord(
                id=job_id,
                source=normalized_job.source,
                canonical_url=canonical_url,
                url_hash=url_hash,
                identity_hash=identity_hash,
                vacancy_hash=vacancy_hash,
                data=snapshot_data,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                last_seen_run_id=run_id,
                availability="active",
                unavailable_at=None,
            )
            db.add(record)
            records.append(record)
            new_count += 1
        else:
            old_url_hash = record.url_hash
            old_identity_hash = record.identity_hash
            record.canonical_url = canonical_url
            record.url_hash = url_hash
            record.identity_hash = identity_hash
            record.vacancy_hash = vacancy_hash
            record.data = snapshot_data
            record.last_seen_at = observed_at
            record.last_seen_run_id = run_id
            record.availability = "active"
            record.unavailable_at = None
            if old_url_hash and by_url_hash.get(old_url_hash) is record:
                del by_url_hash[old_url_hash]
            if old_identity_hash and by_identity_hash.get(old_identity_hash) is record:
                del by_identity_hash[old_identity_hash]
            if content_changed:
                updated_count += 1
            else:
                observed_count += 1

        by_id[record.id] = record
        if url_hash:
            by_url_hash[url_hash] = record
        if identity_hash:
            by_identity_hash[identity_hash] = record
        snapshots.append(
            DiscoveredVacancySnapshot(
                job=normalized_job,
                job_id=record.id,
                vacancy_hash=vacancy_hash,
                is_new=is_new,
                content_changed=content_changed,
            )
        )

    return DiscoveredVacancyUpsertResult(
        vacancies=snapshots,
        jobs_discovered_new=new_count,
        jobs_discovered_updated=updated_count,
        jobs_already_observed=observed_count,
    )


def mark_missing_vacancies_inactive(
    db: Session,
    *,
    source: str,
    seen_job_ids: set[str],
    unavailable_at: datetime | None = None,
) -> int:
    marked_at = as_utc(unavailable_at or datetime.now(UTC))
    records = list(
        db.scalars(
            select(DiscoveredVacancyRecord).where(
                DiscoveredVacancyRecord.source == normalize_source(source),
                DiscoveredVacancyRecord.availability == "active",
            )
        ).all()
    )
    changed = 0
    for record in records:
        if record.id in seen_job_ids:
            continue
        record.availability = "inactive"
        record.unavailable_at = marked_at
        changed += 1
    return changed


def discovered_vacancy_to_parsed_job(
    record: DiscoveredVacancyRecord,
) -> ParsedJob:
    return ParsedJob.model_validate(record.data)


def stable_job_id(job: ParsedJob) -> str:
    source = normalize_source(job.source)
    canonical_url = canonical_job_url(job.url or job.apply_url)
    identity = canonical_url or job_identity(job)
    if not identity:
        identity = hashlib.sha256(
            repr(sorted(job.model_dump(mode="json").items())).encode("utf-8")
        ).hexdigest()
    slug = re.sub(r"[^a-z0-9]+", "-", identity.casefold()).strip("-")[:96]
    return f"{source}-{slug}"


def compact_screening_data(job: ParsedJob, *, job_id: str) -> dict[str, object]:
    return {
        "id": job_id,
        "title": job.title or "",
        "company": job.company or "",
        "location": job.location or "",
        "description": job.description or "",
        "employmentType": job.employment_type or "",
        "seniority": job.seniority or "",
        "source": normalize_source(job.source),
        "postedAt": job.posted_at or "",
        "salaryMin": job.salary_min,
        "salaryMax": job.salary_max,
        "salaryCurrency": job.salary_currency or "",
    }


def normalize_source(value: str) -> str:
    return "jobs_ch" if value in {"jobs_ch", "jobs.ch"} else value.strip().casefold()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
