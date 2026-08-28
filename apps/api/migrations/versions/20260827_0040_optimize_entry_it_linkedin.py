"""optimize the bundled Entry IT LinkedIn discovery strategy

Revision ID: 20260827_0040
Revises: 20260820_0039
Create Date: 2026-08-27 12:00:00.000000
"""

from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0040"
down_revision: str | None = "20260820_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_LINKEDIN_CONFIG_ID = "entry-it-linkedin"
ENTRY_IT_UPDATED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ENTRY_LEVELS = ["Entry level", "Internship", "Associate"]
TECHNICAL_KEYWORDS = [
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
ENTRY_MARKERS = [
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
LINKEDIN_QUERIES = [
    {
        "keyword": keyword,
        "experienceLevels": deepcopy(ENTRY_LEVELS),
        "selectiveSearch": True,
    }
    for keyword in TECHNICAL_KEYWORDS
] + [
    {
        "keyword": keyword,
        "experienceLevels": [],
        "selectiveSearch": True,
    }
    for keyword in ENTRY_MARKERS
] + [
    {
        "keyword": "IT",
        "experienceLevels": [],
        "jobType": "Internship",
        "selectiveSearch": True,
    },
    {
        "keyword": "ICT",
        "experienceLevels": [],
        "jobType": "Internship",
        "selectiveSearch": True,
    },
]
ENTRY_IT_KEYWORDS = (
    "software engineer OR software developer OR softwareentwickler OR "
    "application developer OR backend developer OR frontend developer OR "
    "python developer OR data engineer OR data analyst OR data scientist OR "
    "machine learning engineer OR AI engineer OR DevOps engineer OR "
    "cloud engineer OR QA engineer OR system engineer OR IT support"
)
ENTRY_IT_SEARCH = {
    "keywords": ENTRY_IT_KEYWORDS,
    "location": "Switzerland",
    "remote": "Any",
    "experienceLevel": "Any",
    "jobType": "Any",
    "datePosted": "Past week",
    "resultsLimit": 200,
    "country": "CH",
    "deduplicate": True,
    "linkedinQueries": LINKEDIN_QUERIES,
    "limitPerInput": 10,
    "searchName": "Entry IT",
    "folder": "",
}
ENTRY_IT_TARGET_ROLES = [
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
LEGACY_SEARCH = {
    "keywords": (
        '(intern OR "working student" OR Werkstudent OR Praktikum OR junior OR '
        'graduate) AND (software OR developer OR python OR data OR "machine '
        'learning" OR "AI engineer" OR web)'
    ),
    "location": "Zurich, Switzerland",
    "remote": "Any",
    "experienceLevel": "Any",
    "jobType": "Any",
    "datePosted": "Past 24 hours",
    "resultsLimit": 50,
    "country": "Switzerland",
    "deduplicate": True,
    "searchName": "Entry IT",
    "folder": "",
}


def upgrade() -> None:
    _apply(search=ENTRY_IT_SEARCH, optimized=True)


def downgrade() -> None:
    _apply(search=LEGACY_SEARCH, optimized=False)


def _apply(*, search: dict[str, Any], optimized: bool) -> None:
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

    connection.execute(
        source_configs.update()
        .where(source_configs.c.id == ENTRY_IT_LINKEDIN_CONFIG_ID)
        .values(filters=deepcopy(search), updated_at=ENTRY_IT_UPDATED_AT)
    )

    configs = _configs_table()
    raw_filters = connection.execute(
        sa.select(configs.c.filters).where(
            configs.c.id == source["config_id"],
            configs.c.owner_id == source["owner_id"],
        )
    ).scalar_one_or_none()
    filters = deepcopy(raw_filters) if isinstance(raw_filters, dict) else {}
    filters["schemaVersion"] = 2
    filters["search"] = deepcopy(search)
    screening = filters.get("screening")
    if not isinstance(screening, dict):
        screening = {}
    screening["enabled"] = True
    screening["targetRoles"] = deepcopy(ENTRY_IT_TARGET_ROLES)
    screening["allowedSeniority"] = (
        ["intern", "entry", "junior", "associate"] if optimized else []
    )
    screening.setdefault("excludedRoles", [])
    screening.setdefault("excludedSeniority", [])
    screening.setdefault("hardRules", [])
    filters["screening"] = screening
    connection.execute(
        configs.update()
        .where(
            configs.c.id == source["config_id"],
            configs.c.owner_id == source["owner_id"],
        )
        .values(filters=filters, updated_at=ENTRY_IT_UPDATED_AT)
    )


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
