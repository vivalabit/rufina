"""persist ATS final reviews and renderer inputs

Revision ID: 20260725_0024
Revises: 20260725_0023
Create Date: 2026-07-25 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0024"
down_revision: str | None = "20260725_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ats_final_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "experience_rewrite_id",
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
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("render_input", sa.JSON(), nullable=False),
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
            name="ck_ats_final_reviews_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_ats_final_reviews_latency_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["experience_rewrite_id"],
            ["experience_rewrites.id"],
            name="fk_ats_final_reviews_experience_rewrite",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_id"],
            ["resume_masters.id"],
            name="fk_ats_final_reviews_master",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_version_id"],
            ["resume_master_versions.id"],
            name="fk_ats_final_reviews_master_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "owner_id",
        "experience_rewrite_id",
        "resume_master_id",
        "resume_master_version_id",
        "target_job_id",
    ):
        op.create_index(
            op.f(f"ix_ats_final_reviews_{column}"),
            "ats_final_reviews",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_ats_final_reviews_input",
        "ats_final_reviews",
        ["owner_id", "experience_rewrite_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ats_final_reviews_input",
        table_name="ats_final_reviews",
    )
    for column in (
        "target_job_id",
        "resume_master_version_id",
        "resume_master_id",
        "experience_rewrite_id",
        "owner_id",
    ):
        op.drop_index(
            op.f(f"ix_ats_final_reviews_{column}"),
            table_name="ats_final_reviews",
        )
    op.drop_table("ats_final_reviews")
