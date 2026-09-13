"""Retire storage used only by the obsolete preparation pipelines.

Revision ID: 20260913_0056
Revises: 20260913_0055
Create Date: 2026-09-13 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

revision: str = "20260913_0056"
down_revision: str | None = "20260913_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    check_constraints = {
        constraint["name"]
        for constraint in inspect(op.get_bind()).get_check_constraints("document_files")
        if constraint.get("name")
    }

    # Generated files remain available through their durable content and
    # renderer metadata. These links and JSON payloads belonged exclusively to
    # the retired ATS and Imaginator pipelines.
    op.drop_index(
        op.f("ix_document_files_source_ats_final_review_id"),
        table_name="document_files",
    )
    op.drop_index(
        op.f("ix_document_files_source_imaginator_resume_id"),
        table_name="document_files",
    )
    with op.batch_alter_table("document_files") as batch_op:
        if "ck_document_files_single_resume_pipeline_source" in check_constraints:
            batch_op.drop_constraint(
                "ck_document_files_single_resume_pipeline_source",
                type_="check",
            )
        batch_op.drop_constraint(
            "uq_document_files_imaginator_resume_pdf_source",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_document_files_resume_pdf_source",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_document_files_imaginator_resume",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_document_files_ats_final_review",
            type_="foreignkey",
        )
        batch_op.drop_column("source_imaginator_resume_id")
        batch_op.drop_column("source_ats_final_review_id")
        batch_op.drop_column("stage_results")
        batch_op.drop_column("final_resume_json")
        batch_op.drop_column("provenance")

    # Dependants precede the stores they reference. Dropping a table also
    # removes its private indexes and constraints on every supported backend.
    for table_name in (
        "document_validation_artifacts",
        "document_generation_artifacts",
        "document_workflow_runs",
        "document_pack_jobs",
        "document_version_validations",
        "document_version_generation_provenance",
        "document_generation_provenance",
        "resume_tailoring_stages",
        "resume_tailoring_runs",
        "ats_final_reviews",
        "experience_rewrites",
        "senior_recruiter_analyses",
        "imaginator_resumes",
        "candidate_confirmations",
        "application_preferences",
    ):
        op.drop_table(table_name)


def downgrade() -> None:
    raise RuntimeError(
        "obsolete preparation data was physically deleted and cannot be reconstructed"
    )
