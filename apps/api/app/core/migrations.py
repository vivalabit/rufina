from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection

from app.core.database import Base
from app.core.settings import get_settings

API_ROOT = Path(__file__).resolve().parents[2]
LEGACY_BASELINE_REVISION = "20260718_0001"
LEGACY_BASELINE_TABLES = {
    "applied_assistant_actions",
    "candidate_confirmations",
    "candidate_match_snapshots",
    "conversations",
    "document_attachments",
    "document_files",
    "document_generation_provenance",
    "document_pack_jobs",
    "document_templates",
    "document_version_generation_provenance",
    "document_version_validations",
    "document_versions",
    "documents",
    "job_match_feedback",
    "job_matches",
    "messages",
    "profile_versions",
    "profiles",
    "stored_application_events",
    "stored_applications",
    "stored_jobs",
}
LEGACY_BASELINE_COLUMNS = {
    "applied_assistant_actions": {"id", "action_type", "result", "applied_at"},
    "candidate_confirmations": {
        "application_id", "question_id", "requirement", "response", "example_text",
        "blocking", "updated_at",
    },
    "candidate_match_snapshots": {
        "id", "profile_input_hash", "profile_hash", "matcher_version", "source", "data",
        "openclaw_error", "created_at",
    },
    "conversations": {
        "id", "title", "context_kind", "context_id", "openclaw_session_key", "archived",
        "created_at", "updated_at",
    },
    "document_pack_jobs": {
        "id", "request_fingerprint", "application_id", "persistence_mode", "status",
        "document_ids", "stages", "message", "created_at", "updated_at",
    },
    "document_templates": {
        "id", "type", "name", "file_name", "content_type", "content", "extracted_text",
        "created_at", "updated_at",
    },
    "documents": {"id", "type", "title", "job_id", "current_version", "created_at", "updated_at"},
    "job_match_feedback": {"id", "job_id", "profile_hash", "matcher_version", "feedback", "created_at"},
    "job_matches": {
        "id", "job_id", "profile_hash", "matcher_version", "cache_key", "score", "source",
        "confidence", "breakdown", "reasons", "gaps", "heuristic_score", "openclaw_error",
        "created_at",
    },
    "profile_versions": {"id", "profile_id", "data", "reason", "created_at"},
    "profiles": {"id", "data"},
    "stored_application_events": {"id", "application_id", "data"},
    "stored_applications": {"id", "data"},
    "stored_jobs": {"id", "data"},
    "document_attachments": {"id", "document_id", "application_id", "created_at"},
    "document_files": {"id", "document_id", "version", "template_id", "content", "created_at"},
    "document_generation_provenance": {
        "document_id", "generation_fingerprint", "generation_model", "input_versions", "created_at",
    },
    "document_version_generation_provenance": {
        "document_id", "version", "generation_fingerprint", "generation_model", "input_versions",
        "created_at",
    },
    "document_version_validations": {
        "document_id", "version", "factual_report", "visual_report", "diff_items", "created_at",
    },
    "document_versions": {"id", "document_id", "version", "content", "created_at"},
    "messages": {
        "id", "conversation_id", "sequence", "role", "content", "source", "status", "created_at",
    },
}
LEGACY_RECOVERABLE_MISSING_TABLES = {
    "candidate_confirmations",
    "document_generation_provenance",
    "document_pack_jobs",
    "document_version_generation_provenance",
    "document_version_validations",
}


class LegacyDatabaseMismatchError(RuntimeError):
    """Raised when an unversioned database is not the known legacy baseline."""


def get_alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.attributes["database_url"] = database_url or get_settings().database_url
    return config


def restore_known_legacy_baseline_tables(connection: Connection) -> None:
    metadata = sa.MetaData()
    sa.Table("documents", metadata, autoload_with=connection)
    candidate_confirmations = sa.Table(
        "candidate_confirmations",
        metadata,
        sa.Column("application_id", sa.String(length=160), nullable=False),
        sa.Column("question_id", sa.String(length=160), nullable=False),
        sa.Column("requirement", sa.String(length=500), nullable=False),
        sa.Column("response", sa.String(length=16), nullable=False),
        sa.Column("example_text", sa.String(length=1500), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("application_id", "question_id"),
    )
    document_pack_jobs = sa.Table(
        "document_pack_jobs",
        metadata,
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=160), nullable=False),
        sa.Column("persistence_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    sa.Index(
        sa.schema.conv("ix_document_pack_jobs_application_id"),
        document_pack_jobs.c.application_id,
    )
    document_generation_provenance = sa.Table(
        "document_generation_provenance",
        metadata,
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("generation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generation_model", sa.String(length=160), nullable=False),
        sa.Column("input_versions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )
    sa.Index(
        sa.schema.conv(
            "ix_document_generation_provenance_generation_fingerprint"
        ),
        document_generation_provenance.c.generation_fingerprint,
    )
    document_version_generation_provenance = sa.Table(
        "document_version_generation_provenance",
        metadata,
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("generation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generation_model", sa.String(length=160), nullable=False),
        sa.Column("input_versions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "version"),
    )
    sa.Index(
        sa.schema.conv(
            "ix_document_version_generation_provenance_generation_fingerprint"
        ),
        document_version_generation_provenance.c.generation_fingerprint,
    )
    document_version_validations = sa.Table(
        "document_version_validations",
        metadata,
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("factual_report", sa.JSON(), nullable=False),
        sa.Column("visual_report", sa.JSON(), nullable=False),
        sa.Column("diff_items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "version"),
    )
    metadata.create_all(
        connection,
        tables=[
            candidate_confirmations,
            document_pack_jobs,
            document_generation_provenance,
            document_version_generation_provenance,
            document_version_validations,
        ],
    )


def upgrade_database(database_url: str | None = None) -> None:
    resolved_database_url = database_url or get_settings().database_url
    config = get_alembic_config(resolved_database_url)
    engine = create_engine(resolved_database_url)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            table_names = set(inspect(connection).get_table_names())
            has_version_table = "alembic_version" in table_names
            application_tables = table_names - {"alembic_version"}

            if application_tables and not has_version_table:
                missing_tables = LEGACY_BASELINE_TABLES - application_tables
                unexpected_tables = application_tables - LEGACY_BASELINE_TABLES
                recoverable_partial_baseline = (
                    not unexpected_tables
                    and missing_tables == LEGACY_RECOVERABLE_MISSING_TABLES
                )
                if (
                    missing_tables and not recoverable_partial_baseline
                ) or unexpected_tables:
                    missing = sorted(missing_tables)
                    unexpected = sorted(unexpected_tables)
                    details = []
                    if missing:
                        details.append(f"missing tables: {', '.join(missing)}")
                    if unexpected:
                        details.append(f"unexpected tables: {', '.join(unexpected)}")
                    raise LegacyDatabaseMismatchError(
                        "Unversioned database does not match the Rufina legacy baseline"
                        + (f" ({'; '.join(details)})" if details else "")
                    )
                column_mismatches = []
                database_inspector = inspect(connection)
                for table_name, expected_columns in LEGACY_BASELINE_COLUMNS.items():
                    if table_name not in application_tables:
                        continue
                    actual_columns = {
                        column["name"] for column in database_inspector.get_columns(table_name)
                    }
                    if actual_columns != expected_columns:
                        column_mismatches.append(table_name)
                if column_mismatches:
                    raise LegacyDatabaseMismatchError(
                        "Unversioned database does not match the Rufina legacy baseline "
                        f"(column mismatch: {', '.join(sorted(column_mismatches))})"
                    )
                if recoverable_partial_baseline:
                    restore_known_legacy_baseline_tables(connection)
                command.stamp(config, LEGACY_BASELINE_REVISION)

            command.upgrade(config, "head")

            if application_tables and not has_version_table:
                differences = compare_metadata(
                    MigrationContext.configure(
                        connection,
                        opts={"compare_type": True},
                    ),
                    Base.metadata,
                )
                if differences:
                    preview = "; ".join(str(item) for item in differences[:3])
                    raise LegacyDatabaseMismatchError(
                        "Legacy database migration did not produce the expected schema"
                        + (f": {preview}" if preview else "")
                    )
    finally:
        config.attributes.pop("connection", None)
        engine.dispose()
