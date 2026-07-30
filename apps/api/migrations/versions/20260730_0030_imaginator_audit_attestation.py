"""add Imaginator protected-facts audit attestation

Revision ID: 20260730_0030
Revises: 20260730_0029
Create Date: 2026-07-30 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0030"
down_revision: str | None = "20260730_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_UNVERIFIED_AUDIT = {
    "schemaVersion": "1.0",
    "passed": False,
    "auditedClaimCount": 1,
    "promptVersion": "imaginator-protected-facts-audit-v1",
    "result": {
        "inputFingerprint": "0" * 64,
        "verdict": "reject",
        "safePaths": [],
        "violations": [
            {
                "path": "legacyRecord",
                "categories": ["employer", "education", "identity"],
                "reason": (
                    "This Imaginator record predates protected-facts auditing "
                    "and must be regenerated before rendering."
                ),
            }
        ],
    },
    "metrics": {
        "latencyMs": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "tokenCountSource": "unavailable",
    },
    "model": "legacy-unverified",
    "backend": "openai_api",
    "providerSessionId": "",
}


def _has_audit_column() -> bool:
    return "protected_facts_audit" in {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(
            "imaginator_resumes"
        )
    }


def upgrade() -> None:
    # Revision 0029 briefly existed locally with this column before it was
    # extracted into its own migration. The guard repairs either 0029 shape.
    if _has_audit_column():
        return

    with op.batch_alter_table("imaginator_resumes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "protected_facts_audit",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    imaginator_resumes = sa.table(
        "imaginator_resumes",
        sa.column("protected_facts_audit", sa.JSON()),
    )
    op.execute(
        imaginator_resumes.update().values(
            protected_facts_audit=LEGACY_UNVERIFIED_AUDIT
        )
    )

    with op.batch_alter_table("imaginator_resumes") as batch_op:
        batch_op.alter_column(
            "protected_facts_audit",
            existing_type=sa.JSON(),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    if not _has_audit_column():
        return
    with op.batch_alter_table("imaginator_resumes") as batch_op:
        batch_op.drop_column("protected_facts_audit")
