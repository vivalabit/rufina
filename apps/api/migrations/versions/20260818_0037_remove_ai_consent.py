"""remove the AI consent gate

Revision ID: 20260818_0037
Revises: 20260812_0036
Create Date: 2026-08-18 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0037"
down_revision: str | None = "20260812_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("ai_privacy_settings", "consented_at")
    op.drop_column("ai_privacy_settings", "consent_backend")
    op.drop_column("ai_privacy_settings", "consent_version")


def downgrade() -> None:
    op.add_column(
        "ai_privacy_settings",
        sa.Column("consent_version", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "ai_privacy_settings",
        sa.Column("consent_backend", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ai_privacy_settings",
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
    )
