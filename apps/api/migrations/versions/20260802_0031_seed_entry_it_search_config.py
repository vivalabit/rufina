"""move the bundled Entry IT search config to server storage

Revision ID: 20260802_0031
Revises: 20260730_0030
Create Date: 2026-08-02 12:00:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0031"
down_revision: str | None = "20260730_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_ID = "entry-it"
ENTRY_IT_NAME = "Entry IT"
ENTRY_IT_OWNER_ID = "local-owner"
ENTRY_IT_CREATED_AT = datetime(2026, 7, 21, tzinfo=UTC)
ENTRY_IT_KEYWORDS = (
    '(intern OR "working student" OR Werkstudent OR Praktikum OR junior OR '
    'graduate) AND (software OR developer OR python OR data OR "machine '
    'learning" OR "AI engineer" OR web)'
)
ENTRY_IT_TARGET_ROLES = [
    "Software Engineer",
    "Software Developer",
    "Python Developer",
    "Data Engineer",
    "Machine Learning Engineer",
    "AI Engineer",
    "Web Developer",
    "IT Intern",
    "Working Student IT",
    "Junior IT",
]
ENTRY_IT_FILTERS = {
    "schemaVersion": 2,
    "search": {
        "keywords": ENTRY_IT_KEYWORDS,
        "location": "Zurich, Switzerland",
        "remote": "Any",
        "experienceLevel": "Any",
        "jobType": "Any",
        "datePosted": "Past 24 hours",
        "resultsLimit": 50,
        "country": "Switzerland",
        "deduplicate": True,
        "searchName": ENTRY_IT_NAME,
        "folder": "",
    },
    "screening": {
        "enabled": True,
        "targetRoles": ENTRY_IT_TARGET_ROLES,
        "excludedRoles": [],
        "allowedSeniority": [],
        "excludedSeniority": [],
        "hardRules": [],
    },
}


def _config_table() -> sa.TableClause:
    return sa.table(
        "job_search_configs",
        sa.column("id", sa.String(length=36)),
        sa.column("name", sa.String(length=240)),
        sa.column("filters", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("owner_id", sa.String(length=160)),
    )


def upgrade() -> None:
    configs = _config_table()
    connection = op.get_bind()
    existing_id = connection.execute(
        sa.select(configs.c.id).where(
            sa.or_(
                configs.c.id == ENTRY_IT_ID,
                sa.and_(
                    configs.c.owner_id == ENTRY_IT_OWNER_ID,
                    sa.func.lower(configs.c.name) == ENTRY_IT_NAME.lower(),
                ),
            )
        )
    ).scalar_one_or_none()
    if existing_id is not None:
        return

    connection.execute(
        configs.insert().values(
            id=ENTRY_IT_ID,
            name=ENTRY_IT_NAME,
            filters=ENTRY_IT_FILTERS,
            created_at=ENTRY_IT_CREATED_AT,
            updated_at=ENTRY_IT_CREATED_AT,
            owner_id=ENTRY_IT_OWNER_ID,
        )
    )


def downgrade() -> None:
    configs = _config_table()
    op.get_bind().execute(
        configs.delete().where(
            configs.c.id == ENTRY_IT_ID,
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
        )
    )
