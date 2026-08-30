from __future__ import annotations

import hashlib

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.identity import DEFAULT_OWNER_ID, get_bound_owner_id
from app.models.profile import (
    ProfilePayload,
    ProfileRecord,
    ProfileVersionRecord,
    utc_now,
)

DEFAULT_PROFILE_RECORD_ID = "default"


class StaleProfileRevisionError(RuntimeError):
    """Raised when another writer updates a profile first."""


def profile_record_id(owner_id: str) -> str:
    """Keep the legacy local ID while deriving stable IDs for other owners."""

    if owner_id == DEFAULT_OWNER_ID:
        return DEFAULT_PROFILE_RECORD_ID
    owner_digest = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:48]
    return f"profile-{owner_digest}"


def get_profile_record(
    db: Session,
    *,
    owner_id: str | None = None,
) -> ProfileRecord | None:
    resolved_owner_id = owner_id or get_bound_owner_id()
    return db.scalar(select(ProfileRecord).where(ProfileRecord.owner_id == resolved_owner_id))


def create_profile_record(
    data: dict[str, object],
    *,
    owner_id: str | None = None,
) -> ProfileRecord:
    resolved_owner_id = owner_id or get_bound_owner_id()
    return ProfileRecord(
        id=profile_record_id(resolved_owner_id),
        owner_id=resolved_owner_id,
        data=data,
        revision=1,
    )


def profile_etag(revision: int) -> str:
    return f'"{revision}"'


MEANINGFUL_PROFILE_FIELDS = (
    "name",
    "current_role",
    "desired_role",
    "location",
    "work_format",
    "headline",
    "linkedin",
    "github",
    "portfolio",
    "personal_site",
    "experience",
    "skills",
    "education",
    "job_preferences",
    "dealbreakers",
    "additional_notes",
    "documents",
    "resume_data_url",
)


def profile_completeness(profile: ProfilePayload) -> int:
    return sum(
        bool(str(getattr(profile, field_name, "")).strip())
        for field_name in MEANINGFUL_PROFILE_FIELDS
    )


def is_suspicious_profile_replacement(
    current: ProfilePayload,
    replacement: ProfilePayload,
) -> bool:
    current_score = profile_completeness(current)
    replacement_score = profile_completeness(replacement)
    return (
        current_score >= 3
        and replacement_score < current_score
        and replacement_score <= max(1, current_score // 3)
    )


def record_profile_version(
    db: Session,
    profile: ProfileRecord,
    *,
    reason: str,
) -> None:
    db.add(
        ProfileVersionRecord(
            profile_id=profile.id,
            owner_id=profile.owner_id,
            revision=profile.revision,
            data=dict(profile.data),
            reason=reason,
        )
    )


def update_profile_data(
    db: Session,
    profile: ProfileRecord,
    *,
    data: dict[str, object],
    reason: str,
) -> int:
    """Replace profile data only if its persisted revision is still current."""

    expected_revision = profile.revision
    next_revision = expected_revision + 1
    result = db.execute(
        update(ProfileRecord)
        .where(
            ProfileRecord.id == profile.id,
            ProfileRecord.owner_id == profile.owner_id,
            ProfileRecord.revision == expected_revision,
        )
        .values(
            data=data,
            revision=next_revision,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise StaleProfileRevisionError(
            f"Profile revision {expected_revision} is no longer current"
        )
    record_profile_version(db, profile, reason=reason)
    db.expire(profile, ["data", "revision", "updated_at"])
    return next_revision
