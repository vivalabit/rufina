"""key resume PDF artifacts by resolved design

Revision ID: 20260726_0028
Revises: 20260726_0027
Create Date: 2026-07-26 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_0028"
down_revision: str | None = "20260726_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_DESIGN_SHA256 = "0" * 64


def upgrade() -> None:
    with op.batch_alter_table("document_files") as batch_op:
        batch_op.drop_constraint(
            "uq_document_files_resume_pdf_source",
            type_="unique",
        )
        batch_op.add_column(
            sa.Column(
                "renderer_design_sha256",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.create_unique_constraint(
            "uq_document_files_resume_pdf_source",
            [
                "source_ats_final_review_id",
                "renderer_template_id",
                "renderer_template_version",
                "renderer_design_sha256",
            ],
        )
    op.execute(
        sa.text(
            "UPDATE document_files "
            "SET renderer_design_sha256 = :legacy_design_sha256 "
            "WHERE source_ats_final_review_id IS NOT NULL "
            "AND renderer_template_id IS NOT NULL "
            "AND renderer_template_version IS NOT NULL"
        ).bindparams(
            legacy_design_sha256=LEGACY_DESIGN_SHA256,
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("document_files") as batch_op:
        batch_op.drop_constraint(
            "uq_document_files_resume_pdf_source",
            type_="unique",
        )
        batch_op.drop_column("renderer_design_sha256")
        batch_op.create_unique_constraint(
            "uq_document_files_resume_pdf_source",
            [
                "source_ats_final_review_id",
                "renderer_template_id",
                "renderer_template_version",
            ],
        )
