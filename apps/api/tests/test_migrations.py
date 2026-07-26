import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app import main as main_module
from app.core.database import Base
from app.core.migrations import (
    LegacyDatabaseMismatchError,
    get_alembic_config,
    upgrade_database,
)


def test_baseline_migration_matches_current_schema(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'baseline.sqlite'}"

    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert table_names == {*Base.metadata.tables, "alembic_version"}
        template_constraints = inspect(engine).get_unique_constraints(
            "document_templates"
        )
        assert {
            tuple(constraint["column_names"])
            for constraint in template_constraints
        } == {("owner_id", "type", "content_sha256")}
        pack_indexes = inspect(engine).get_indexes("document_pack_jobs")
        assert any(index["column_names"] == ["expires_at"] for index in pack_indexes)
        pack_foreign_keys = inspect(engine).get_foreign_keys("document_pack_jobs")
        assert [
            (
                foreign_key["constrained_columns"],
                foreign_key["referred_table"],
                foreign_key["referred_columns"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in pack_foreign_keys
        ] == [(["application_id"], "stored_applications", ["id"], "CASCADE")]
        artifact_foreign_keys = inspect(engine).get_foreign_keys(
            "document_validation_artifacts"
        )
        assert all(
            len(foreign_key["name"]) <= 63
            for foreign_key in artifact_foreign_keys
            if foreign_key["name"]
        )
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in artifact_foreign_keys
            } == {
                (("application_id",), "stored_applications", ("id",), "CASCADE"),
                (
                    ("generation_artifact_id",),
                    "document_generation_artifacts",
                    ("id",),
                    "CASCADE",
                ),
                (("template_id",), "document_templates", ("id",), "CASCADE"),
            }
        artifact_indexes = inspect(engine).get_indexes("document_validation_artifacts")
        assert {tuple(index["column_names"]) for index in artifact_indexes} >= {
            ("expires_at",),
            ("template_id",),
        }
        snapshot_indexes = inspect(engine).get_indexes("candidate_match_snapshots")
        assert any(
            index["column_names"]
            == ["profile_input_hash", "matcher_version", "source", "model"]
            for index in snapshot_indexes
        )
        privacy_columns = {
            column["name"] for column in inspect(engine).get_columns("ai_privacy_settings")
        }
        assert "consent_backend" in privacy_columns
        resume_template_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "resume_template_definitions"
            )
        }
        assert resume_template_columns == {
            "id",
            "owner_id",
            "name",
            "base_template_id",
            "design_json",
            "version",
            "content_sha256",
            "created_at",
            "updated_at",
        }
        with engine.connect() as connection:
            definition_count = connection.execute(
                text("SELECT COUNT(*) FROM resume_template_definitions")
            ).scalar_one()
        assert definition_count == 0
        owner_tables = {
            "stored_applications",
            "stored_application_events",
            "candidate_confirmations",
            "documents",
            "document_pack_jobs",
            "document_validation_artifacts",
            "document_templates",
            "workspace_source_documents",
            "conversations",
            "applied_assistant_actions",
            "job_matches",
            "job_match_feedback",
            "candidate_match_snapshots",
            "stored_jobs",
            "job_search_configs",
            "job_search_schedules",
            "job_search_runs",
            "job_screening_decisions",
            "resume_masters",
            "resume_master_versions",
            "resume_source_files",
            "senior_recruiter_analyses",
            "experience_rewrites",
            "ats_final_reviews",
            "resume_tailoring_runs",
            "resume_tailoring_stages",
            "resume_template_definitions",
        }
        for table_name in owner_tables:
            owner_column = next(
                column
                for column in inspect(engine).get_columns(table_name)
                if column["name"] == "owner_id"
            )
            assert owner_column["nullable"] is False
            assert any(
                index["column_names"] == ["owner_id"]
                for index in inspect(engine).get_indexes(table_name)
            )

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == "20260726_0028"
        assert inspect(engine).get_pk_constraint("stored_jobs")["constrained_columns"] == [
            "owner_id",
            "id",
        ]
        stored_job_columns = {
            column["name"]
            for column in inspect(engine).get_columns("stored_jobs")
        }
        assert stored_job_columns >= {
            "search_config_id",
            "search_config_version",
            "screening_config_hash",
            "screening_config_snapshot",
        }
        automatic_run_indexes = {
            index["name"]: index
            for index in inspect(engine).get_indexes("job_search_runs")
        }
        automatic_run_index = automatic_run_indexes[
            "uq_job_search_runs_automatic_schedule_time"
        ]
        assert automatic_run_index["column_names"] == [
            "schedule_id",
            "scheduled_for",
        ]
        assert automatic_run_index["unique"] == 1
        screening_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "job_screening_decisions"
            )
        }
        assert screening_columns == {
            "id",
            "job_id",
            "search_config_id",
            "vacancy_hash",
            "config_hash",
            "decision",
            "reason_code",
            "reason",
            "matched_rule_ids",
            "model",
            "prompt_version",
            "title",
            "company",
            "source_url",
            "vacancy_data",
            "invalidated_at",
            "manually_allowed_at",
            "created_at",
            "owner_id",
        }
        screening_indexes = {
            index["name"]: index
            for index in inspect(engine).get_indexes(
                "job_screening_decisions"
            )
        }
        assert screening_indexes[
            "ix_job_screening_decisions_cache"
        ]["column_names"] == [
            "owner_id",
            "vacancy_hash",
            "config_hash",
            "model",
            "prompt_version",
        ]
        resume_master_columns = {
            column["name"]
            for column in inspect(engine).get_columns("resume_masters")
        }
        resume_version_columns = {
            column["name"]
            for column in inspect(engine).get_columns("resume_master_versions")
        }
        resume_source_columns = {
            column["name"]
            for column in inspect(engine).get_columns("resume_source_files")
        }
        assert "content" not in resume_master_columns
        assert "content" not in resume_version_columns
        assert {"data", "source_file_id", "content_sha256"} <= resume_version_columns
        assert {
            "content",
            "content_type",
            "content_sha256",
            "draft_resume_id",
            "extraction",
        } <= resume_source_columns
        resume_master_id_column = next(
            column
            for column in inspect(engine).get_columns("resume_source_files")
            if column["name"] == "resume_master_id"
        )
        assert resume_master_id_column["nullable"] is True
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspect(engine).get_foreign_keys(
                "resume_master_versions"
            )
        } == {
            (("resume_master_id",), "resume_masters", "CASCADE"),
            (("source_file_id",), "resume_source_files", "SET NULL"),
        }
        document_file_columns = {
            column["name"]
            for column in inspect(engine).get_columns("document_files")
        }
        assert document_file_columns >= {
            "file_name",
            "content_type",
            "renderer_template_id",
            "renderer_template_version",
            "renderer_design_sha256",
            "source_ats_final_review_id",
            "final_resume_json",
            "stage_results",
            "provenance",
        }
        assert (
            "source_ats_final_review_id",
            "renderer_template_id",
            "renderer_template_version",
            "renderer_design_sha256",
        ) in {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(
                "document_files"
            )
        }
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspect(engine).get_foreign_keys(
                "document_files"
            )
        } >= {
            (
                ("source_ats_final_review_id",),
                "ats_final_reviews",
                "SET NULL",
            ),
        }
        run_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "resume_tailoring_runs"
            )
        }
        assert run_columns >= {
            "resume_master_id",
            "resume_master_version_id",
            "target_job_id",
            "status",
            "current_stage",
            "error",
            "completed_at",
        }
        stage_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "resume_tailoring_stages"
            )
        }
        assert stage_columns >= {
            "run_id",
            "stage_number",
            "request_type",
            "input_fingerprint",
            "structured_output",
            "output_record_id",
            "model",
            "backend",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "token_count_source",
            "status",
            "error",
            "attempt",
            "completed_at",
        }
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspect(engine).get_foreign_keys(
                "resume_tailoring_stages"
            )
        } == {
            (("run_id",), "resume_tailoring_runs", "CASCADE"),
        }
        ats_review_columns = {
            column["name"]
            for column in inspect(engine).get_columns("ats_final_reviews")
        }
        assert ats_review_columns >= {
            "experience_rewrite_id",
            "resume_master_id",
            "resume_master_version_id",
            "target_job_id",
            "prompt_version",
            "result",
            "render_input",
            "model",
            "backend",
            "provider_session_id",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "token_count_source",
            "latency_ms",
        }
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspect(engine).get_foreign_keys(
                "ats_final_reviews"
            )
        } == {
            (
                ("experience_rewrite_id",),
                "experience_rewrites",
                "CASCADE",
            ),
            (("resume_master_id",), "resume_masters", "CASCADE"),
            (
                ("resume_master_version_id",),
                "resume_master_versions",
                "CASCADE",
            ),
        }
        recruiter_analysis_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "senior_recruiter_analyses"
            )
        }
        assert recruiter_analysis_columns >= {
            "resume_master_id",
            "resume_master_version_id",
            "target_job_id",
            "vacancy_hash",
            "prompt_version",
            "result",
            "model",
            "backend",
            "provider_session_id",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "token_count_source",
            "latency_ms",
        }
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspect(engine).get_foreign_keys(
                "senior_recruiter_analyses"
            )
        } == {
            (("resume_master_id",), "resume_masters", "CASCADE"),
            (
                ("resume_master_version_id",),
                "resume_master_versions",
                "CASCADE",
            ),
        }
        experience_rewrite_columns = {
            column["name"]
            for column in inspect(engine).get_columns("experience_rewrites")
        }
        assert experience_rewrite_columns >= {
            "senior_recruiter_analysis_id",
            "resume_master_id",
            "resume_master_version_id",
            "target_job_id",
            "prompt_version",
            "original_experiences",
            "result",
            "links",
            "model",
            "backend",
            "provider_session_id",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "token_count_source",
            "latency_ms",
        }
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspect(engine).get_foreign_keys(
                "experience_rewrites"
            )
        } == {
            (
                ("senior_recruiter_analysis_id",),
                "senior_recruiter_analyses",
                "CASCADE",
            ),
            (("resume_master_id",), "resume_masters", "CASCADE"),
            (
                ("resume_master_version_id",),
                "resume_master_versions",
                "CASCADE",
            ),
        }
        run_columns = {
            column["name"]
            for column in inspect(engine).get_columns("job_search_runs")
        }
        assert run_columns >= {
            "jobs_found",
            "jobs_already_known",
            "jobs_screened",
            "jobs_passed",
            "jobs_rejected",
            "jobs_uncertain",
            "jobs_added",
            "jobs_analyzed",
            "screening_errors",
            "warning",
        }
    finally:
        engine.dispose()

    command.check(get_alembic_config(database_url))


def test_upgrade_database_can_run_again_at_head(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'repeat.sqlite'}"

    upgrade_database(database_url)
    upgrade_database(database_url)


def test_screening_persistence_migration_backfills_run_statistics(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'screening-persistence.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260723_0015")
    now = datetime.now(UTC).isoformat()

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job_search_runs "
                    "(id, schedule_id, run_type, scheduled_for, config_snapshot, "
                    "sources, status, jobs_found, jobs_added, source_errors, "
                    "started_at, completed_at, owner_id) VALUES "
                    "('legacy-run', NULL, 'manual', NULL, '{}', '[]', "
                    "'completed', 8, 3, '{}', :now, :now, 'legacy-owner')"
                ),
                {"now": now},
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT jobs_found, jobs_already_known, jobs_screened, "
                    "jobs_passed, jobs_rejected, jobs_uncertain, jobs_added, "
                    "jobs_analyzed, screening_errors "
                    "FROM job_search_runs WHERE id = 'legacy-run'"
                )
            ).one()
        assert tuple(row) == (8, 5, 0, 0, 0, 0, 3, 0, 0)
        assert "job_screening_decisions" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_backend_aware_consent_migration_preserves_openclaw_consent(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'backend-consent.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260722_0012")
    now = datetime.now(UTC).isoformat()

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ai_privacy_settings "
                    "(owner_id, consent_version, consented_at, retention_days, updated_at) "
                    "VALUES ('consented-owner', 'privacy-v1', :now, 30, :now), "
                    "('revoked-owner', NULL, NULL, 30, :now)"
                ),
                {"now": now},
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = dict(
                connection.execute(
                    text(
                        "SELECT owner_id, consent_backend FROM ai_privacy_settings "
                        "ORDER BY owner_id"
                    )
                ).all()
            )
        assert rows == {
            "consented-owner": "openclaw_codex",
            "revoked-owner": None,
        }
    finally:
        engine.dispose()


def test_backend_neutral_provenance_migration_preserves_legacy_ai_data(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'backend-provenance.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260722_0010")
    now = datetime.now(UTC).isoformat()

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO conversations "
                    "(id, title, context_kind, context_id, openclaw_session_key, archived, "
                    "created_at, updated_at, owner_id) VALUES "
                    "('legacy-chat', 'Legacy', 'profile', '', 'legacy-session', 0, :now, :now, "
                    "'local-owner')"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, sequence, role, content, source, status, created_at) "
                    "VALUES ('legacy-message', 'legacy-chat', 0, 'assistant', 'hello', "
                    "'openclaw', 'complete', :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO candidate_match_snapshots "
                    "(id, profile_input_hash, profile_hash, matcher_version, source, data, "
                    "openclaw_error, created_at, owner_id) VALUES "
                    "('legacy-snapshot', :hash, :hash, 'ai-match-v3', 'openclaw', '{}', "
                    "'snapshot error', :now, 'local-owner')"
                ),
                {"hash": "a" * 64, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO job_matches "
                    "(id, job_id, profile_hash, vacancy_hash, model, prompt_version, "
                    "matcher_version, cache_key, score, source, confidence, breakdown, reasons, "
                    "gaps, heuristic_score, openclaw_error, created_at, owner_id) VALUES "
                    "('legacy-match', 'job', :hash, :hash, 'legacy-model', 'prompt-v1', "
                    "'ai-match-v3', :hash, 80, 'openclaw', 'high', '{}', '[]', '[]', 75, "
                    "'match error', :now, 'local-owner')"
                ),
                {"hash": "b" * 64, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO documents "
                    "(id, type, title, job_id, current_version, created_at, updated_at, owner_id) "
                    "VALUES ('legacy-document', 'tailored_resume', 'Legacy document', NULL, 1, "
                    ":now, :now, 'local-owner')"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO document_generation_provenance "
                    "(document_id, generation_fingerprint, generation_model, input_versions, "
                    "created_at) VALUES ('legacy-document', :hash, 'legacy-model', '{}', :now)"
                ),
                {"hash": "c" * 64, "now": now},
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        columns = {
            table: {column["name"] for column in inspect(engine).get_columns(table)}
            for table in ("conversations", "candidate_match_snapshots", "job_matches")
        }
        assert "provider_session_id" in columns["conversations"]
        assert "openclaw_session_key" not in columns["conversations"]
        assert "provider_error" in columns["candidate_match_snapshots"]
        assert "model" in columns["candidate_match_snapshots"]
        assert "provider_error" in columns["job_matches"]
        assert "backend" in columns["job_matches"]
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT provider_session_id FROM conversations WHERE id = 'legacy-chat'")
            ).scalar_one() == "legacy-session"
            assert connection.execute(
                text("SELECT source FROM messages WHERE id = 'legacy-message'")
            ).scalar_one() == "openclaw_codex"
            assert connection.execute(
                text(
                    "SELECT source, model, provider_error FROM candidate_match_snapshots "
                    "WHERE id = 'legacy-snapshot'"
                )
            ).one() == ("openclaw_codex", "legacy", "snapshot error")
            assert connection.execute(
                text(
                    "SELECT source, backend, provider_error FROM job_matches "
                    "WHERE id = 'legacy-match'"
                )
            ).one() == ("openclaw_codex", "openclaw_codex", "match error")
            assert connection.execute(
                text(
                    "SELECT generation_backend FROM document_generation_provenance "
                    "WHERE document_id = 'legacy-document'"
                )
            ).scalar_one() == "openclaw_codex"
    finally:
        engine.dispose()


def test_storage_foreign_key_migration_removes_existing_orphans(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'storage-orphans.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260719_0004")
    now = datetime.now(UTC)

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO stored_applications (id, data) "
                    "VALUES ('legacy-application', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO document_templates "
                    "(id, type, name, file_name, content_type, content, extracted_text, "
                    "created_at, updated_at, content_sha256) "
                    "VALUES ('legacy-template', 'tailored_resume', 'Legacy', 'legacy.docx', "
                    "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', "
                    ":content, '', :created_at, :updated_at, :content_sha256)"
                ),
                {
                    "content": b"legacy-template",
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "content_sha256": "f" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO document_pack_jobs "
                    "(id, request_fingerprint, application_id, persistence_mode, status, "
                    "document_ids, stages, message, created_at, updated_at, expires_at) "
                    "VALUES (:id, :fingerprint, :application_id, 'atomic', 'completed', "
                    "'[]', '[]', '', :created_at, :updated_at, :expires_at)"
                ),
                {
                    "id": "orphan-pack",
                    "fingerprint": "a" * 64,
                    "application_id": "missing-application",
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=1)).isoformat(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO document_validation_artifacts "
                    "(id, application_id, document_type, template_id, template_hash, "
                    "result_hash, evidence_hash, rendered_hash, rendered_content, "
                    "validation_report, consumed_at, expires_at, created_at) "
                    "VALUES (:id, :application_id, 'tailored_resume', :template_id, "
                    ":template_hash, :result_hash, :evidence_hash, :rendered_hash, "
                    ":rendered_content, '{}', NULL, :expires_at, :created_at)"
                ),
                {
                    "id": "orphan-artifact",
                    "application_id": "missing-application",
                    "template_id": "missing-template",
                    "template_hash": "b" * 64,
                    "result_hash": "c" * 64,
                    "evidence_hash": "d" * 64,
                    "rendered_hash": "e" * 64,
                    "rendered_content": b"rendered",
                    "expires_at": (now + timedelta(minutes=30)).isoformat(),
                    "created_at": now.isoformat(),
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM document_pack_jobs")
            ).scalar_one() == 0
            assert connection.execute(
                text("SELECT COUNT(*) FROM document_validation_artifacts")
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    "SELECT owner_id FROM stored_applications "
                    "WHERE id = 'legacy-application'"
                )
            ).scalar_one() == "local-owner"
            assert connection.execute(
                text(
                    "SELECT owner_id FROM document_templates "
                    "WHERE id = 'legacy-template'"
                )
            ).scalar_one() == "local-owner"
    finally:
        engine.dispose()


def test_upgrade_database_bootstraps_legacy_baseline(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260718_0001")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()

    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == "20260726_0028"
    finally:
        engine.dispose()
    command.check(get_alembic_config(database_url))


def test_job_soft_delete_migration_preserves_existing_jobs(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'job-soft-delete.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260720_0009")

    engine = create_engine(database_url)
    original_data = '{"id":"legacy-job","title":"Legacy vacancy"}'
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO stored_jobs (id, data) VALUES ('legacy-job', :data)"),
                {"data": original_data},
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT owner_id, data, status, dismissed_at, "
                    "search_config_id, search_config_version, "
                    "screening_config_hash, screening_config_snapshot "
                    "FROM stored_jobs "
                    "WHERE id = 'legacy-job'"
                )
            ).one()
            assert row.owner_id == "local-owner"
            assert row.status == "active"
            assert row.dismissed_at is None
            assert row.data == original_data
            assert row.search_config_id is None
            assert row.search_config_version is None
            assert row.screening_config_hash is None
            assert row.screening_config_snapshot is None
    finally:
        engine.dispose()


def test_job_owner_scoping_migration_backfills_and_allows_shared_ids(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'job-owner-scoping.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260722_0013")
    now = datetime.now(UTC).isoformat()

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO stored_jobs (id, data, status) "
                    "VALUES ('shared-job', :data, 'active')"
                ),
                {"data": '{"id":"shared-job","title":"Legacy vacancy"}'},
            )
            connection.execute(
                text(
                    "INSERT INTO job_match_feedback "
                    "(id, job_id, profile_hash, matcher_version, feedback, created_at) "
                    "VALUES ('legacy-feedback', 'shared-job', :profile_hash, "
                    "'ai-match-v3', 'good_match', :created_at)"
                ),
                {"profile_hash": "a" * 64, "created_at": now},
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert inspector.get_pk_constraint("stored_jobs")["constrained_columns"] == [
            "owner_id",
            "id",
        ]
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO stored_jobs (owner_id, id, data, status) "
                    "VALUES ('owner-b', 'shared-job', :data, 'active')"
                ),
                {"data": '{"id":"shared-job","title":"Owner B vacancy"}'},
            )
            jobs = connection.execute(
                text(
                    "SELECT owner_id, data FROM stored_jobs "
                    "WHERE id = 'shared-job' ORDER BY owner_id"
                )
            ).all()
            feedback_owner = connection.execute(
                text(
                    "SELECT owner_id FROM job_match_feedback "
                    "WHERE id = 'legacy-feedback'"
                )
            ).scalar_one()

        assert [row.owner_id for row in jobs] == ["local-owner", "owner-b"]
        assert feedback_owner == "local-owner"
    finally:
        engine.dispose()

    command.downgrade(config, "20260722_0013")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert inspector.get_pk_constraint("stored_jobs")["constrained_columns"] == ["id"]
        assert "owner_id" not in {
            column["name"] for column in inspector.get_columns("job_match_feedback")
        }
        with engine.connect() as connection:
            retained_job = connection.execute(
                text("SELECT data FROM stored_jobs WHERE id = 'shared-job'")
            ).scalar_one()
        assert retained_job == '{"id":"shared-job","title":"Legacy vacancy"}'
    finally:
        engine.dispose()


def test_upgrade_database_rejects_unknown_unversioned_schema(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'unknown.sqlite'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)"))
    finally:
        engine.dispose()

    with pytest.raises(
        LegacyDatabaseMismatchError,
        match="unexpected tables: unrelated",
    ):
        upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        assert "alembic_version" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_upgrade_database_rolls_back_mismatched_legacy_schema(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'mismatched-legacy.sqlite'}"
    command.upgrade(get_alembic_config(database_url), "20260718_0001")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
            connection.execute(text("ALTER TABLE profiles DROP COLUMN data"))
    finally:
        engine.dispose()

    with pytest.raises(
        LegacyDatabaseMismatchError,
        match="column mismatch: profiles",
    ):
        upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        assert "alembic_version" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_lifespan_propagates_database_initialization_error(monkeypatch) -> None:
    def fail_upgrade() -> None:
        raise SQLAlchemyError("database initialization failed")

    monkeypatch.setattr(main_module, "upgrade_database", fail_upgrade)

    async def start_application() -> None:
        async with main_module.lifespan(main_module.app):
            pass

    with pytest.raises(SQLAlchemyError, match="database initialization failed"):
        asyncio.run(start_application())


def test_lifespan_starts_and_stops_scheduled_expiration_cleanup(monkeypatch) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()
    worker_started = asyncio.Event()
    worker_stopped = asyncio.Event()

    async def scheduled_cleanup(interval_seconds: int) -> None:
        assert interval_seconds == main_module.settings.storage_cleanup_interval_seconds
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    async def scheduled_job_search(
        interval_seconds: float,
        *,
        settings,
        stop_event: asyncio.Event,
    ) -> None:
        assert interval_seconds == settings.job_search_poll_interval_seconds
        worker_started.set()
        await stop_event.wait()
        worker_stopped.set()

    monkeypatch.setattr(main_module, "upgrade_database", lambda: None)
    monkeypatch.setattr(main_module, "run_expiration_cleanup", scheduled_cleanup)
    monkeypatch.setattr(main_module, "run_job_search_worker", scheduled_job_search)

    async def start_application() -> None:
        async with main_module.lifespan(main_module.app):
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.wait_for(worker_started.wait(), timeout=1)
        await asyncio.wait_for(stopped.wait(), timeout=1)
        await asyncio.wait_for(worker_stopped.wait(), timeout=1)

    asyncio.run(start_application())
