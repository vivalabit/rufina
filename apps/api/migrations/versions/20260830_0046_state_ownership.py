"""prepare durable state ownership and optimistic concurrency

Revision ID: 20260830_0046
Revises: 20260829_0045
Create Date: 2026-08-30 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0046"
down_revision: str | None = "20260829_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_OWNER_ID = "local-owner"


def upgrade() -> None:
    op.add_column(
        "stored_jobs",
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stored_jobs",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stored_jobs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "stored_jobs",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute(sa.text("UPDATE stored_jobs SET updated_at = CURRENT_TIMESTAMP"))
    with op.batch_alter_table("stored_jobs") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )

    for table_name in ("stored_applications", "stored_application_events"):
        op.add_column(
            table_name,
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET created_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP"
            )
        )
        with op.batch_alter_table(table_name) as batch_op:
            for column_name in ("created_at", "updated_at"):
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                )

    op.add_column(
        "profiles",
        sa.Column(
            "owner_id",
            sa.String(length=160),
            nullable=False,
            server_default=LEGACY_OWNER_ID,
        ),
    )
    op.add_column(
        "profiles",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "profiles",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(sa.text("UPDATE profiles SET updated_at = CURRENT_TIMESTAMP"))
    with op.batch_alter_table("profiles") as batch_op:
        batch_op.alter_column(
            "owner_id",
            existing_type=sa.String(length=160),
            nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
    op.create_index(op.f("ix_profiles_owner_id"), "profiles", ["owner_id"])
    op.create_index(op.f("ix_profiles_updated_at"), "profiles", ["updated_at"])
    with op.batch_alter_table("profiles") as batch_op:
        batch_op.create_unique_constraint("uq_profiles_owner_id", ["owner_id"])

    op.add_column(
        "profile_versions",
        sa.Column(
            "owner_id",
            sa.String(length=160),
            nullable=False,
            server_default=LEGACY_OWNER_ID,
        ),
    )
    op.add_column(
        "profile_versions",
        sa.Column("revision", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "WITH ranked AS ("
            "  SELECT id, ROW_NUMBER() OVER ("
            "    PARTITION BY owner_id, profile_id "
            "    ORDER BY created_at ASC, id ASC"
            "  ) AS revision "
            "  FROM profile_versions"
            ") "
            "UPDATE profile_versions "
            "SET revision = ("
            "  SELECT ranked.revision FROM ranked "
            "  WHERE ranked.id = profile_versions.id"
            ")"
        )
    )
    op.execute(
        sa.text(
            "UPDATE profiles SET revision = COALESCE(("
            "  SELECT MAX(profile_versions.revision) "
            "  FROM profile_versions "
            "  WHERE profile_versions.owner_id = profiles.owner_id "
            "    AND profile_versions.profile_id = profiles.id"
            "), 0) + 1"
        )
    )
    with op.batch_alter_table("profile_versions") as batch_op:
        batch_op.alter_column(
            "owner_id",
            existing_type=sa.String(length=160),
            nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "revision",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_profile_versions_owner_profile_revision",
            ["owner_id", "profile_id", "revision"],
        )
    op.create_index(
        op.f("ix_profile_versions_owner_id"),
        "profile_versions",
        ["owner_id"],
    )
    op.create_table(
        "application_preferences",
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("application_id", sa.String(length=160), nullable=False),
        sa.Column("resume_template_id", sa.String(length=160), nullable=True),
        sa.Column("resume_generation_mode", sa.String(length=32), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "resume_generation_mode IS NULL OR resume_generation_mode IN "
            "('recruiter_xyz_ats', 'imaginator')",
            name="ck_application_preferences_resume_generation_mode",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["stored_applications.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_id", "application_id"),
    )
    op.create_index(
        op.f("ix_application_preferences_owner_id"),
        "application_preferences",
        ["owner_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_application_preferences_owner_id"),
        table_name="application_preferences",
    )
    op.drop_table("application_preferences")

    op.drop_index(
        op.f("ix_profile_versions_owner_id"),
        table_name="profile_versions",
    )
    with op.batch_alter_table("profile_versions") as batch_op:
        batch_op.drop_constraint(
            "uq_profile_versions_owner_profile_revision",
            type_="unique",
        )
        batch_op.drop_column("revision")
        batch_op.drop_column("owner_id")

    op.drop_index(op.f("ix_profiles_updated_at"), table_name="profiles")
    op.drop_index(op.f("ix_profiles_owner_id"), table_name="profiles")
    with op.batch_alter_table("profiles") as batch_op:
        batch_op.drop_constraint("uq_profiles_owner_id", type_="unique")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("revision")
        batch_op.drop_column("owner_id")

    for table_name in ("stored_application_events", "stored_applications"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("revision")
            batch_op.drop_column("updated_at")
            batch_op.drop_column("created_at")

    with op.batch_alter_table("stored_jobs") as batch_op:
        batch_op.drop_column("revision")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("saved_at")
