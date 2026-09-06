"""remove archive state from persisted job JSON

Revision ID: 20260906_0051
Revises: 20260906_0050
Create Date: 2026-09-06 10:30:00.000000
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0051"
down_revision: str | None = "20260906_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ARCHIVE_JSON_KEYS = ("archived", "archivedAt", "archived_at")


def _json_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return dict(parsed) if isinstance(parsed, Mapping) else None
    return None


def upgrade() -> None:
    stored_jobs = sa.table(
        "stored_jobs",
        sa.column("owner_id", sa.String()),
        sa.column("id", sa.String()),
        sa.column("data", sa.JSON()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(stored_jobs.c.owner_id, stored_jobs.c.id, stored_jobs.c.data)
    ).mappings()
    for row in rows:
        data = _json_object(row["data"])
        if data is None or not any(key in data for key in ARCHIVE_JSON_KEYS):
            continue
        for key in ARCHIVE_JSON_KEYS:
            data.pop(key, None)
        connection.execute(
            stored_jobs.update()
            .where(
                stored_jobs.c.owner_id == row["owner_id"],
                stored_jobs.c.id == row["id"],
            )
            .values(data=data)
        )


def downgrade() -> None:
    # Archive state remains available in archived_at. Recreating duplicate JSON
    # state would restore the ambiguity this contract migration removes.
    pass
