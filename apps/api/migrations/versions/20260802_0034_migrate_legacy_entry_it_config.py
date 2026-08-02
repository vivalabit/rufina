"""migrate an existing legacy Entry IT config to the shared profile

Revision ID: 20260802_0034
Revises: 20260802_0033
Create Date: 2026-08-02 15:00:00.000000
"""

from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0034"
down_revision: str | None = "20260802_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_ID = "entry-it"
ENTRY_IT_NAME = "Entry IT"
ENTRY_IT_OWNER_ID = "local-owner"
ENTRY_IT_UPDATED_AT = datetime(2026, 8, 2, 15, 0, tzinfo=UTC)
ENTRY_IT_SOURCE_IDS = {
    "linkedin": "entry-it-linkedin",
    "indeed": "entry-it-indeed",
    "jobs_ch": "entry-it-jobs-ch",
}
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
SEARCH_DEFAULTS = {
    "keywords": "",
    "location": "",
    "remote": "Any",
    "experienceLevel": "Any",
    "jobType": "Any",
    "datePosted": "Any time",
    "resultsLimit": 100,
    "country": "Any",
    "deduplicate": True,
    "searchName": ENTRY_IT_NAME,
    "folder": "",
}
SEARCH_FIELDS = frozenset(SEARCH_DEFAULTS)


def upgrade() -> None:
    connection = op.get_bind()
    configs = _config_table()
    entry_it = connection.execute(
        sa.select(configs.c.id, configs.c.filters).where(
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
            sa.or_(
                configs.c.id == ENTRY_IT_ID,
                sa.func.lower(configs.c.name) == ENTRY_IT_NAME.lower(),
            ),
        )
    ).mappings().first()
    if entry_it is None:
        return

    config_id = entry_it["id"]
    filters = entry_it["filters"]
    if not isinstance(filters, dict):
        filters = {}
    migrated_filters = _migrate_filters(filters)
    if migrated_filters != filters:
        connection.execute(
            configs.update()
            .where(
                configs.c.id == config_id,
                configs.c.owner_id == ENTRY_IT_OWNER_ID,
            )
            .values(filters=migrated_filters, updated_at=ENTRY_IT_UPDATED_AT)
        )

    _seed_source_configs(
        connection,
        config_id=config_id,
        search_filters=migrated_filters["search"],
    )
    _seed_preset(connection, config_id=config_id)


def downgrade() -> None:
    connection = op.get_bind()
    configs = _config_table()
    config_id = connection.execute(
        sa.select(configs.c.id).where(
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
            sa.func.lower(configs.c.name) == ENTRY_IT_NAME.lower(),
        )
    ).scalar_one_or_none()
    if config_id is None or config_id == ENTRY_IT_ID:
        return

    presets = _preset_table()
    connection.execute(
        presets.delete().where(
            presets.c.id == "entry-it-all-sources",
            presets.c.config_id == config_id,
            presets.c.owner_id == ENTRY_IT_OWNER_ID,
        )
    )
    source_configs = _source_config_table()
    connection.execute(
        source_configs.delete().where(
            source_configs.c.config_id == config_id,
            source_configs.c.id.in_(ENTRY_IT_SOURCE_IDS.values()),
            source_configs.c.owner_id == ENTRY_IT_OWNER_ID,
        )
    )


def _migrate_filters(filters: dict[str, object]) -> dict[str, object]:
    if filters.get("schemaVersion") == 2 and isinstance(filters.get("search"), dict):
        migrated = deepcopy(filters)
        screening = migrated.get("screening")
        if not isinstance(screening, dict):
            migrated["screening"] = _screening_defaults()
        return migrated

    search = deepcopy(SEARCH_DEFAULTS)
    for key in SEARCH_FIELDS:
        if key in filters:
            search[key] = deepcopy(filters[key])
    return {
        "schemaVersion": 2,
        "search": search,
        "screening": _screening_defaults(),
    }


def _screening_defaults() -> dict[str, object]:
    return {
        "enabled": True,
        "targetRoles": deepcopy(ENTRY_IT_TARGET_ROLES),
        "excludedRoles": [],
        "allowedSeniority": [],
        "excludedSeniority": [],
        "hardRules": [],
    }


def _seed_source_configs(
    connection: sa.Connection,
    *,
    config_id: str,
    search_filters: dict[str, object],
) -> None:
    source_configs = _source_config_table()
    for source, source_config_id in ENTRY_IT_SOURCE_IDS.items():
        exists = connection.execute(
            sa.select(source_configs.c.id).where(
                source_configs.c.id == source_config_id
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        connection.execute(
            source_configs.insert().values(
                id=source_config_id,
                name=f"Entry IT · {_source_label(source)}",
                config_id=config_id,
                source=source,
                filters=deepcopy(search_filters),
                created_at=ENTRY_IT_UPDATED_AT,
                updated_at=ENTRY_IT_UPDATED_AT,
                owner_id=ENTRY_IT_OWNER_ID,
            )
        )


def _seed_preset(connection: sa.Connection, *, config_id: str) -> None:
    presets = _preset_table()
    exists = connection.execute(
        sa.select(presets.c.id).where(presets.c.id == "entry-it-all-sources")
    ).scalar_one_or_none()
    if exists is not None:
        return
    connection.execute(
        presets.insert().values(
            id="entry-it-all-sources",
            name="Entry IT · all sources",
            config_id=config_id,
            sources=["linkedin", "indeed", "jobs_ch", "sbb"],
            source_config_ids=ENTRY_IT_SOURCE_IDS,
            created_at=ENTRY_IT_UPDATED_AT,
            updated_at=ENTRY_IT_UPDATED_AT,
            owner_id=ENTRY_IT_OWNER_ID,
        )
    )


def _config_table() -> sa.TableClause:
    return sa.table(
        "job_search_configs",
        sa.column("id", sa.String(length=36)),
        sa.column("name", sa.String(length=240)),
        sa.column("filters", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("owner_id", sa.String(length=160)),
    )


def _source_config_table() -> sa.TableClause:
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


def _preset_table() -> sa.TableClause:
    return sa.table(
        "job_search_presets",
        sa.column("id", sa.String(length=36)),
        sa.column("name", sa.String(length=240)),
        sa.column("config_id", sa.String(length=36)),
        sa.column("sources", sa.JSON()),
        sa.column("source_config_ids", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("owner_id", sa.String(length=160)),
    )


def _source_label(source: str) -> str:
    return {"linkedin": "LinkedIn", "indeed": "Indeed", "jobs_ch": "jobs.ch"}[source]
