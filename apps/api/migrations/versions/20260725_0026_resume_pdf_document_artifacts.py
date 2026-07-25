"""store format-aware generated resume PDF artifacts

Revision ID: 20260725_0026
Revises: 20260725_0025
Create Date: 2026-07-25 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0026"
down_revision: str | None = "20260725_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upgrade() -> None:
    with op.batch_alter_table("document_files") as batch_op:
        batch_op.add_column(
            sa.Column(
                "file_name",
                sa.String(length=240),
                server_default="",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "content_type",
                sa.String(length=160),
                server_default=DOCX_CONTENT_TYPE,
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "renderer_template_id",
                sa.String(length=80),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "renderer_template_version",
                sa.String(length=40),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_ats_final_review_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("final_resume_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("stage_results", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("provenance", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "fk_document_files_ats_final_review",
            "ats_final_reviews",
            ["source_ats_final_review_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_document_files_resume_pdf_source",
            [
                "source_ats_final_review_id",
                "renderer_template_id",
                "renderer_template_version",
            ],
        )

    op.create_index(
        op.f("ix_document_files_source_ats_final_review_id"),
        "document_files",
        ["source_ats_final_review_id"],
        unique=False,
    )

    with op.batch_alter_table("document_files") as batch_op:
        batch_op.alter_column(
            "file_name",
            existing_type=sa.String(length=240),
            server_default=None,
            nullable=False,
        )
        batch_op.alter_column(
            "content_type",
            existing_type=sa.String(length=160),
            server_default=None,
            nullable=False,
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_files_source_ats_final_review_id"),
        table_name="document_files",
    )
    with op.batch_alter_table("document_files") as batch_op:
        batch_op.drop_constraint(
            "uq_document_files_resume_pdf_source",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_document_files_ats_final_review",
            type_="foreignkey",
        )
        batch_op.drop_column("provenance")
        batch_op.drop_column("stage_results")
        batch_op.drop_column("final_resume_json")
        batch_op.drop_column("source_ats_final_review_id")
        batch_op.drop_column("renderer_template_version")
        batch_op.drop_column("renderer_template_id")
        batch_op.drop_column("content_type")
        batch_op.drop_column("file_name")
