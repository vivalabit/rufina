"""add standalone Imaginator resume pipeline

Revision ID: 20260730_0029
Revises: 20260726_0028
Create Date: 2026-07-30 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0029"
down_revision: str | None = "20260726_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "imaginator_resumes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_master_id", sa.String(length=36), nullable=False),
        sa.Column(
            "resume_master_version_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("target_job_id", sa.String(length=160), nullable=False),
        sa.Column("application_id", sa.String(length=160), nullable=True),
        sa.Column("vacancy_hash", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("constraints_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("render_input", sa.JSON(), nullable=False),
        sa.Column("claim_ledger", sa.JSON(), nullable=False),
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
            name="ck_imaginator_resumes_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_imaginator_resumes_latency_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["stored_applications.id"],
            name="fk_imaginator_resumes_application",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_id"],
            ["resume_masters.id"],
            name="fk_imaginator_resumes_master",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_version_id"],
            ["resume_master_versions.id"],
            name="fk_imaginator_resumes_master_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "owner_id",
        "resume_master_id",
        "resume_master_version_id",
        "target_job_id",
        "application_id",
    ):
        op.create_index(
            op.f(f"ix_imaginator_resumes_{column}"),
            "imaginator_resumes",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_imaginator_resumes_input",
        "imaginator_resumes",
        [
            "owner_id",
            "resume_master_version_id",
            "target_job_id",
            "created_at",
        ],
        unique=False,
    )

    with op.batch_alter_table("document_files") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_imaginator_resume_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_document_files_imaginator_resume",
            "imaginator_resumes",
            ["source_imaginator_resume_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_document_files_imaginator_resume_pdf_source",
            [
                "source_imaginator_resume_id",
                "renderer_template_id",
                "renderer_template_version",
                "renderer_design_sha256",
            ],
        )
        batch_op.create_check_constraint(
            "ck_document_files_single_resume_pipeline_source",
            (
                "source_ats_final_review_id IS NULL "
                "OR source_imaginator_resume_id IS NULL"
            ),
        )
    op.create_index(
        op.f("ix_document_files_source_imaginator_resume_id"),
        "document_files",
        ["source_imaginator_resume_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_files_source_imaginator_resume_id"),
        table_name="document_files",
    )
    with op.batch_alter_table("document_files") as batch_op:
        batch_op.drop_constraint(
            "ck_document_files_single_resume_pipeline_source",
            type_="check",
        )
        batch_op.drop_constraint(
            "uq_document_files_imaginator_resume_pdf_source",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_document_files_imaginator_resume",
            type_="foreignkey",
        )
        batch_op.drop_column("source_imaginator_resume_id")

    op.drop_index(
        "ix_imaginator_resumes_input",
        table_name="imaginator_resumes",
    )
    for column in (
        "application_id",
        "target_job_id",
        "resume_master_version_id",
        "resume_master_id",
        "owner_id",
    ):
        op.drop_index(
            op.f(f"ix_imaginator_resumes_{column}"),
            table_name="imaginator_resumes",
        )
    op.drop_table("imaginator_resumes")
