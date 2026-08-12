"""keep the bundled Entry IT query scoped to LinkedIn

Revision ID: 20260812_0036
Revises: 20260802_0035
Create Date: 2026-08-12 14:30:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0036"
down_revision: str | None = "20260802_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_PRESET_ID = "entry-it-all-sources"
ENTRY_IT_LINKEDIN_CONFIG_ID = "entry-it-linkedin"
ENTRY_IT_UNUSED_SOURCE_CONFIG_IDS = (
    "entry-it-indeed",
    "entry-it-jobs-ch",
)
ENTRY_IT_UPDATED_AT = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)
ENTRY_IT_CREATED_AT = datetime(2026, 7, 21, tzinfo=UTC)
ENTRY_IT_KEYWORDS = (
    '(intern OR "working student" OR Werkstudent OR Praktikum OR junior OR '
    'graduate) AND (software OR developer OR python OR data OR "machine '
    'learning" OR "AI engineer" OR web)'
)
ENTRY_IT_SOURCE_FILTERS = {
    "keywords": ENTRY_IT_KEYWORDS,
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


def _presets_table() -> sa.TableClause:
    return sa.table(
        "job_search_presets",
        sa.column("id", sa.String(length=36)),
        sa.column("name", sa.String(length=240)),
        sa.column("sources", sa.JSON()),
        sa.column("source_config_ids", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _source_configs_table() -> sa.TableClause:
    return sa.table(
        "job_source_configs",
        sa.column("id", sa.String(length=36)),
        sa.column("name", sa.String(length=240)),
        sa.column("config_id", sa.String(length=36)),
        sa.column("source", sa.String(length=32)),
        sa.column("filters", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("owner_id", sa.String(length=160)),
    )


def _schedules_table() -> sa.TableClause:
    return sa.table(
        "job_search_schedules",
        sa.column("preset_id", sa.String(length=36)),
        sa.column("sources", sa.JSON()),
        sa.column("source_config_ids", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    connection = op.get_bind()
    presets = _presets_table()
    source_configs = _source_configs_table()
    schedules = _schedules_table()

    connection.execute(
        presets.update()
        .where(presets.c.id == ENTRY_IT_PRESET_ID)
        .values(
            name="Entry IT · LinkedIn",
            sources=["linkedin"],
            source_config_ids={"linkedin": ENTRY_IT_LINKEDIN_CONFIG_ID},
            updated_at=ENTRY_IT_UPDATED_AT,
        )
    )
    connection.execute(
        schedules.update()
        .where(schedules.c.preset_id == ENTRY_IT_PRESET_ID)
        .values(
            sources=["linkedin"],
            source_config_ids={"linkedin": ENTRY_IT_LINKEDIN_CONFIG_ID},
            updated_at=ENTRY_IT_UPDATED_AT,
        )
    )
    connection.execute(
        source_configs.delete().where(
            source_configs.c.id.in_(ENTRY_IT_UNUSED_SOURCE_CONFIG_IDS)
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    presets = _presets_table()
    source_configs = _source_configs_table()
    schedules = _schedules_table()
    preset = connection.execute(
        sa.select(presets.c.id).where(presets.c.id == ENTRY_IT_PRESET_ID)
    ).first()
    if preset is None:
        return

    configs = sa.table(
        "job_search_presets",
        sa.column("id", sa.String(length=36)),
        sa.column("config_id", sa.String(length=36)),
    )
    config_id = connection.execute(
        sa.select(configs.c.config_id).where(configs.c.id == ENTRY_IT_PRESET_ID)
    ).scalar_one()
    for source, source_config_id, label in (
        ("indeed", "entry-it-indeed", "Indeed"),
        ("jobs_ch", "entry-it-jobs-ch", "jobs.ch"),
    ):
        exists = connection.execute(
            sa.select(source_configs.c.id).where(
                source_configs.c.id == source_config_id
            )
        ).first()
        if exists is None:
            connection.execute(
                source_configs.insert().values(
                    id=source_config_id,
                    name=f"Entry IT · {label}",
                    config_id=config_id,
                    source=source,
                    filters=ENTRY_IT_SOURCE_FILTERS,
                    created_at=ENTRY_IT_CREATED_AT,
                    updated_at=ENTRY_IT_CREATED_AT,
                    owner_id="local-owner",
                )
            )

    sources = ["linkedin", "indeed", "jobs_ch", "sbb"]
    source_config_ids = {
        "linkedin": ENTRY_IT_LINKEDIN_CONFIG_ID,
        "indeed": "entry-it-indeed",
        "jobs_ch": "entry-it-jobs-ch",
    }
    connection.execute(
        presets.update()
        .where(presets.c.id == ENTRY_IT_PRESET_ID)
        .values(
            name="Entry IT · all sources",
            sources=sources,
            source_config_ids=source_config_ids,
            updated_at=ENTRY_IT_CREATED_AT,
        )
    )
    connection.execute(
        schedules.update()
        .where(schedules.c.preset_id == ENTRY_IT_PRESET_ID)
        .values(
            sources=sources,
            source_config_ids=source_config_ids,
            updated_at=ENTRY_IT_CREATED_AT,
        )
    )
