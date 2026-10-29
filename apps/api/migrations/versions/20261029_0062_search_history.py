"""Persist search sessions and immutable source/vacancy reports."""

import sqlalchemy as sa
from alembic import op

revision = "20261029_0062"
down_revision = "20260923_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_search_runs") as batch:
        batch.add_column(sa.Column("session_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("report_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("report", sa.JSON(none_as_null=True), nullable=True))
        batch.create_index("ix_job_search_runs_session_id", ["session_id"])


def downgrade() -> None:
    with op.batch_alter_table("job_search_runs") as batch:
        batch.drop_index("ix_job_search_runs_session_id")
        batch.drop_column("report")
        batch.drop_column("report_version")
        batch.drop_column("session_id")
