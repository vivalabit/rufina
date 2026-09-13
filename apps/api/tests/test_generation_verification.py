from types import SimpleNamespace

import pytest

from app.models.generation_workflow import DraftBundle, FitKeyword
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


def test_verification_reports_required_keyword_and_page_failures(
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
    assert failed_names == {"page_count", "keyword:Kubernetes"}
    assert verified.report.passed is False
    assert verified.page_images == (b"png-one", b"png-two")
