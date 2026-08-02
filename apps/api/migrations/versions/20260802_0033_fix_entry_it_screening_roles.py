"""replace the invalid Entry IT screening role with concrete roles

Revision ID: 20260802_0033
Revises: 20260802_0032
Create Date: 2026-08-02 14:30:00.000000
"""

from collections.abc import Sequence
from copy import deepcopy

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0033"
down_revision: str | None = "20260802_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_ID = "entry-it"
ENTRY_IT_OWNER_ID = "local-owner"
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


def _config_table() -> sa.TableClause:
    return sa.table(
        "job_search_configs",
        sa.column("id", sa.String(length=36)),
        sa.column("owner_id", sa.String(length=160)),
        sa.column("filters", sa.JSON()),
    )


def upgrade() -> None:
    configs = _config_table()
    connection = op.get_bind()
    filters = connection.execute(
        sa.select(configs.c.filters).where(
            configs.c.id == ENTRY_IT_ID,
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
        )
    ).scalar_one_or_none()
    if not isinstance(filters, dict):
        return
    screening = filters.get("screening")
    if not isinstance(screening, dict):
        return
    if screening.get("targetRoles") != [ENTRY_IT_KEYWORDS]:
        return

    updated_filters = deepcopy(filters)
    updated_filters["screening"]["targetRoles"] = ENTRY_IT_TARGET_ROLES
    connection.execute(
        configs.update()
        .where(
            configs.c.id == ENTRY_IT_ID,
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
        )
        .values(filters=updated_filters)
    )


def downgrade() -> None:
    configs = _config_table()
    connection = op.get_bind()
    filters = connection.execute(
        sa.select(configs.c.filters).where(
            configs.c.id == ENTRY_IT_ID,
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
        )
    ).scalar_one_or_none()
    if not isinstance(filters, dict):
        return
    screening = filters.get("screening")
    if not isinstance(screening, dict):
        return
    if screening.get("targetRoles") != ENTRY_IT_TARGET_ROLES:
        return

    updated_filters = deepcopy(filters)
    updated_filters["screening"]["targetRoles"] = [ENTRY_IT_KEYWORDS]
    connection.execute(
        configs.update()
        .where(
            configs.c.id == ENTRY_IT_ID,
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
        )
        .values(filters=updated_filters)
    )
