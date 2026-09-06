"""backfill authoritative job archive state

Revision ID: 20260906_0050
Revises: 20260831_0049
Create Date: 2026-09-06 10:00:00.000000
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0050"
down_revision: str | None = "20260831_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_object(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT owner_id, id, data, updated_at "
            "FROM stored_jobs WHERE archived_at IS NULL"
        )
    ).mappings()
    for row in rows:
        data = _json_object(row["data"])
        if data.get("archived") is not True:
            continue
        archived_at = (
            _timestamp(data.get("archivedAt"))
            or _timestamp(data.get("archived_at"))
            or _timestamp(row["updated_at"])
        )
        if archived_at is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE stored_jobs SET archived_at = :archived_at "
                "WHERE owner_id = :owner_id AND id = :id AND archived_at IS NULL"
            ),
            {
                "archived_at": archived_at,
                "owner_id": row["owner_id"],
                "id": row["id"],
            },
        )


def downgrade() -> None:
    # The JSON source remains intact in this expand migration. Clearing a value
    # here could erase an archive action made after the upgrade.
    pass
