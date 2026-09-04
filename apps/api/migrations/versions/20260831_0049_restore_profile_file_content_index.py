"""restore the profile file content hash index

Revision ID: 20260831_0049
Revises: 20260831_0048
Create Date: 2026-08-31 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0049"
down_revision: str | None = "20260831_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_HASH_INDEX = "ix_profile_files_content_sha256"


def upgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("profile_files")}
    if CONTENT_HASH_INDEX not in indexes:
        op.create_index(
            CONTENT_HASH_INDEX,
            "profile_files",
            ["content_sha256"],
            unique=False,
        )


def downgrade() -> None:
    # Revision 0047's canonical schema already contains this index. This repair
    # revision therefore has no schema to undo.
    pass
