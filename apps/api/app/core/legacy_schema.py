"""Database objects retained only for upgrade and downgrade compatibility."""

LEGACY_PREPARATION_TABLES = frozenset(
    {
        "application_preferences",
        "ats_final_reviews",
        "candidate_confirmations",
        "document_generation_artifacts",
        "document_generation_provenance",
        "document_pack_jobs",
        "document_validation_artifacts",
        "document_version_generation_provenance",
        "document_version_validations",
        "experience_rewrites",
        "imaginator_resumes",
        "resume_tailoring_runs",
        "resume_tailoring_stages",
        "senior_recruiter_analyses",
    }
)

LEGACY_DOCUMENT_FILE_COLUMNS = frozenset(
    {
        "final_resume_json",
        "provenance",
        "source_ats_final_review_id",
        "source_imaginator_resume_id",
        "stage_results",
    }
)

LEGACY_DOCUMENT_FILE_SCHEMA_OBJECTS = frozenset(
    {
        "ck_document_files_single_resume_pipeline_source",
        "fk_document_files_ats_final_review",
        "fk_document_files_imaginator_resume",
        "ix_document_files_source_ats_final_review_id",
        "ix_document_files_source_imaginator_resume_id",
        "uq_document_files_imaginator_resume_pdf_source",
        "uq_document_files_resume_pdf_source",
    }
)


def include_current_schema_object(
    object_,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to,
) -> bool:
    """Ignore retained legacy storage that has no runtime model."""
    if reflected and type_ == "table" and name in LEGACY_PREPARATION_TABLES:
        return False
    table = getattr(object_, "table", None)
    if reflected and getattr(table, "name", None) == "document_files":
        if type_ == "column" and name in LEGACY_DOCUMENT_FILE_COLUMNS:
            return False
        if name in LEGACY_DOCUMENT_FILE_SCHEMA_OBJECTS:
            return False
    return True
