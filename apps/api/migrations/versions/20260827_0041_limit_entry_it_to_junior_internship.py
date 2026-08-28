"""limit Entry IT LinkedIn professions to junior and internship levels

Revision ID: 20260827_0041
Revises: 20260827_0040
Create Date: 2026-08-27 19:00:00.000000
"""

from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0041"
down_revision: str | None = "20260827_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_LINKEDIN_CONFIG_ID = "entry-it-linkedin"
ENTRY_IT_UPDATED_AT = datetime(2026, 8, 27, 19, 0, tzinfo=UTC)
JUNIOR_INTERNSHIP_LEVELS = ["Entry level", "Internship"]
PREVIOUS_LEVELS = ["Entry level", "Internship", "Associate"]


def upgrade() -> None:
    _apply(
        experience_levels=JUNIOR_INTERNSHIP_LEVELS,
        allowed_seniority=["intern", "entry", "junior"],
    )


def downgrade() -> None:
    _apply(
        experience_levels=PREVIOUS_LEVELS,
        allowed_seniority=["intern", "entry", "junior", "associate"],
    )


def _apply(
    *,
    experience_levels: list[str],
    allowed_seniority: list[str],
) -> None:
    connection = op.get_bind()
    source_configs = _source_configs_table()
    source = connection.execute(
        sa.select(
            source_configs.c.config_id,
            source_configs.c.filters,
            source_configs.c.owner_id,
        ).where(source_configs.c.id == ENTRY_IT_LINKEDIN_CONFIG_ID)
    ).mappings().first()
    if source is None:
        return

    source_filters = _updated_search_filters(
        source["filters"], experience_levels=experience_levels
    )
    connection.execute(
        source_configs.update()
        .where(source_configs.c.id == ENTRY_IT_LINKEDIN_CONFIG_ID)
        .values(filters=source_filters, updated_at=ENTRY_IT_UPDATED_AT)
    )

    configs = _configs_table()
    raw_filters = connection.execute(
        sa.select(configs.c.filters).where(
            configs.c.id == source["config_id"],
            configs.c.owner_id == source["owner_id"],
        )
    ).scalar_one_or_none()
    if not isinstance(raw_filters, dict):
        return

    filters = deepcopy(raw_filters)
    search = filters.get("search")
    if isinstance(search, dict):
        filters["search"] = _updated_search_filters(
            search, experience_levels=experience_levels
        )
    screening = filters.get("screening")
    if isinstance(screening, dict):
        screening["allowedSeniority"] = deepcopy(allowed_seniority)
    connection.execute(
        configs.update()
        .where(
            configs.c.id == source["config_id"],
            configs.c.owner_id == source["owner_id"],
        )
        .values(filters=filters, updated_at=ENTRY_IT_UPDATED_AT)
    )


def _updated_search_filters(
    raw_filters: Any,
    *,
    experience_levels: list[str],
) -> dict[str, Any]:
    filters = deepcopy(raw_filters) if isinstance(raw_filters, dict) else {}
    queries = filters.get("linkedinQueries")
    if not isinstance(queries, list):
        return filters

    for query in queries:
        if not isinstance(query, dict):
            continue
        current_levels = query.get("experienceLevels")
        if isinstance(current_levels, list) and current_levels:
            query["experienceLevels"] = deepcopy(experience_levels)
    return filters


def _source_configs_table() -> sa.TableClause:
    return sa.table(
        "job_source_configs",
        sa.column("id", sa.String(length=36)),
        sa.column("config_id", sa.String(length=36)),
        sa.column("filters", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("owner_id", sa.String(length=160)),
    )


def _configs_table() -> sa.TableClause:
    return sa.table(
        "job_search_configs",
        sa.column("id", sa.String(length=36)),
        sa.column("filters", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("owner_id", sa.String(length=160)),
    )
