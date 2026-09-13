"""Restore the historical durable document workflow schema revision."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0054"
down_revision: str | None = "20260906_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resume_master_versions") as batch_op:
        batch_op.drop_constraint(
            "fk_resume_master_versions_source",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "source_file_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_resume_master_versions_source",
            "resume_source_files",
            ["source_file_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.create_table(
        "document_workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("application_id", sa.String(length=160), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("repair_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("latex_source", sa.Text(), nullable=True),
        sa.Column("pdf_content", sa.LargeBinary(), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ready', 'running', 'failed', 'completed')",
            name="ck_document_workflow_status",
        ),
        sa.CheckConstraint(
            "document_type IN ('tailored_resume', 'cover_letter')",
            name="ck_document_workflow_type",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["stored_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_workflow_runs_application_id"),
        "document_workflow_runs",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_workflow_runs_owner_id"),
        "document_workflow_runs",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_workflow_runs_owner_id"),
        table_name="document_workflow_runs",
    )
    op.drop_index(
        op.f("ix_document_workflow_runs_application_id"),
        table_name="document_workflow_runs",
    )
    op.drop_table("document_workflow_runs")

    with op.batch_alter_table("resume_master_versions") as batch_op:
        batch_op.drop_constraint(
            "fk_resume_master_versions_source",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "source_file_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_resume_master_versions_source",
            "resume_source_files",
            ["source_file_id"],
            ["id"],
            ondelete="SET NULL",
        )
