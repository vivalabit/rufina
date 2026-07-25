"""persist master resumes and import versions

Revision ID: 20260725_0020
Revises: 20260724_0019
Create Date: 2026-07-25 10:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0020"
down_revision: str | None = "20260724_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_masters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "current_version >= 1",
            name="ck_resume_masters_current_version_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_resume_masters_owner_id"),
        "resume_masters",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_masters_updated_at"),
        "resume_masters",
        ["updated_at"],
        unique=False,
    )

    op.create_table(
        "resume_source_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_master_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "content_type IN ("
            "'application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
            ")",
            name="ck_resume_source_files_content_type",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_resume_source_files_size_positive",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_id"],
            ["resume_masters.id"],
            name="fk_resume_source_files_master",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resume_master_id",
            "content_sha256",
            name="uq_resume_source_files_master_sha256",
        ),
    )
    op.create_index(
        op.f("ix_resume_source_files_owner_id"),
        "resume_source_files",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_source_files_resume_master_id"),
        "resume_source_files",
        ["resume_master_id"],
        unique=False,
    )

    op.create_table(
        "resume_master_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_master_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_file_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_resume_master_versions_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_id"],
            ["resume_masters.id"],
            name="fk_resume_master_versions_master",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["resume_source_files.id"],
            name="fk_resume_master_versions_source",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resume_master_id",
            "version",
            name="uq_resume_master_versions_number",
        ),
    )
    op.create_index(
        op.f("ix_resume_master_versions_owner_id"),
        "resume_master_versions",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_master_versions_resume_master_id"),
        "resume_master_versions",
        ["resume_master_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_master_versions_source_file_id"),
        "resume_master_versions",
        ["source_file_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_resume_master_versions_source_file_id"),
        table_name="resume_master_versions",
    )
    op.drop_index(
        op.f("ix_resume_master_versions_resume_master_id"),
        table_name="resume_master_versions",
    )
    op.drop_index(
        op.f("ix_resume_master_versions_owner_id"),
        table_name="resume_master_versions",
    )
    op.drop_table("resume_master_versions")

    op.drop_index(
        op.f("ix_resume_source_files_resume_master_id"),
        table_name="resume_source_files",
    )
    op.drop_index(
        op.f("ix_resume_source_files_owner_id"),
        table_name="resume_source_files",
    )
    op.drop_table("resume_source_files")

    op.drop_index(
        op.f("ix_resume_masters_updated_at"),
        table_name="resume_masters",
    )
    op.drop_index(
        op.f("ix_resume_masters_owner_id"),
        table_name="resume_masters",
    )
    op.drop_table("resume_masters")
