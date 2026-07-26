"""add owner-scoped resume template definitions

Revision ID: 20260726_0027
Revises: 20260725_0026
Create Date: 2026-07-26 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_0027"
down_revision: str | None = "20260725_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_template_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("base_template_id", sa.String(length=80), nullable=False),
        sa.Column("design_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_resume_template_definitions_version_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_resume_template_definitions_owner_id"),
        "resume_template_definitions",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_template_definitions_updated_at"),
        "resume_template_definitions",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_resume_template_definitions_owner_base",
        "resume_template_definitions",
        ["owner_id", "base_template_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resume_template_definitions_owner_base",
        table_name="resume_template_definitions",
    )
    op.drop_index(
        op.f("ix_resume_template_definitions_updated_at"),
        table_name="resume_template_definitions",
    )
    op.drop_index(
        op.f("ix_resume_template_definitions_owner_id"),
        table_name="resume_template_definitions",
    )
    op.drop_table("resume_template_definitions")
