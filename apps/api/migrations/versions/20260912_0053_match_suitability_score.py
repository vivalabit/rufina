"""Reduce stored matches to suitability scores and calculation provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0053"
down_revision: str | None = "20260911_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_matches") as batch_op:
        for column in ("confidence", "breakdown", "reasons", "gaps", "heuristic_score"):
            batch_op.drop_column(column)

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


def downgrade() -> None:
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

    # Removed analysis cannot be reconstructed; retain scores and restore empty legacy fields.
    with op.batch_alter_table("job_matches") as batch_op:
        batch_op.add_column(
            sa.Column("confidence", sa.String(16), nullable=False, server_default="low")
        )
        batch_op.add_column(
            sa.Column("breakdown", sa.JSON(), nullable=False, server_default="{}")
        )
        for column in ("reasons", "gaps"):
            batch_op.add_column(
                sa.Column(column, sa.JSON(), nullable=False, server_default="[]")
            )
        batch_op.add_column(
            sa.Column("heuristic_score", sa.Integer(), nullable=False, server_default="0")
        )
