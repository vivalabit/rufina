"""persist mandatory XYZ experience rewrites

Revision ID: 20260725_0023
Revises: 20260725_0022
Create Date: 2026-07-25 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0023"
down_revision: str | None = "20260725_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experience_rewrites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "senior_recruiter_analysis_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("resume_master_id", sa.String(length=36), nullable=False),
        sa.Column(
            "resume_master_version_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("target_job_id", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("original_experiences", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column(
            "provider_session_id",
            sa.String(length=500),
            nullable=False,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("token_count_source", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0",
            name="ck_experience_rewrites_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_experience_rewrites_latency_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["senior_recruiter_analysis_id"],
            ["senior_recruiter_analyses.id"],
            name="fk_experience_rewrites_recruiter_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_id"],
            ["resume_masters.id"],
            name="fk_experience_rewrites_master",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_version_id"],
            ["resume_master_versions.id"],
            name="fk_experience_rewrites_master_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_experience_rewrites_owner_id"),
        "experience_rewrites",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experience_rewrites_senior_recruiter_analysis_id"),
        "experience_rewrites",
        ["senior_recruiter_analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experience_rewrites_resume_master_id"),
        "experience_rewrites",
        ["resume_master_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experience_rewrites_resume_master_version_id"),
        "experience_rewrites",
        ["resume_master_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experience_rewrites_target_job_id"),
        "experience_rewrites",
        ["target_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_experience_rewrites_input",
        "experience_rewrites",
        ["owner_id", "senior_recruiter_analysis_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_experience_rewrites_input",
        table_name="experience_rewrites",
    )
    op.drop_index(
        op.f("ix_experience_rewrites_target_job_id"),
        table_name="experience_rewrites",
    )
    op.drop_index(
        op.f("ix_experience_rewrites_resume_master_version_id"),
        table_name="experience_rewrites",
    )
    op.drop_index(
        op.f("ix_experience_rewrites_resume_master_id"),
        table_name="experience_rewrites",
    )
    op.drop_index(
        op.f("ix_experience_rewrites_senior_recruiter_analysis_id"),
        table_name="experience_rewrites",
    )
    op.drop_index(
        op.f("ix_experience_rewrites_owner_id"),
        table_name="experience_rewrites",
    )
    op.drop_table("experience_rewrites")
