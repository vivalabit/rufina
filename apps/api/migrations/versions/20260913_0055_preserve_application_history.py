"""Preserve application-scoped history for the new preparation workspace.

Revision ID: 20260913_0055
Revises: 20260912_0053
Create Date: 2026-09-13 11:00:00.000000
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0055"
down_revision: str | None = "20260912_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_CONFIRMATIONS_KEY = "legacyCandidateConfirmations"


def upgrade() -> None:
    connection = op.get_bind()
    stored_applications = _stored_applications_table()
    stored_jobs = _stored_jobs_table()
    confirmations_by_application: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        sa.text(
            "SELECT application_id, question_id, requirement, response, "
            "example_text, blocking, updated_at "
            "FROM candidate_confirmations "
            "ORDER BY application_id, updated_at, question_id"
        )
    ).mappings():
        confirmations_by_application[str(row["application_id"])].append(
            {
                "questionId": str(row["question_id"]),
                "requirement": str(row["requirement"] or ""),
                "response": str(row["response"] or ""),
                "exampleText": str(row["example_text"] or ""),
                "blocking": bool(row["blocking"]),
                "updatedAt": _serialize_datetime(row["updated_at"]),
            }
        )

    application_rows = connection.execute(
        sa.select(stored_applications.c.id, stored_applications.c.data).order_by(
            stored_applications.c.id
        )
    ).mappings()
    for row in application_rows:
        application = _json_object(row["data"])
        changed = _remove_legacy_match(application)
        confirmations = confirmations_by_application.get(str(row["id"]), [])
        if confirmations:
            archived = _merge_confirmations(
                application.get(LEGACY_CONFIRMATIONS_KEY),
                confirmations,
            )
            if application.get(LEGACY_CONFIRMATIONS_KEY) != archived:
                application[LEGACY_CONFIRMATIONS_KEY] = archived
                changed = True
        if changed:
            connection.execute(
                stored_applications.update()
                .where(stored_applications.c.id == row["id"])
                .values(data=application)
            )

    # Stored vacancy snapshots used to carry presentation and preparation
    # analysis. The new workspace only accepts a freshly hydrated, authoritative
    # match, so the old embedded value must not leak back through another API.
    for row in connection.execute(
        sa.select(stored_jobs.c.owner_id, stored_jobs.c.id, stored_jobs.c.data).order_by(
            stored_jobs.c.owner_id,
            stored_jobs.c.id,
        )
    ).mappings():
        job = _json_object(row["data"])
        if "aiMatch" in job:
            job.pop("aiMatch", None)
            connection.execute(
                stored_jobs.update()
                .where(
                    stored_jobs.c.owner_id == row["owner_id"],
                    stored_jobs.c.id == row["id"],
                )
                .values(data=job)
            )


def downgrade() -> None:
    connection = op.get_bind()
    stored_applications = _stored_applications_table()
    for row in connection.execute(
        sa.select(stored_applications.c.id, stored_applications.c.data).order_by(
            stored_applications.c.id
        )
    ).mappings():
        application = _json_object(row["data"])
        if LEGACY_CONFIRMATIONS_KEY in application:
            application.pop(LEGACY_CONFIRMATIONS_KEY, None)
            connection.execute(
                stored_applications.update()
                .where(stored_applications.c.id == row["id"])
                .values(data=application)
            )
    # Embedded analytical snapshots are intentionally not reconstructed. The
    # normalized job-match records remain available to older revisions.


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): nested for key, nested in value.items()}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        if isinstance(decoded, Mapping):
            return {str(key): nested for key, nested in decoded.items()}
    return {}


def _remove_legacy_match(application: dict[str, Any]) -> bool:
    job = application.get("job")
    if not isinstance(job, Mapping) or "aiMatch" not in job:
        return False
    sanitized_job = {str(key): value for key, value in job.items()}
    sanitized_job.pop("aiMatch", None)
    application["job"] = sanitized_job
    return True


def _merge_confirmations(
    current: object,
    migrated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_question_id: dict[str, dict[str, Any]] = {}
    if isinstance(current, list):
        for value in current:
            if not isinstance(value, Mapping):
                continue
            question_id = str(value.get("questionId") or "").strip()
            if question_id:
                by_question_id[question_id] = {
                    str(key): nested for key, nested in value.items()
                }
    for confirmation in migrated:
        by_question_id[confirmation["questionId"]] = confirmation
    return [by_question_id[key] for key in sorted(by_question_id)]


def _serialize_datetime(value: object) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value or "")


def _stored_applications_table() -> sa.TableClause:
    return sa.table(
        "stored_applications",
        sa.column("id", sa.String()),
        sa.column("data", sa.JSON()),
    )


def _stored_jobs_table() -> sa.TableClause:
    return sa.table(
        "stored_jobs",
        sa.column("owner_id", sa.String()),
        sa.column("id", sa.String()),
        sa.column("data", sa.JSON()),
    )
