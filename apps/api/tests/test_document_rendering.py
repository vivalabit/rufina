from datetime import date
from io import BytesIO

import pytest
from docx import Document
from pydantic import ValidationError
from tailoring_fixtures import cover_letter_payload, final_resume

from app.models.generation_workflow import CoverLetterDraft
from app.models.resume import RewrittenBullet
from app.services.document_docx import build_cover_letter_docx, build_resume_docx
from app.services.document_rendering import (
    DEFAULT_DOCUMENT_TEMPLATE_ID,
    DocumentRenderError,
    droppable_statement_ids,
    extract_pdf_text,
    format_letter_date,
    list_document_templates,
    normalize_document_template_id,
    pdf_page_count,
    render_cover_letter,
    render_resume_to_fit,
    resolve_document_template,
    without_statements,
)
from app.services.resume_emphasis import emphasis_segments, valid_emphasis
from app.services.resume_pdf_renderer import (
    ChromiumPdfSession,
    resume_view_model,
    skill_group_view,
)


def test_gallery_lists_the_default_template_first_and_flags_ats_safety() -> None:
    templates = list_document_templates()

    assert templates[0].id == DEFAULT_DOCUMENT_TEMPLATE_ID == "swiss_classic"
    assert templates[0].is_default is True
    assert [template.is_default for template in templates[1:]] == [False] * 4
    assert {template.id for template in templates if not template.ats_safe} == {
        "modern_two_column"
    }


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        (None, "swiss_classic"),
        ("  ", "swiss_classic"),
        ("roman", "swiss_classic"),
        ("ishchenko_classic", "swiss_classic"),
        ("moderncv_banking", "modern_single"),
        ("classic_single", "classic_single"),
    ],
)
def test_template_ids_saved_by_earlier_versions_stay_usable(
    saved: str | None, expected: str
) -> None:
    assert normalize_document_template_id(saved) == expected
    assert resolve_document_template(saved).id == expected


def test_unknown_template_is_rejected_with_a_stable_code() -> None:
    with pytest.raises(DocumentRenderError) as error:
        resolve_document_template("missing-template")

    assert error.value.code == "document_template_unsupported"


def test_emphasis_marks_metrics_and_known_technologies() -> None:
    segments = emphasis_segments(
        "Cut latency by 40% for 10,000+ users within 3 months using FastAPI in 2025.",
        technologies=["FastAPI", "API"],
    )

    assert [segment.text for segment in segments if segment.strong] == [
        "40%",
        "10,000+",
        "3 months",
        "FastAPI",
    ]
    assert "".join(segment.text for segment in segments).endswith("in 2025.")


def test_explicit_emphasis_replaces_the_automatic_choice() -> None:
    text = "Built a Python automation tool that saved 5,000 hours."

    segments = emphasis_segments(
        text, explicit=["Python automation tool", "not present"], technologies=["Python"]
    )

    assert [segment.text for segment in segments if segment.strong] == ["Python automation tool"]
    assert valid_emphasis(text, ["5,000 hours", "missing", "Python automation tool"]) == [
        "Python automation tool",
        "5,000 hours",
    ]


def test_tailored_bullet_rejects_emphasis_outside_its_text() -> None:
    bullet = RewrittenBullet(
        id="bullet-1", text="Built APIs with FastAPI.", evidenceIds=["source:a"], emphasis=["FastAPI"]
    )
    assert bullet.emphasis == ["FastAPI"]

    with pytest.raises(ValidationError, match="emphasis phrases must occur in the text"):
        RewrittenBullet(
            id="bullet-1", text="Built APIs.", evidenceIds=["source:a"], emphasis=["Kafka"]
        )


def test_view_model_exposes_segments_for_every_statement() -> None:
    view = resume_view_model(final_resume())

    first_bullet = view["experiences"][0]["bullets"][0]
    assert "".join(segment["text"] for segment in first_bullet["segments"]) == first_bullet["text"]
    assert {"text": "40%", "strong": True} in first_bullet["segments"]
    assert view["education"][0]["details"][0]["segments"]


def test_optional_statements_are_dropped_in_order_but_every_role_keeps_one() -> None:
    resume = final_resume()
    atlas = [bullet.id for bullet in resume.experiences[0].bullets]
    borealis = [bullet.id for bullet in resume.experiences[1].bullets]

    droppable = droppable_statement_ids(resume, [*reversed(atlas), "unknown", *borealis])

    assert droppable == [*reversed(atlas[1:]), *borealis[:2]]
    trimmed = without_statements(resume, droppable)
    assert [len(experience.bullets) for experience in trimmed.experiences] == [1, 1]
    assert {item.id for item in trimmed.evidence} < {item.id for item in resume.evidence}


def test_resume_is_fitted_to_one_page_by_dropping_the_lowest_value_statements() -> None:
    resume = final_resume(extra_bullets_per_role=14)
    template = resolve_document_template("swiss_classic")
    # Filler statements first, then the genuine ones from the end of each role.
    drop_order = [
        bullet.id
        for experience in resume.experiences
        for bullet in reversed(experience.bullets)
        if "internal tool" in bullet.text
    ]

    with ChromiumPdfSession() as session:
        unconstrained = render_resume_to_fit(
            resume, template=template, max_pages=3, session=session
        )
        fitted = render_resume_to_fit(
            resume, template=template, max_pages=1, drop_order=drop_order, session=session
        )
        oversized = final_resume(extra_bullets_per_role=16)
        impossible = render_resume_to_fit(
            oversized, template=template, max_pages=1, session=session
        )

    assert unconstrained.document.page_count == 2
    assert unconstrained.document.dropped_statement_ids == ()
    assert fitted.document.page_count == 1
    assert 0 < len(fitted.document.dropped_statement_ids) < len(drop_order)
    assert fitted.document.dropped_statement_ids == tuple(
        drop_order[: len(fitted.document.dropped_statement_ids)]
    )
    assert fitted.document.ats_readable, fitted.document.text_check_error
    assert fitted.document.template_id == "swiss_classic"
    assert "Cut report generation time by 40%" in " ".join(
        extract_pdf_text(fitted.document.pdf).split()
    )
    kept = {bullet.id for experience in fitted.resume.experiences for bullet in experience.bullets}
    assert kept.isdisjoint(fitted.document.dropped_statement_ids)
    # Without anything droppable the complete document is returned at full size.
    assert impossible.document.page_count > 1
    assert impossible.document.fit_scale == 1.0
    assert impossible.resume == oversized


@pytest.mark.parametrize(
    "template_id",
    ["swiss_classic", "classic_single", "modern_single", "swiss_local_german", "modern_two_column"],
)
def test_one_resume_renders_in_every_gallery_template(template_id: str) -> None:
    rendered = render_resume_to_fit(
        final_resume(), template=resolve_document_template(template_id), max_pages=2
    )

    assert rendered.document.pdf.startswith(b"%PDF-")
    assert rendered.document.page_count <= 2
    assert rendered.document.template_id == template_id
    assert "Mira Keller" in extract_pdf_text(rendered.document.pdf)


def test_cover_letter_matches_the_resume_design_and_stays_on_one_page() -> None:
    resume = final_resume()
    letter = CoverLetterDraft.model_validate(cover_letter_payload())

    rendered = render_cover_letter(
        letter,
        sender=resume.basics,
        letter_date=date(2026, 11, 3),
        template=resolve_document_template("swiss_classic"),
    )

    text = " ".join(extract_pdf_text(rendered.pdf).split())
    assert rendered.document_type == "cover_letter"
    assert rendered.page_count == pdf_page_count(rendered.pdf) == 1
    assert rendered.ats_readable, rendered.text_check_error
    assert "Zurich, 3 November 2026" in text
    assert "Northwind Analytics AG Hiring Team" in text
    assert text.index("Dear Hiring Team,") < text.index("Kind regards,") < text.rindex("Mira Keller")


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "1 March 2026"), ("German", "1. März 2026"), ("fr", "1er mars 2026")],
)
def test_letter_date_follows_the_document_language(language: str, expected: str) -> None:
    assert format_letter_date(date(2026, 3, 1), language) == expected


def test_resume_docx_is_built_from_structured_content_in_the_template_style() -> None:
    content = build_resume_docx(
        final_resume(), template=resolve_document_template("swiss_classic")
    )

    document = Document(BytesIO(content))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    assert paragraphs[0] == "Mira Keller"
    assert "Experience" in paragraphs
    assert "Backend Developer\t06/2025 – Present" in paragraphs
    assert "Atlas Data GmbH\tZurich" in paragraphs
    assert "English: Fluent (C1)      German: Intermediate (B1)" in paragraphs
    assert "Languages: Python, TypeScript, SQL" in paragraphs
    assert document.styles["Normal"].font.name == "Times New Roman"
    bullet = next(paragraph for paragraph in document.paragraphs if "40%" in paragraph.text)
    assert bullet.style.name == "List Bullet"
    assert [run.text for run in bullet.runs if run.bold] == ["40%", "Python", "FastAPI", "PostgreSQL"]
    assert not document.tables
    relationships = [rel.target_ref for rel in document.part.rels.values() if rel.is_external]
    assert "https://github.com/mira-keller-example" in relationships


def test_sans_template_docx_uses_an_installed_font_fallback() -> None:
    content = build_resume_docx(
        final_resume(), template=resolve_document_template("modern_single")
    )

    document = Document(BytesIO(content))
    assert document.styles["Normal"].font.name == "Arial"
    assert "EXPERIENCE" in [paragraph.text for paragraph in document.paragraphs]


def test_cover_letter_docx_contains_the_complete_letter() -> None:
    resume = final_resume()
    letter = CoverLetterDraft.model_validate(cover_letter_payload(language="de"))

    content = build_cover_letter_docx(
        letter,
        sender=resume.basics,
        letter_date=date(2026, 3, 1),
        template=resolve_document_template("swiss_classic"),
    )

    paragraphs = [paragraph.text for paragraph in Document(BytesIO(content)).paragraphs]
    assert paragraphs[0] == "Mira Keller"
    assert "Zurich, 1. März 2026" in paragraphs
    assert "Application for Backend Engineer (Python)" in paragraphs
    assert paragraphs[-2:] == ["Kind regards,", "Mira Keller"]


@pytest.mark.parametrize(("language", "label"), [("en", "Expertise"), ("de", "Fachkenntnisse")])
def test_skills_without_a_category_get_a_labeled_group(language: str, label: str) -> None:
    resume = final_resume(language=language)
    skills = [skill.model_dump(mode="json", by_alias=True) for skill in resume.skills]
    skills.append({**skills[0], "id": "concept-1", "name": "LLM", "category": "  "})
    resume = resume.model_validate(
        {**resume.model_dump(mode="json", by_alias=True), "skills": skills}
    )

    groups = skill_group_view(resume)

    assert all(group["category"] for group in groups)
    assert groups[-1] == {"category": label, "names": ["LLM"]}
    content = build_resume_docx(resume, template=resolve_document_template("swiss_classic"))
    docx_text = "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs)
    assert f"{label}: LLM" in docx_text
