from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, RectangleObject

from app.models.generation_workflow import CoverLetterDraft, DraftBundle, FitKeyword
from app.models.resume import FinalResume
from app.services import generation_verification
from app.services.generation_latex import CompiledDocument
from app.services.generation_verification import PdfCheck, verify_compiled_document


def _geometry_pdf(
    pages: list[list[tuple[float, float, str]]],
    *,
    crop_box: tuple[float, float, float, float] | None = None,
) -> bytes:
    """Real PDF fixtures with known text positions, independent of TeX/Poppler."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for lines in pages:
        page = writer.add_blank_page(width=595.28, height=841.89)
        if crop_box is not None:
            page.cropbox = RectangleObject(crop_box)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        commands = []
        for x, y, text in lines:
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"BT /F1 10 Tf {x:.2f} {y:.2f} Td ({escaped}) Tj ET")
        content = DecodedStreamObject()
        content.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _geometry_check(tmp_path: Path, pdf: bytes) -> PdfCheck:
    path = tmp_path / "document.pdf"
    path.write_bytes(pdf)
    return generation_verification._layout_check(path)


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


@pytest.mark.parametrize("max_pages, passed", [(2, True), (1, False)])
def test_real_pdf_whitespace_is_advisory_but_page_overflow_still_blocks(
    monkeypatch: pytest.MonkeyPatch, max_pages: int, passed: bool,
) -> None:
    pages = [
        [(71, 775 - 12 * index, "Readable CV text with supported source facts.")
         for index in range(count)]
        for count in (44, 37)
    ]
    pages[0][0] = (71, 775, "Ada Lovelace ada@example.com +41 44 555 01 01")
    for number, lines in enumerate(pages, 1):
        lines.append((520, 70, f"{number}/2"))
    # Only PNG rendering is mocked. PDF parsing, text checks and geometry all
    # exercise the actual artifact, including recognized page-number footers.
    monkeypatch.setattr(generation_verification, "_render_pages", lambda _path, _workdir: (
        (b"page-one", b"page-two"),
        PdfCheck(name="page_images", status="passed", message="Rendered"),
    ))
    verified = verify_compiled_document(
        CompiledDocument(
            document_type="tailored_resume", engine="lualatex", file_name="cv.pdf",
            tex_source="server-owned", pdf=_geometry_pdf(pages), compile_log="ok",
        ),
        bundle=_bundle(), max_pages=max_pages,
    )
    checks = {check.name: check for check in verified.report.checks}
    assert verified.report.passed is passed
    assert checks["layout_geometry"].status == "warning"
    assert [finding["code"] for finding in checks["layout_geometry"].details["findings"]] == [
        "bottom_whitespace", "bottom_whitespace",
    ]
    assert {check.name for check in checks.values() if check.status == "failed"} == (
        set() if passed else {"page_count"}
    )


def test_real_letter_text_within_18mm_margin_has_no_phantom_footer_collision(
    tmp_path: Path,
) -> None:
    # The final lines fall inside the old 90pt footer band but above Roman's
    # actual 18mm bottom margin. This template deliberately has no footer.
    check = _geometry_check(tmp_path, _geometry_pdf([[
        (71, 775 - 12.6 * index, "Readable letter text with no page-number footer.")
        for index in range(57)
    ]]))
    assert check.status == "passed"
    assert check.details["findings"] == []
    assert check.details["pages"][0]["bodyLines"] == 57


def test_real_pdf_internal_whitespace_is_an_explicit_warning(tmp_path: Path) -> None:
    check = _geometry_check(tmp_path, _geometry_pdf([[
        (71, 775, "Candidate heading"), (71, 540, "Readable content after a generous gap."),
    ]]))
    assert check.status == "warning"
    assert check.details["findings"][0]["code"] == "internal_whitespace"


def test_possible_orphan_requires_visual_review_instead_of_geometry_rejection(
    tmp_path: Path,
) -> None:
    check = _geometry_check(tmp_path, _geometry_pdf([
        [(71, 775, "Source content"), (71, 180, "Possible role heading")],
        [(95, 775, "Indented body text continues on the next page.")],
    ]))
    assert check.status == "warning"
    assert any(item["code"] == "possible_orphan_heading"
               and item["severity"] == "warning" for item in check.details["findings"])


@pytest.mark.parametrize("x,y", [(-5, 700), (590, 700), (71, 850), (71, -5)])
def test_real_pdf_text_clipped_at_each_page_edge_still_blocks(
    tmp_path: Path, x: float, y: float,
) -> None:
    check = _geometry_check(tmp_path, _geometry_pdf([[
        (71, 775, "Readable source content"), (x, y, "Clipped content"),
    ]]))
    assert check.status == "failed"
    clipping = next(item for item in check.details["findings"] if item["code"] == "text_clipped")
    assert clipping["severity"] == "failed"
    assert clipping["measurements"]["characterCount"] > 0


def test_real_pdf_cropbox_clipping_is_detected_even_inside_media_box(tmp_path: Path) -> None:
    check = _geometry_check(tmp_path, _geometry_pdf(
        [[(71, 775, "Visible source content"), (20, 700, "Hidden by crop box")]],
        crop_box=(36, 36, 559, 806),
    ))
    assert check.status == "failed"
    assert check.details["findings"][0]["code"] == "text_clipped"


def test_real_pdf_empty_page_is_a_document_failure(tmp_path: Path) -> None:
    check = _geometry_check(tmp_path, _geometry_pdf([[]]))
    assert check.name == "layout_geometry"
    assert check.status == "failed"
    assert check.details["findings"][0]["code"] == "empty_page"


def test_geometry_extractor_failure_is_distinct_from_a_document_defect(tmp_path: Path) -> None:
    check = _geometry_check(tmp_path, b"unreadable PDF data")
    assert check.name == "layout_unavailable"
    assert check.status == "failed"
    assert check.details["available"] is False
    assert str(tmp_path) not in check.message
