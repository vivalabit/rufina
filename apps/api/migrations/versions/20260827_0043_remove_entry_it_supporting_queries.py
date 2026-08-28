"""remove broad supporting queries from Entry IT

Revision ID: 20260827_0043
Revises: 20260827_0042
Create Date: 2026-08-27 20:00:00.000000
"""

from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0043"
down_revision: str | None = "20260827_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_LINKEDIN_CONFIG_ID = "entry-it-linkedin"
ENTRY_IT_UPDATED_AT = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)
SUPPORTING_KEYWORDS = [
    "junior IT",
    "junior software",
    "graduate IT",
    "trainee IT",
    "IT intern",
    "software intern",
    "working student IT",
    "Werkstudent IT",
    "Praktikum IT",
    "Berufseinsteiger IT",
    "stagiaire informatique",
    "tirocinio informatica",
]


def upgrade() -> None:
    _apply(include_supporting_queries=False)


def downgrade() -> None:
    _apply(include_supporting_queries=True)


def _apply(*, include_supporting_queries: bool) -> None:
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
        source["filters"], include_supporting_queries=include_supporting_queries
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
            search,
            include_supporting_queries=include_supporting_queries,
        )
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
    include_supporting_queries: bool,
) -> dict[str, Any]:
    filters = deepcopy(raw_filters) if isinstance(raw_filters, dict) else {}
    raw_queries = filters.get("linkedinQueries")
    queries = raw_queries if isinstance(raw_queries, list) else []
    profession_queries = [
        deepcopy(query)
        for query in queries
        if isinstance(query, dict) and query.get("experienceLevels")
    ]
    if include_supporting_queries:
        profession_queries.extend(
            {
                "keyword": keyword,
                "experienceLevels": [],
                "selectiveSearch": True,
            }
            for keyword in SUPPORTING_KEYWORDS
        )
        profession_queries.extend(
            {
                "keyword": keyword,
                "experienceLevels": [],
                "jobType": "Internship",
                "selectiveSearch": True,
            }
            for keyword in ("IT", "ICT")
        )
    filters["linkedinQueries"] = profession_queries
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
