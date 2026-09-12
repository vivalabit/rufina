import pytest
from pydantic import ValidationError

from app.models.generation import (
    GeneratedFile,
    GenerationApplicationSnapshot,
    GenerationDocumentResult,
    GenerationError,
    GenerationMasterProfileVersion,
    GenerationRequest,
    GenerationResult,
    GenerationVacancySnapshot,
)
from app.services.document_generator import DocumentGenerator, UnavailableDocumentGenerator


def generation_request() -> GenerationRequest:
    return GenerationRequest(
        application=GenerationApplicationSnapshot(
            id="application-42",
            revision=3,
            data={"status": "draft", "notes": "Prefer a concise application."},
        ),
        vacancy=GenerationVacancySnapshot(
            id="vacancy-7",
            revision=2,
            full_description="Platform Engineer role with complete responsibilities and requirements.",
            data={"title": "Platform Engineer", "company": "Example AG"},
        ),
        master_profile_version=GenerationMasterProfileVersion(
            id="master-profile-1",
            version=4,
            content_sha256="a" * 64,
            data={"name": "Ada", "experience": []},
        ),
        document_types=("tailored_resume", "cover_letter"),
        language="de-CH",
        formatting_parameters={
            "tailored_resume": {"templateId": "swiss-classic", "maxPages": 2},
            "cover_letter": {"templateId": "formal-letter"},
        },
        user_preferences="Keep the cover letter direct and formal.",
    )


def test_request_serializes_the_public_generator_boundary() -> None:
    payload = generation_request().model_dump(mode="json", by_alias=True)

    assert payload == {
        "application": {
            "id": "application-42",
            "revision": 3,
            "data": {"status": "draft", "notes": "Prefer a concise application."},
        },
        "vacancy": {
            "id": "vacancy-7",
            "revision": 2,
            "fullDescription": (
                "Platform Engineer role with complete responsibilities and requirements."
            ),
            "data": {"title": "Platform Engineer", "company": "Example AG"},
        },
        "masterProfileVersion": {
            "id": "master-profile-1",
            "version": 4,
            "contentSha256": "a" * 64,
            "data": {"name": "Ada", "experience": []},
        },
        "documentTypes": ["tailored_resume", "cover_letter"],
        "language": "de-CH",
        "formattingParameters": {
            "tailored_resume": {"templateId": "swiss-classic", "maxPages": 2},
            "cover_letter": {"templateId": "formal-letter"},
        },
        "userPreferences": "Keep the cover letter direct and formal.",
    }


@pytest.mark.parametrize(
    ("snapshot", "field_name"),
    [
        ("application", "aiMatch"),
        ("vacancy", "matchScore"),
        ("master_profile", "generationPlan"),
    ],
)
def test_request_rejects_matching_analysis_and_plans(
    snapshot: str,
    field_name: str,
) -> None:
    request = generation_request()

    with pytest.raises(ValidationError, match="must not contain matching analysis or plans"):
        if snapshot == "application":
            GenerationApplicationSnapshot(
                id=request.application.id,
                revision=request.application.revision,
                data={field_name: {"score": 95}},
            )
        elif snapshot == "vacancy":
            GenerationVacancySnapshot(
                id=request.vacancy.id,
                revision=request.vacancy.revision,
                full_description=request.vacancy.full_description,
                data={field_name: 95},
            )
        else:
            GenerationMasterProfileVersion(
                id=request.master_profile_version.id,
                version=request.master_profile_version.version,
                content_sha256=request.master_profile_version.content_sha256,
                data={field_name: ["Rewrite experience"]},
            )


def test_request_rejects_duplicate_document_types_and_undeclared_inputs() -> None:
    payload = generation_request().model_dump()
    payload["document_types"] = ("cover_letter", "cover_letter")

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        GenerationRequest.model_validate(payload)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GenerationRequest.model_validate({**generation_request().model_dump(), "match_score": 95})


def test_result_keeps_a_separate_outcome_and_file_links_for_each_document() -> None:
    result = GenerationResult(
        execution_id="generation-123",
        state="completed",
        documents=(
            GenerationDocumentResult(
                document_type="tailored_resume",
                state="completed",
                files=(
                    GeneratedFile(
                        file_name="resume.docx",
                        content_type=(
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        download_url="/documents/resume-1/download",
                    ),
                ),
            ),
            GenerationDocumentResult(
                document_type="cover_letter",
                state="failed",
                error=GenerationError(
                    code="render_failed",
                    message="The cover letter could not be rendered.",
                    retryable=True,
                ),
            ),
        ),
    )

    payload = result.model_dump(mode="json", by_alias=True)
    assert payload["state"] == "completed"
    assert payload["documents"][0]["files"][0]["downloadUrl"] == ("/documents/resume-1/download")
    assert payload["documents"][1]["error"] == {
        "code": "render_failed",
        "message": "The cover letter could not be rendered.",
        "retryable": True,
    }


def test_terminal_results_require_files_or_understandable_errors() -> None:
    with pytest.raises(ValidationError, match="must contain at least one file"):
        GenerationDocumentResult(
            document_type="cover_letter",
            state="completed",
        )

    with pytest.raises(ValidationError, match="must contain an error"):
        GenerationDocumentResult(
            document_type="cover_letter",
            state="failed",
        )

    with pytest.raises(ValidationError, match="must contain an error"):
        GenerationResult(
            execution_id="generation-123",
            state="failed",
            documents=(
                GenerationDocumentResult(
                    document_type="cover_letter",
                    state="failed",
                    error=GenerationError(
                        code="render_failed",
                        message="The cover letter could not be rendered.",
                    ),
                ),
            ),
        )


def test_unavailable_generator_is_a_safe_contract_compatible_stub() -> None:
    generator = UnavailableDocumentGenerator(execution_id_factory=lambda: "stub-generation-1")

    assert isinstance(generator, DocumentGenerator)
    result = generator.generate(generation_request())

    assert result.execution_id == "stub-generation-1"
    assert result.state == "failed"
    assert [document.document_type for document in result.documents] == [
        "tailored_resume",
        "cover_letter",
    ]
    assert all(document.state == "failed" for document in result.documents)
    assert all(document.files == () for document in result.documents)
    assert result.error == GenerationError(
        code="generator_unavailable",
        message="Document generation is not configured yet.",
        retryable=False,
    )
