"""Editable Word versions of tailored documents, built from structured content.

The DOCX is never converted from the PDF: it is assembled from the same
`FinalResume` or `CoverLetterDraft` with the template's font, accent color and
margins, in a single column with real headings, tab-aligned dates and list
paragraphs so that applicant tracking systems and people can both edit it.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from app.models.generation_workflow import CoverLetterDraft
from app.models.resume import FinalResume, ResumeBasics
from app.services.document_rendering import cover_letter_view_model
from app.services.resume_pdf_renderer import ResolvedResumeTemplate, resume_view_model

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Fonts that are rarely installed with Word are replaced by a close system font.
_FONT_FALLBACKS = {"Inter": "Arial"}
_CENTERED_HEADER_TEMPLATES = frozenset({"swiss_classic", "swiss_local_german"})
_A4_WIDTH_MM = 210.0
_LINK_LABELS = {"linkedin": "LinkedIn", "github": "GitHub", "portfolio": "Portfolio"}


class _Style:
    def __init__(self, template: ResolvedResumeTemplate) -> None:
        design = template.design
        self.font = _FONT_FALLBACKS.get(design.font_family, design.font_family)
        self.accent = RGBColor.from_string(design.accent_color.lstrip("#").upper())
        self.centered = template.base_template_id in _CENTERED_HEADER_TEMPLATES
        self.serif = self.centered
        self.margins = design.page_margins
        self.text_width_mm = _A4_WIDTH_MM - design.page_margins.left - design.page_margins.right
        self.body_size = 10.0
        self.heading_size = 13.0 if self.serif else 11.0
        self.name_size = 14.0 if self.serif else 20.0


def _new_document(style: _Style) -> Any:
    document = Document()
    section = document.sections[0]
    section.page_width = Mm(_A4_WIDTH_MM)
    section.page_height = Mm(297)
    section.top_margin = Mm(style.margins.top)
    section.right_margin = Mm(style.margins.right)
    section.bottom_margin = Mm(style.margins.bottom)
    section.left_margin = Mm(style.margins.left)
    normal = document.styles["Normal"]
    normal.font.name = style.font
    normal.font.size = Pt(style.body_size)
    # East Asian and complex-script fallbacks must name the same font.
    fonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attribute), style.font)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.0
    return document


def _paragraph(
    document: Any,
    *,
    before: float = 0,
    after: float = 0,
    align: WD_ALIGN_PARAGRAPH | None = None,
    keep_with_next: bool = False,
) -> Any:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.keep_with_next = keep_with_next
    if align is not None:
        paragraph.alignment = align
    return paragraph


def _run(
    paragraph: Any,
    text: str,
    *,
    size: float | None = None,
    bold: bool = False,
    italic: bool = False,
    color: RGBColor | None = None,
) -> Any:
    run = paragraph.add_run(text)
    run.bold = bold or None
    run.italic = italic or None
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    return run


def _hyperlink(paragraph: Any, url: str, text: str, *, size: float) -> None:
    relationship_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(underline)
    for tag in ("w:sz", "w:szCs"):
        element = OxmlElement(tag)
        element.set(qn("w:val"), str(int(size * 2)))
        properties.append(element)
    run.append(properties)
    text_element = OxmlElement("w:t")
    text_element.text = text
    text_element.set(qn("xml:space"), "preserve")
    run.append(text_element)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _bottom_border(paragraph: Any, color: RGBColor) -> None:
    properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), str(color))
    borders.append(bottom)
    properties.append(borders)


def _right_tab(paragraph: Any, style: _Style) -> None:
    paragraph.paragraph_format.tab_stops.add_tab_stop(
        Mm(style.text_width_mm), WD_TAB_ALIGNMENT.RIGHT
    )


def _two_sided_line(
    document: Any,
    style: _Style,
    left: str,
    right: str,
    *,
    bold: bool = False,
    italic: bool = False,
    before: float = 0,
) -> None:
    paragraph = _paragraph(document, before=before, keep_with_next=True)
    _right_tab(paragraph, style)
    _run(paragraph, left, bold=bold, italic=italic)
    if right:
        _run(paragraph, "\t" + right, italic=italic)


def _bullet(document: Any, statement: dict[str, Any]) -> None:
    paragraph = document.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.left_indent = Mm(10)
    paragraph.paragraph_format.first_line_indent = Mm(-5)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(1)
    segments = statement.get("segments") or [{"text": statement.get("text", ""), "strong": False}]
    for segment in segments:
        _run(paragraph, str(segment["text"]), bold=bool(segment["strong"]))


def _section_heading(document: Any, style: _Style, title: str) -> None:
    paragraph = _paragraph(document, before=9, after=3, keep_with_next=True)
    _run(
        paragraph,
        title if style.serif else title.upper(),
        size=style.heading_size,
        bold=True,
        color=style.accent,
    )
    _bottom_border(paragraph, style.accent)


def _identity(document: Any, style: _Style, basics: dict[str, Any]) -> None:
    align = WD_ALIGN_PARAGRAPH.CENTER if style.centered else WD_ALIGN_PARAGRAPH.LEFT
    name = _paragraph(document, align=align)
    _run(name, str(basics["full_name"]), size=style.name_size, bold=True)
    if basics.get("headline"):
        _run(_paragraph(document, before=2, align=align), str(basics["headline"]), size=12)
    meta = " | ".join(
        str(value) for value in (basics.get("location"), basics.get("work_authorization")) if value
    )
    if meta:
        _run(_paragraph(document, before=2, align=align), meta, size=9)
    contacts = [
        contact
        for contact in basics.get("contacts", [])
        if contact["kind"] not in {"location", "work_authorization"}
    ]
    if contacts:
        line = _paragraph(document, before=1, align=align)
        for index, contact in enumerate(contacts):
            if index:
                _run(line, " | ", size=9)
            label = _LINK_LABELS.get(contact["kind"], contact["value"])
            href = contact.get("href", "")
            if href:
                _hyperlink(line, href, label, size=9)
            else:
                _run(line, str(contact["value"]), size=9)


def _period(start: str, end: str) -> str:
    return " – ".join(value for value in (start, end) if value)


def build_resume_docx(resume: FinalResume, *, template: ResolvedResumeTemplate) -> bytes:
    style = _Style(template)
    view = resume_view_model(resume)
    titles: dict[str, str] = view["section_titles"]  # type: ignore[assignment]
    document = _new_document(style)
    _identity(document, style, view["basics"])  # type: ignore[arg-type]

    for section in view["section_order"]:  # type: ignore[union-attr]
        if section == "summary" and view["summary"]:
            if not style.serif:
                _section_heading(document, style, titles["summary"])
            _run(
                _paragraph(document, before=8 if style.serif else 0),
                str(view["summary"]["text"]),  # type: ignore[index]
            )
        elif section == "experience" and view["experiences"]:
            _section_heading(document, style, titles["experience"])
            for index, experience in enumerate(view["experiences"]):  # type: ignore[arg-type]
                _two_sided_line(
                    document,
                    style,
                    experience["title"],
                    experience["period"].replace(" - ", " – "),
                    bold=True,
                    before=7 if index else 0,
                )
                _two_sided_line(
                    document, style, experience["company"], experience["location"], italic=True
                )
                for bullet in experience["bullets"]:
                    _bullet(document, bullet)
        elif section == "education" and view["education"]:
            _section_heading(document, style, titles["education"])
            for index, education in enumerate(view["education"]):  # type: ignore[arg-type]
                credential = education["credential"]
                if education["field_of_study"]:
                    credential = f"{credential} in {education['field_of_study']}"
                _two_sided_line(
                    document,
                    style,
                    credential,
                    _period(education["start_date"], education["end_date"]),
                    bold=True,
                    before=7 if index else 0,
                )
                _two_sided_line(
                    document, style, education["institution"], education["location"], italic=True
                )
                for detail in education["details"]:
                    _bullet(document, detail)
        elif section == "languages" and view["languages"]:
            _section_heading(document, style, titles["languages"])
            paragraph = _paragraph(document)
            for index, language in enumerate(view["languages"]):  # type: ignore[arg-type]
                if index:
                    _run(paragraph, "      ")
                _run(paragraph, f"{language['name']}: ", bold=True)
                _run(paragraph, language["proficiency"])
        elif section == "skills" and view["skill_groups"]:
            _section_heading(document, style, titles["skills"])
            for group in view["skill_groups"]:  # type: ignore[union-attr]
                paragraph = _paragraph(document, after=1)
                if group["category"]:
                    _run(paragraph, f"{group['category']}: ", bold=True)
                _run(paragraph, ", ".join(group["names"]))
        elif section == "projects" and view["projects"]:
            _section_heading(document, style, titles["projects"])
            for index, project in enumerate(view["projects"]):  # type: ignore[arg-type]
                _two_sided_line(
                    document,
                    style,
                    project["name"],
                    project["role"],
                    bold=True,
                    before=7 if index else 0,
                )
                if project["url"]:
                    _run(_paragraph(document), project["url"], italic=True)
                for bullet in project["bullets"]:
                    _bullet(document, bullet)
        elif section == "certifications" and view["certifications"]:
            _section_heading(document, style, titles["certifications"])
            for certification in view["certifications"]:  # type: ignore[union-attr]
                paragraph = _paragraph(document, after=1)
                _run(paragraph, certification["name"], bold=True)
                details = [certification["issuer"], certification["issued_on"]]
                if certification["expires_on"]:
                    details.append(f"{titles['expires']}: {certification['expires_on']}")
                _run(paragraph, "".join(f" | {value}" for value in details if value))
        elif section == "additional" and view["additional_sections"]:
            _section_heading(document, style, titles["additional"])
            for additional in view["additional_sections"]:  # type: ignore[union-attr]
                _run(_paragraph(document, before=3), additional["title"], bold=True)
                for item in additional["items"]:
                    _bullet(document, item)

    document.core_properties.title = f"{resume.basics.full_name} - Resume"
    document.core_properties.author = resume.basics.full_name
    return _save(document)


def build_cover_letter_docx(
    letter: CoverLetterDraft,
    *,
    sender: ResumeBasics,
    letter_date: date,
    template: ResolvedResumeTemplate,
) -> bytes:
    style = _Style(template)
    view = cover_letter_view_model(letter, sender=sender, letter_date=letter_date)
    sender_view: dict[str, Any] = view["sender"]  # type: ignore[assignment]
    letter_view: dict[str, Any] = view["letter"]  # type: ignore[assignment]
    document = _new_document(style)
    document.styles["Normal"].font.size = Pt(10.5)
    align = WD_ALIGN_PARAGRAPH.CENTER if style.centered else WD_ALIGN_PARAGRAPH.LEFT

    name = _paragraph(document, align=align)
    _run(name, sender_view["full_name"], size=14, bold=True, color=style.accent)
    contacts = _paragraph(document, before=2, after=4, align=align)
    _run(contacts, " | ".join(sender_view["contact_lines"]), size=9)
    _bottom_border(contacts, style.accent)

    for index, line in enumerate(letter_view["recipient_lines"]):
        _run(_paragraph(document, before=22 if index == 0 else 0), line)
    _run(_paragraph(document, before=18, after=20), letter_view["dateline"])
    _run(_paragraph(document, after=14), letter_view["subject"], size=11.5, bold=True)
    _run(_paragraph(document, after=9), letter_view["salutation"])
    for text in letter_view["paragraphs"]:
        body = _paragraph(document, after=9)
        body.paragraph_format.line_spacing = 1.15
        _run(body, text)
    _run(_paragraph(document, before=8, keep_with_next=True), letter_view["closing"])
    _run(_paragraph(document, before=22), sender_view["full_name"], bold=True)

    document.core_properties.title = f"{sender.full_name} - Cover letter"
    document.core_properties.author = sender.full_name
    return _save(document)


def _save(document: Any) -> bytes:
    output = BytesIO()
    document.save(output)
    return output.getvalue()


__all__ = ["DOCX_CONTENT_TYPE", "build_cover_letter_docx", "build_resume_docx"]
