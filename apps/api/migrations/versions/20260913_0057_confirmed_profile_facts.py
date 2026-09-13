"""Persist facts explicitly confirmed during document generation.

Revision ID: 20260913_0057
Revises: 20260913_0056
Create Date: 2026-09-13 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0057"
down_revision: str | None = "20260913_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "confirmed_profile_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("resume_master_id", sa.String(length=36), nullable=False),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("from_version", sa.Integer(), nullable=False),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.Column("fact_text", sa.String(length=20000), nullable=False),
        sa.Column("evidence_id", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "from_version >= 1 AND to_version = from_version + 1",
            name="ck_confirmed_profile_facts_versions",
        ),
        sa.ForeignKeyConstraint(
            ["resume_master_id"],
            ["resume_masters.id"],
            name="fk_confirmed_profile_facts_master",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_confirmed_profile_facts_owner_idempotency",
        ),
    )
    for column_name in ("owner_id", "resume_master_id", "source_run_id"):
        op.create_index(
            op.f(f"ix_confirmed_profile_facts_{column_name}"),
            "confirmed_profile_facts",
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    for column_name in ("source_run_id", "resume_master_id", "owner_id"):
        op.drop_index(
            op.f(f"ix_confirmed_profile_facts_{column_name}"),
            table_name="confirmed_profile_facts",
        )
    op.drop_table("confirmed_profile_facts")
