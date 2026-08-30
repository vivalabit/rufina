"""widen discovered vacancy source identifiers

Revision ID: 20260829_0045
Revises: 20260828_0044
Create Date: 2026-08-29 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0045"
down_revision: str | None = "20260828_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("discovered_vacancies") as batch_op:
        batch_op.alter_column(
            "source",
            existing_type=sa.String(length=32),
            type_=sa.String(length=160),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("discovered_vacancies") as batch_op:
        batch_op.alter_column(
            "source",
            existing_type=sa.String(length=160),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
