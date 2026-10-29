"""Allow PDF check names containing full source identifiers.

Revision ID: 20260923_0061
Revises: 20260916_0060
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0061"
down_revision = "20260916_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_run_checks") as batch_op:
        batch_op.alter_column(
            "check_type", existing_type=sa.String(80), type_=sa.Text(), existing_nullable=False
        )


def downgrade() -> None:
    # Never truncate existing identifiers when restoring the old limit.
    oversized = op.get_bind().execute(
        sa.text("SELECT 1 FROM generation_run_checks WHERE length(check_type) > 80 LIMIT 1")
    ).first()
    if oversized:
        raise RuntimeError("Cannot restore the 80-character limit while longer check names exist")
    with op.batch_alter_table("generation_run_checks") as batch_op:
        batch_op.alter_column(
            "check_type", existing_type=sa.Text(), type_=sa.String(80), existing_nullable=False
        )
