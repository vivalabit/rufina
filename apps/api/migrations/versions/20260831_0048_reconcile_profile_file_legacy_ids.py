"""reconcile profile file legacy identity schema

Revision ID: 20260831_0048
Revises: 20260830_0047
Create Date: 2026-08-31 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0048"
down_revision: str | None = "20260830_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_CONTENT_UNIQUE = "uq_profile_files_owner_kind_sha256"
LEGACY_ID_CHECK = "ck_profile_files_legacy_id_kind"
LEGACY_ID_UNIQUE = "uq_profile_files_owner_kind_legacy"


def upgrade() -> None:
    """Repair databases upgraded with the earlier shape of revision 0047."""

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("profile_files")}
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("profile_files")
    }
    check_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("profile_files")
    }

    if "legacy_document_id" not in columns:
        op.add_column(
            "profile_files",
            sa.Column("legacy_document_id", sa.String(length=160), nullable=True),
        )

    schema_needs_reconciliation = (
        LEGACY_CONTENT_UNIQUE in unique_constraints
        or LEGACY_ID_UNIQUE not in unique_constraints
        or LEGACY_ID_CHECK not in check_constraints
    )
    if not schema_needs_reconciliation:
        return

    with op.batch_alter_table("profile_files") as batch_op:
        if LEGACY_CONTENT_UNIQUE in unique_constraints:
            batch_op.drop_constraint(LEGACY_CONTENT_UNIQUE, type_="unique")
        if LEGACY_ID_UNIQUE not in unique_constraints:
            batch_op.create_unique_constraint(
                LEGACY_ID_UNIQUE,
                ["owner_id", "kind", "legacy_document_id"],
            )
        if LEGACY_ID_CHECK not in check_constraints:
            batch_op.create_check_constraint(
                LEGACY_ID_CHECK,
                "kind = 'supporting_document' OR legacy_document_id IS NULL",
            )


def downgrade() -> None:
    # Revision 0047's canonical schema already contains these fields and
    # constraints. This repair revision therefore has no schema to undo.
    pass
