"""remove legacy browser-file identity columns

Revision ID: 20260906_0052
Revises: 20260906_0051
Create Date: 2026-09-06 12:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0052"
down_revision: str | None = "20260906_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("profile_files") as batch_op:
        batch_op.drop_constraint(
            "uq_profile_files_owner_kind_legacy",
            type_="unique",
        )
        batch_op.drop_constraint(
            "ck_profile_files_legacy_id_kind",
            type_="check",
        )
        batch_op.drop_column("legacy_document_id")

    with op.batch_alter_table("workspace_source_documents") as batch_op:
        batch_op.drop_constraint(
            "uq_workspace_source_documents_owner_application_legacy",
            type_="unique",
        )
        batch_op.drop_column("legacy_document_id")


def downgrade() -> None:
    with op.batch_alter_table("workspace_source_documents") as batch_op:
        batch_op.add_column(
            sa.Column("legacy_document_id", sa.String(length=160), nullable=True),
        )
        batch_op.create_unique_constraint(
            "uq_workspace_source_documents_owner_application_legacy",
            ["owner_id", "application_id", "legacy_document_id"],
        )

    with op.batch_alter_table("profile_files") as batch_op:
        batch_op.add_column(
            sa.Column("legacy_document_id", sa.String(length=160), nullable=True),
        )
        batch_op.create_check_constraint(
            "ck_profile_files_legacy_id_kind",
            "kind = 'supporting_document' OR legacy_document_id IS NULL",
        )
        batch_op.create_unique_constraint(
            "uq_profile_files_owner_kind_legacy",
            ["owner_id", "kind", "legacy_document_id"],
        )
