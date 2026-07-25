"""add durable resume tailoring runs and stage attempts

Revision ID: 20260725_0025
Revises: 20260725_0024
Create Date: 2026-07-25 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0025"
down_revision: str | None = "20260725_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_tailoring_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_master_id", sa.String(length=36), nullable=False),
        sa.Column(
            "resume_master_version_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("target_job_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_stage", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_resume_tailoring_runs_status",
        ),
        sa.CheckConstraint(
            "current_stage >= 1 AND current_stage <= 3",
            name="ck_resume_tailoring_runs_current_stage",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_id"],
            ["resume_masters.id"],
            name="fk_resume_tailoring_runs_master",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_version_id"],
            ["resume_master_versions.id"],
            name="fk_resume_tailoring_runs_master_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "owner_id",
        "resume_master_id",
        "resume_master_version_id",
        "target_job_id",
    ):
        op.create_index(
            op.f(f"ix_resume_tailoring_runs_{column}"),
            "resume_tailoring_runs",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_resume_tailoring_runs_input",
        "resume_tailoring_runs",
        [
            "owner_id",
            "resume_master_version_id",
            "target_job_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_table(
        "resume_tailoring_stages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("stage_number", sa.Integer(), nullable=False),
        sa.Column("request_type", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("output_record_id", sa.String(length=36), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("token_count_source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "stage_number >= 1 AND stage_number <= 3",
            name="ck_resume_tailoring_stages_number",
        ),
        sa.CheckConstraint(
            "attempt >= 1",
            name="ck_resume_tailoring_stages_attempt",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_resume_tailoring_stages_status",
        ),
        sa.CheckConstraint(
            "request_type IN ("
            "'senior_recruiter_analysis', "
            "'xyz_experience_rewrite', "
            "'ats_final_review'"
            ")",
            name="ck_resume_tailoring_stages_request_type",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0",
            name="ck_resume_tailoring_stages_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_resume_tailoring_stages_latency_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["resume_tailoring_runs.id"],
            name="fk_resume_tailoring_stages_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "stage_number",
            "attempt",
            name="uq_resume_tailoring_stages_attempt",
        ),
    )
    for column in ("owner_id", "run_id", "output_record_id"):
        op.create_index(
            op.f(f"ix_resume_tailoring_stages_{column}"),
            "resume_tailoring_stages",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_resume_tailoring_stages_output",
        "resume_tailoring_stages",
        ["owner_id", "output_record_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resume_tailoring_stages_output",
        table_name="resume_tailoring_stages",
    )
    for column in ("output_record_id", "run_id", "owner_id"):
        op.drop_index(
            op.f(f"ix_resume_tailoring_stages_{column}"),
            table_name="resume_tailoring_stages",
        )
    op.drop_table("resume_tailoring_stages")

    op.drop_index(
        "ix_resume_tailoring_runs_input",
        table_name="resume_tailoring_runs",
    )
    for column in (
        "target_job_id",
        "resume_master_version_id",
        "resume_master_id",
        "owner_id",
    ):
        op.drop_index(
            op.f(f"ix_resume_tailoring_runs_{column}"),
            table_name="resume_tailoring_runs",
        )
    op.drop_table("resume_tailoring_runs")
