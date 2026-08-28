"""store persistent critical parser failure notifications

Revision ID: 20260828_0044
Revises: 20260827_0043
Create Date: 2026-08-28 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0044"
down_revision: str | None = "20260827_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "critical_notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "severity",
            sa.String(length=16),
            server_default="critical",
            nullable=False,
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "attempts > 0",
            name="ck_critical_notifications_attempts",
        ),
        sa.CheckConstraint(
            "severity = 'critical'",
            name="ck_critical_notifications_severity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "run_id",
            "source",
            name="uq_critical_notifications_owner_run_source",
        ),
    )
    op.create_index(
        "ix_critical_notifications_created_at",
        "critical_notifications",
        ["created_at"],
    )
    op.create_index(
        "ix_critical_notifications_owner_created_at",
        "critical_notifications",
        ["owner_id", "created_at"],
    )
    op.create_index(
        op.f("ix_critical_notifications_owner_id"),
        "critical_notifications",
        ["owner_id"],
    )


def downgrade() -> None:
    op.drop_table("critical_notifications")
