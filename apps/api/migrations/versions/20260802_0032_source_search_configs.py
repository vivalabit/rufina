"""add per-source search configs and reusable search presets

Revision ID: 20260802_0032
Revises: 20260802_0031
Create Date: 2026-08-02 14:00:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0032"
down_revision: str | None = "20260802_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_IT_ID = "entry-it"
ENTRY_IT_OWNER_ID = "local-owner"
ENTRY_IT_CREATED_AT = datetime(2026, 7, 21, tzinfo=UTC)
ENTRY_IT_SOURCE_IDS = {
    "linkedin": "entry-it-linkedin",
    "indeed": "entry-it-indeed",
    "jobs_ch": "entry-it-jobs-ch",
}
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


def upgrade() -> None:
    op.create_table(
        "job_source_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("config_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["job_search_configs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("config_id", "source", "updated_at", "owner_id"):
        op.create_index(
            op.f(f"ix_job_source_configs_{column}"),
            "job_source_configs",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_job_source_configs_config_source",
        "job_source_configs",
        ["config_id", "source"],
        unique=False,
    )

    op.create_table(
        "job_search_presets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("config_id", sa.String(length=36), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("source_config_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["job_search_configs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("config_id", "updated_at", "owner_id"):
        op.create_index(
            op.f(f"ix_job_search_presets_{column}"),
            "job_search_presets",
            [column],
            unique=False,
        )

    with op.batch_alter_table("job_search_schedules") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_config_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column("preset_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_job_search_schedules_preset_id_job_search_presets",
            "job_search_presets",
            ["preset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_job_search_schedules_preset_id"),
            ["preset_id"],
            unique=False,
        )

    _seed_entry_it_source_configs()


def _seed_entry_it_source_configs() -> None:
    connection = op.get_bind()
    configs = sa.table(
        "job_search_configs",
        sa.column("id", sa.String(length=36)),
        sa.column("owner_id", sa.String(length=160)),
    )
    entry_it_exists = connection.execute(
        sa.select(configs.c.id).where(
            configs.c.id == ENTRY_IT_ID,
            configs.c.owner_id == ENTRY_IT_OWNER_ID,
        )
    ).scalar_one_or_none()
    if entry_it_exists is None:
        return

    source_configs = sa.table(
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
    for source, source_config_id in ENTRY_IT_SOURCE_IDS.items():
        connection.execute(
            source_configs.insert().values(
                id=source_config_id,
                name=f"Entry IT · {_source_label(source)}",
                config_id=ENTRY_IT_ID,
                source=source,
                filters=ENTRY_IT_SOURCE_FILTERS,
                created_at=ENTRY_IT_CREATED_AT,
                updated_at=ENTRY_IT_CREATED_AT,
                owner_id=ENTRY_IT_OWNER_ID,
            )
        )

    presets = sa.table(
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
    connection.execute(
        presets.insert().values(
            id="entry-it-all-sources",
            name="Entry IT · all sources",
            config_id=ENTRY_IT_ID,
            sources=["linkedin", "indeed", "jobs_ch", "sbb"],
            source_config_ids=ENTRY_IT_SOURCE_IDS,
            created_at=ENTRY_IT_CREATED_AT,
            updated_at=ENTRY_IT_CREATED_AT,
            owner_id=ENTRY_IT_OWNER_ID,
        )
    )


def _source_label(source: str) -> str:
    return {"linkedin": "LinkedIn", "indeed": "Indeed", "jobs_ch": "jobs.ch"}[source]


def downgrade() -> None:
    with op.batch_alter_table("job_search_schedules") as batch_op:
        batch_op.drop_index(op.f("ix_job_search_schedules_preset_id"))
        batch_op.drop_constraint(
            "fk_job_search_schedules_preset_id_job_search_presets",
            type_="foreignkey",
        )
        batch_op.drop_column("preset_id")
        batch_op.drop_column("source_config_ids")
    op.drop_table("job_search_presets")
    op.drop_table("job_source_configs")
