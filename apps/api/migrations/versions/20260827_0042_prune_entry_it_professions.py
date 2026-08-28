"""keep only the selected Entry IT professions

Revision ID: 20260827_0042
Revises: 20260827_0041
Create Date: 2026-08-27 19:30:00.000000
"""

from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0042"
down_revision: str | None = "20260827_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_LINKEDIN_CONFIG_ID = "entry-it-linkedin"
ENTRY_IT_UPDATED_AT = datetime(2026, 8, 27, 19, 30, tzinfo=UTC)
ENTRY_LEVELS = ["Entry level", "Internship"]

SELECTED_PROFESSIONS = [
    "software engineer",
    "softwareentwickler",
    "applikationsentwickler",
    "backend developer",
    "full stack developer",
    "python developer",
    "data engineer",
    "data analyst",
    "data scientist",
    "machine learning engineer",
    "AI engineer",
    "QA engineer",
    "test engineer",
    "informatiker",
]
SELECTED_TARGET_ROLES = [
    "Software Engineer",
    "Softwareentwickler",
    "Applikationsentwickler",
    "Backend Developer",
    "Full Stack Developer",
    "Python Developer",
    "Data Engineer",
    "Data Analyst",
    "Data Scientist",
    "Machine Learning Engineer",
    "AI Engineer",
    "QA Engineer",
    "Test Engineer",
    "Informatiker",
]

PREVIOUS_PROFESSIONS = [
    "software engineer",
    "software developer",
    "softwareentwickler",
    "application developer",
    "applikationsentwickler",
    "backend developer",
    "frontend developer",
    "full stack developer",
    "python developer",
    "data engineer",
    "data analyst",
    "data scientist",
    "machine learning engineer",
    "AI engineer",
    "DevOps engineer",
    "cloud engineer",
    "QA engineer",
    "test engineer",
    "system engineer",
    "ICT support",
    "IT support",
    "cybersecurity analyst",
    "business analyst IT",
    "informatiker",
    "développeur logiciel",
    "ingénieur logiciel",
    "support informatique",
]
PREVIOUS_TARGET_ROLES = [
    "Software Engineer",
    "Software Developer",
    "Application Developer",
    "Backend Developer",
    "Frontend Developer",
    "Full Stack Developer",
    "Python Developer",
    "Data Engineer",
    "Data Analyst",
    "Data Scientist",
    "Machine Learning Engineer",
    "AI Engineer",
    "DevOps Engineer",
    "Cloud Engineer",
    "QA Engineer",
    "Test Engineer",
    "System Engineer",
    "ICT Support",
    "IT Support",
    "Cybersecurity Analyst",
    "IT Business Analyst",
    "IT Intern",
    "Working Student IT",
    "Junior IT",
]


def upgrade() -> None:
    _apply(
        professions=SELECTED_PROFESSIONS,
        target_roles=SELECTED_TARGET_ROLES,
    )


def downgrade() -> None:
    _apply(
        professions=PREVIOUS_PROFESSIONS,
        target_roles=PREVIOUS_TARGET_ROLES,
    )


def _apply(*, professions: list[str], target_roles: list[str]) -> None:
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
        source["filters"], professions=professions
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
            search, professions=professions
        )
    screening = filters.get("screening")
    if isinstance(screening, dict):
        screening["targetRoles"] = deepcopy(target_roles)
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
    professions: list[str],
) -> dict[str, Any]:
    filters = deepcopy(raw_filters) if isinstance(raw_filters, dict) else {}
    raw_queries = filters.get("linkedinQueries")
    queries = raw_queries if isinstance(raw_queries, list) else []
    existing_professions = {
        str(query.get("keyword", "")).casefold(): query
        for query in queries
        if isinstance(query, dict) and query.get("experienceLevels")
    }
    supporting_queries = [
        deepcopy(query)
        for query in queries
        if isinstance(query, dict) and not query.get("experienceLevels")
    ]
    profession_queries = []
    for keyword in professions:
        existing = existing_professions.get(keyword.casefold())
        query = deepcopy(existing) if existing is not None else {
            "keyword": keyword,
            "selectiveSearch": True,
        }
        query["keyword"] = keyword
        query["experienceLevels"] = deepcopy(ENTRY_LEVELS)
        profession_queries.append(query)

    filters["keywords"] = " OR ".join(professions)
    filters["linkedinQueries"] = profession_queries + supporting_queries
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
