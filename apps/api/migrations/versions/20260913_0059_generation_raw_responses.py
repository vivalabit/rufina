"""Retain raw backend responses for generation-run audit and recovery.

Revision ID: 20260913_0059
Revises: 20260913_0058
Create Date: 2026-09-13 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0059"
down_revision: str | None = "20260913_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("generation_run_messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "raw_response",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
    with op.batch_alter_table("generation_run_messages") as batch_op:
        batch_op.alter_column(
            "raw_response",
            existing_type=sa.Text(),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_run_messages") as batch_op:
        batch_op.drop_column("raw_response")
