"""Persist recoverable application generation runs and artifacts.

Revision ID: 20260913_0058
Revises: 20260913_0057
Create Date: 2026-09-13 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0058"
down_revision: str | None = "20260913_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_generation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("application_id", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=32), nullable=False),
        sa.Column("settings_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("document_types", sa.JSON(), nullable=False),
        sa.Column("pending_question", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'completed', "
            "'failed', 'cancelled')",
            name="ck_application_generation_runs_status",
        ),
        sa.CheckConstraint(
            "stage IN ('sources', 'fit', 'draft', 'review', 'pdf_checks', 'final_review')",
            name="ck_application_generation_runs_stage",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_application_generation_runs_revision"),
        sa.ForeignKeyConstraint(["application_id"], ["stored_applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "application_id",
            "idempotency_key",
            name="uq_application_generation_runs_idempotency",
        ),
    )
    for name in ("owner_id", "application_id", "status", "input_fingerprint", "updated_at"):
        op.create_index(
            op.f(f"ix_application_generation_runs_{name}"),
            "application_generation_runs",
            [name],
            unique=False,
        )

    op.create_table(
        "generation_run_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_generation_run_events_sequence"),
        sa.ForeignKeyConstraint(["run_id"], ["application_generation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_generation_run_events_sequence"),
    )
    _owner_and_run_indexes("generation_run_events")

    op.create_table(
        "generation_run_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=24), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("response_id", sa.String(length=160), nullable=True),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_generation_run_messages_sequence"),
        sa.CheckConstraint(
            "actor IN ('system', 'author', 'reviewer', 'user')",
            name="ck_generation_run_messages_actor",
        ),
        sa.CheckConstraint(
            "role IN ('system', 'user', 'assistant')",
            name="ck_generation_run_messages_role",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["application_generation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_generation_run_messages_sequence"),
    )
    _owner_and_run_indexes("generation_run_messages")

    op.create_table(
        "generation_run_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=True),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("document_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_generation_run_artifacts_version"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["application_generation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "artifact_type", "version", name="uq_generation_run_artifacts_version"
        ),
    )
    _owner_and_run_indexes("generation_run_artifacts")
    op.create_index(
        op.f("ix_generation_run_artifacts_document_id"),
        "generation_run_artifacts",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "generation_run_checks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.Column("check_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'warning')",
            name="ck_generation_run_checks_status",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["generation_run_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["application_generation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _owner_and_run_indexes("generation_run_checks")
    op.create_index(
        op.f("ix_generation_run_checks_artifact_id"),
        "generation_run_checks",
        ["artifact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("generation_run_checks")
    op.drop_table("generation_run_artifacts")
    op.drop_table("generation_run_messages")
    op.drop_table("generation_run_events")
    op.drop_table("application_generation_runs")


def _owner_and_run_indexes(table_name: str) -> None:
    for name in ("owner_id", "run_id"):
        op.create_index(op.f(f"ix_{table_name}_{name}"), table_name, [name], unique=False)
