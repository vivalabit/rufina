"""add master resume review and confirmation

Revision ID: 20260725_0021
Revises: 20260725_0020
Create Date: 2026-07-25 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0021"
down_revision: str | None = "20260725_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resume_source_files") as batch_op:
        batch_op.add_column(
            sa.Column("draft_resume_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "extraction",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch_op.alter_column(
            "resume_master_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )

    with op.batch_alter_table("resume_source_files") as batch_op:
        batch_op.alter_column(
            "extraction",
            existing_type=sa.JSON(),
            server_default=None,
            nullable=False,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM resume_source_files WHERE resume_master_id IS NULL"
        )
    )
    with op.batch_alter_table("resume_source_files") as batch_op:
        batch_op.alter_column(
            "resume_master_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.drop_column("extraction")
        batch_op.drop_column("draft_resume_id")
