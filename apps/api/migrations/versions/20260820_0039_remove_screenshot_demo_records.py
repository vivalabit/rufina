"""remove screenshot demo records from the local owner workspace

Revision ID: 20260820_0039
Revises: 20260820_0038
Create Date: 2026-08-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0039"
down_revision: str | None = "20260820_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCAL_OWNER_ID = "local-owner"
DEMO_APPLICATION_IDS = (
    "application-manual-job-demo-novara",
    "application-manual-job-demo-cirruspay",
    "application-manual-job-demo-alpine-grid",
    "application-manual-job-demo-luma-health",
)
DEMO_JOB_IDS = (
    "manual-job-demo-novara",
    "manual-job-demo-cirruspay",
    "manual-job-demo-alpine-grid",
    "manual-job-demo-luma-health",
    "manual-job-demo-fieldnote",
    "manual-job-demo-greenline",
)


def upgrade() -> None:
    connection = op.get_bind()

    documents = sa.table(
        "documents",
        sa.column("id", sa.String()),
        sa.column("owner_id", sa.String()),
    )
    document_attachments = sa.table(
        "document_attachments",
        sa.column("document_id", sa.String()),
        sa.column("application_id", sa.String()),
    )
    connection.execute(
        document_attachments.delete().where(
            document_attachments.c.application_id.in_(DEMO_APPLICATION_IDS),
            document_attachments.c.document_id.in_(
                sa.select(documents.c.id).where(documents.c.owner_id == LOCAL_OWNER_ID)
            ),
        )
    )

    for table_name in (
        "document_validation_artifacts",
        "document_generation_artifacts",
        "document_pack_jobs",
        "workspace_source_documents",
        "candidate_confirmations",
        "stored_application_events",
    ):
        table = sa.table(
            table_name,
            sa.column("owner_id", sa.String()),
            sa.column("application_id", sa.String()),
        )
        connection.execute(
            table.delete().where(
                table.c.owner_id == LOCAL_OWNER_ID,
                table.c.application_id.in_(DEMO_APPLICATION_IDS),
            )
        )

    imaginator_resumes = sa.table(
        "imaginator_resumes",
        sa.column("owner_id", sa.String()),
        sa.column("application_id", sa.String()),
    )
    connection.execute(
        imaginator_resumes.update()
        .where(
            imaginator_resumes.c.owner_id == LOCAL_OWNER_ID,
            imaginator_resumes.c.application_id.in_(DEMO_APPLICATION_IDS),
        )
        .values(application_id=None)
    )

    stored_applications = sa.table(
        "stored_applications",
        sa.column("owner_id", sa.String()),
        sa.column("id", sa.String()),
    )
    connection.execute(
        stored_applications.delete().where(
            stored_applications.c.owner_id == LOCAL_OWNER_ID,
            stored_applications.c.id.in_(DEMO_APPLICATION_IDS),
        )
    )

    for table_name, id_column in (
        ("job_match_feedback", "job_id"),
        ("job_matches", "job_id"),
        ("stored_jobs", "id"),
    ):
        table = sa.table(
            table_name,
            sa.column("owner_id", sa.String()),
            sa.column(id_column, sa.String()),
        )
        connection.execute(
            table.delete().where(
                table.c.owner_id == LOCAL_OWNER_ID,
                table.c[id_column].in_(DEMO_JOB_IDS),
            )
        )


def downgrade() -> None:
    # The deleted fixture data is intentionally not recreated.
    pass
