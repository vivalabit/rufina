from types import SimpleNamespace

import pytest

from app.models.generation_workflow import CoverLetterDraft, DraftBundle, FitKeyword
from app.models.resume import FinalResume
from app.services import generation_verification
from app.services.generation_latex import CompiledDocument
from app.services.generation_verification import PdfCheck, verify_compiled_document


def _bundle() -> DraftBundle:
    resume = FinalResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "resume-1",
            "masterResumeId": "master-1",
            "targetJobId": "job-1",
            "language": "English",
            "basics": {
                "fullName": "Ada Lovelace",
                "email": "ada@example.com",
                "phone": "+41 44 555 01 01",
            },
            "summary": {"text": "Builds APIs.", "evidenceIds": ["source:one"]},
            "evidence": [{"id": "source:one", "type": "source", "text": "Builds APIs."}],
            "sectionOrder": ["summary"],
        }
    )
    return DraftBundle(resume=resume)


def test_verification_reports_keyword_warning_and_page_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        SimpleNamespace(
            extract_text=lambda: (
                "Ada Lovelace ada@example.com +41 44 555 01 01 builds reliable "
                "platforms and services for enterprise customers."
            )
        ),
        SimpleNamespace(extract_text=lambda: "Second page content remains readable."),
    ]
    monkeypatch.setattr(
        generation_verification,
        "PdfReader",
        lambda _source: SimpleNamespace(pages=pages),
    )
    monkeypatch.setattr(
        generation_verification,
        "_render_pages",
        lambda _path, _workdir: (
            (b"png-one", b"png-two"),
            PdfCheck(name="page_images", status="passed", message="Rendered"),
        ),
    )
    monkeypatch.setattr(
        generation_verification,
        "_layout_check",
        lambda _path: PdfCheck(name="layout_geometry", status="passed", message="Balanced"),
    )
    verified = verify_compiled_document(
        CompiledDocument(
            document_type="tailored_resume",
            engine="lualatex",
            file_name="cv.pdf",
            tex_source="server-owned",
            pdf=b"%PDF-fake",
            compile_log="ok",
        ),
        bundle=_bundle(),
        keywords=(
            FitKeyword(
                term="Kubernetes",
                importance="required",
                support="supported",
                evidenceIds=("source:one",),
            ),
        ),
        max_pages=1,
    )

    failed_names = {check.name for check in verified.report.checks if check.status == "failed"}
    checks = {check.name: check for check in verified.report.checks}
    assert failed_names == {"page_count"}
    assert checks["keyword:Kubernetes"].status == "warning"
    assert checks["keyword:Kubernetes"].details == {
        "importance": "required",
        "support": "supported",
        "present": False,
    }
    assert verified.report.passed is False
    assert verified.page_images == (b"png-one", b"png-two")


def test_cover_letter_does_not_enforce_resume_only_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume = _bundle().resume
    assert resume is not None
    resume_data = resume.model_dump(mode="json", by_alias=True)
    resume_data.update(
        {
            "experiences": [
                {
                    "id": "rewrite:acme",
                    "masterExperienceId": "experience:acme",
                    "company": "Acme AG",
                    "title": "Platform Engineer",
                    "period": "2022 — Present",
                    "bullets": [
                        {
                            "id": "tailored-bullet:acme",
                            "text": "Built reliable platforms.",
                            "evidenceIds": ["source:one"],
                        }
                    ],
                }
            ],
            "sectionOrder": ["summary", "experience"],
        }
    )
    bundle = DraftBundle(
        resume=FinalResume.model_validate(resume_data),
        coverLetter=CoverLetterDraft.model_validate(
            {
                "id": "letter-1",
                "targetJobId": "job-1",
                "language": "English",
                "recipient": "Acme AG",
                "subject": "Platform Engineer",
                "salutation": "Dear hiring team,",
                "paragraphs": [
                    {"text": "I build reliable platforms.", "evidenceIds": ["source:one"]},
                    {"text": "I welcome a conversation.", "evidenceIds": []},
                ],
                "closing": "Kind regards,",
                "signature": "Ada Lovelace",
            }
        ),
    )
    monkeypatch.setattr(
        generation_verification,
        "PdfReader",
        lambda _source: SimpleNamespace(
            pages=[
                SimpleNamespace(
                    extract_text=lambda: (
                        "Ada Lovelace applies for the Platform Engineer role at Acme AG. "
                        "This cover letter remains readable and intentionally omits CV dates."
                    )
                )
            ]
        ),
    )
    monkeypatch.setattr(
        generation_verification,
        "_render_pages",
        lambda _path, _workdir: (
            (b"png-one",),
            PdfCheck(name="page_images", status="passed", message="Rendered"),
        ),
    )
    monkeypatch.setattr(
        generation_verification,
        "_layout_check",
        lambda _path: PdfCheck(name="layout_geometry", status="passed", message="Balanced"),
    )

    verified = verify_compiled_document(
        CompiledDocument(
            document_type="cover_letter",
            engine="xelatex",
            file_name="letter.pdf",
            tex_source="server-owned",
            pdf=b"%PDF-fake",
            compile_log="ok",
        ),
        bundle=bundle,
        keywords=(
            FitKeyword(
                term="Kubernetes",
                importance="required",
                support="supported",
                evidenceIds=("source:one",),
            ),
        ),
        max_pages=1,
    )

    checks = {check.name: check for check in verified.report.checks}
    assert "contact_email" not in checks
    assert "contact_phone" not in checks
    assert not any(name.startswith("role_dates:") for name in checks)
    assert checks["keyword:Kubernetes"].status == "warning"
    assert checks["keyword:Kubernetes"].details["present"] is False
    assert verified.report.passed is True
