"""add persistent discovered vacancy inventory

Revision ID: 20260802_0035
Revises: 20260802_0034
Create Date: 2026-08-02 18:00:00.000000
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0035"
down_revision: str | None = "20260802_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIGRATION_AT = datetime(2026, 8, 2, 18, 0, tzinfo=UTC)
IMPORTED_SOURCE_PREFIXES = (
    "linkedin",
    "swisscom",
    "jobs_ch",
    "galaxus",
    "indeed",
    "sbb",
)
RUN_METRIC_COLUMNS = (
    "jobs_discovered_new",
    "jobs_discovered_updated",
    "jobs_already_observed",
    "jobs_screening_ai_calls",
)


def upgrade() -> None:
    op.create_table(
        "discovered_vacancies",
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("vacancy_hash", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_run_id", sa.String(length=36), nullable=True),
        sa.Column(
            "availability",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("unavailable_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "availability IN ('active', 'inactive')",
            name="ck_discovered_vacancies_availability",
        ),
        sa.PrimaryKeyConstraint("owner_id", "id"),
    )
    for column in (
        "owner_id",
        "source",
        "vacancy_hash",
        "last_seen_at",
        "last_seen_run_id",
        "availability",
    ):
        op.create_index(
            op.f(f"ix_discovered_vacancies_{column}"),
            "discovered_vacancies",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_discovered_vacancies_owner_url_hash",
        "discovered_vacancies",
        ["owner_id", "url_hash"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_vacancies_owner_identity_hash",
        "discovered_vacancies",
        ["owner_id", "identity_hash"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_vacancies_owner_source_availability",
        "discovered_vacancies",
        ["owner_id", "source", "availability"],
        unique=False,
    )

    with op.batch_alter_table("job_search_runs") as batch_op:
        for column in RUN_METRIC_COLUMNS:
            batch_op.add_column(
                sa.Column(
                    column,
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )

    _backfill_imported_stored_jobs(op.get_bind())


def downgrade() -> None:
    with op.batch_alter_table("job_search_runs") as batch_op:
        for column in reversed(RUN_METRIC_COLUMNS):
            batch_op.drop_column(column)
    op.drop_table("discovered_vacancies")


def _backfill_imported_stored_jobs(connection: sa.Connection) -> None:
    stored_jobs = sa.table(
        "stored_jobs",
        sa.column("owner_id", sa.String(length=160)),
        sa.column("id", sa.String(length=160)),
        sa.column("data", sa.JSON()),
    )
    inventory = sa.table(
        "discovered_vacancies",
        sa.column("owner_id", sa.String(length=160)),
        sa.column("id", sa.String(length=160)),
        sa.column("source", sa.String(length=32)),
        sa.column("canonical_url", sa.Text()),
        sa.column("url_hash", sa.String(length=64)),
        sa.column("identity_hash", sa.String(length=64)),
        sa.column("vacancy_hash", sa.String(length=64)),
        sa.column("data", sa.JSON()),
        sa.column("first_seen_at", sa.DateTime(timezone=True)),
        sa.column("last_seen_at", sa.DateTime(timezone=True)),
        sa.column("last_seen_run_id", sa.String(length=36)),
        sa.column("availability", sa.String(length=16)),
        sa.column("unavailable_at", sa.DateTime(timezone=True)),
    )
    rows = connection.execute(
        sa.select(stored_jobs.c.owner_id, stored_jobs.c.id, stored_jobs.c.data)
    ).mappings()
    for row in rows:
        source = _source_from_job_id(row["id"])
        if source is None:
            continue
        data = _as_dict(row["data"])
        parsed_data = _stored_data_to_parsed_data(data, source=source)
        canonical_url = _canonical_url(
            str(parsed_data.get("url") or parsed_data.get("apply_url") or "")
        )
        identity = _identity(parsed_data)
        first_seen_at = _parse_datetime(data.get("addedAt")) or MIGRATION_AT
        vacancy_hash = _sha256_json(_compact_screening_data(parsed_data, job_id=row["id"]))
        connection.execute(
            inventory.insert().values(
                owner_id=row["owner_id"],
                id=row["id"],
                source=source,
                canonical_url=canonical_url,
                url_hash=_sha256_text(canonical_url) if canonical_url else "",
                identity_hash=_sha256_text(identity) if identity else "",
                vacancy_hash=vacancy_hash,
                data=parsed_data,
                first_seen_at=first_seen_at,
                last_seen_at=MIGRATION_AT,
                last_seen_run_id=None,
                availability="active",
                unavailable_at=None,
            )
        )


def _source_from_job_id(job_id: str) -> str | None:
    return next(
        (source for source in IMPORTED_SOURCE_PREFIXES if job_id.startswith(f"{source}-")),
        None,
    )


def _stored_data_to_parsed_data(
    data: dict[str, object],
    *,
    source: str,
) -> dict[str, object]:
    return {
        "source": source,
        "title": data.get("title"),
        "company": data.get("company"),
        "location": data.get("location"),
        "url": data.get("sourceUrl"),
        "apply_url": data.get("applyUrl"),
        "posted_at": data.get("posted"),
        "employment_type": data.get("type"),
        "seniority": data.get("experience"),
        "description": data.get("overview"),
        "salary": data.get("salary"),
        "salary_min": _integer_or_none(data.get("salaryMin")),
        "salary_max": _integer_or_none(data.get("salaryMax")),
        "salary_currency": None,
        "salary_unit": None,
        "raw": {},
    }


def _compact_screening_data(
    data: dict[str, object],
    *,
    job_id: str,
) -> dict[str, object]:
    compact = {
        "id": job_id,
        "title": data.get("title") or "",
        "company": data.get("company") or "",
        "location": data.get("location") or "",
        "description": data.get("description") or "",
        "employment_type": data.get("employment_type") or "",
        "seniority": data.get("seniority") or "",
        "source": data.get("source") or "",
        "posted_at": data.get("posted_at") or "",
        "salary_currency": data.get("salary_currency") or "",
    }
    if data.get("salary_min") is not None:
        compact["salary_min"] = data["salary_min"]
    if data.get("salary_max") is not None:
        compact["salary_max"] = data["salary_max"]
    return compact


def _canonical_url(value: str) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip().casefold()
    if not parts.netloc:
        return value.strip().casefold()
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            "",
            "",
        )
    )


def _identity(data: dict[str, object]) -> str:
    title = _normalize_identity_part(data.get("title"))
    company = _normalize_identity_part(data.get("company"))
    location = _normalize_identity_part(data.get("location"))
    if not title or not company:
        return ""
    return f"{title}|{company}|{location}"


def _normalize_identity_part(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _integer_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = re.sub(r"[^0-9-]", "", value)
        try:
            return int(digits) if digits else None
        except ValueError:
            return None
    return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
