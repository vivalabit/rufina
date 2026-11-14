"""Render tailored documents from structured content in any gallery template.

Content and design are independent: a `FinalResume` or `CoverLetterDraft` is
rendered by a server-owned HTML template into a PDF, and the same content can be
re-rendered in another template without calling a model. Page limits are met
deterministically, first by a small layout shrink and then by dropping the
lowest-value optional statements.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Literal

from jinja2 import Environment, StrictUndefined, select_autoescape
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models.generation_workflow import CoverLetterDraft
from app.models.resume import FinalResume, ResumeBasics, resume_evidence_ids
from app.services.resume_pdf_renderer import (
    MIN_FIT_SCALE,
    ChromiumPdfSession,
    ResolvedResumeTemplate,
    ResumePdfPageManifest,
    ResumePdfRenderError,
    ResumePdfTemplateBundle,
    expected_resume_text_fragments,
    load_template_bundle,
    normalize_display_value,
    render_resolved_final_resume_html,
    resolve_bundled_resume_template,
    resolve_resume_template,
    resume_design_css,
    validate_rendered_pdf,
)
from app.services.resume_pdf_validation import (
    ResumePdfValidationError,
    extract_pdf_text_with_poppler,
    stamp_resume_pdf_metadata,
)
from app.services.resume_template_registry import (
    get_bundled_resume_template,
    is_bundled_resume_template_id,
)

DocumentKind = Literal["tailored_resume", "cover_letter"]

DEFAULT_DOCUMENT_TEMPLATE_ID = "swiss_classic"
# Gallery order: the default first, single-column templates before the design one.
DOCUMENT_TEMPLATE_ORDER = (
    "swiss_classic",
    "classic_single",
    "modern_single",
    "swiss_local_german",
    "modern_two_column",
)
# Identifiers saved by earlier generator versions.
LEGACY_DOCUMENT_TEMPLATE_IDS = {
    "roman": "swiss_classic",
    "ishchenko_classic": "swiss_classic",
    "moderncv_banking": "modern_single",
}
COVER_LETTER_TEMPLATE_VERSION = "1.0.0"
COVER_LETTER_TEMPLATE_ROOT = (
    Path(__file__).resolve().parent.parent / "templates" / "cover_letter_pdf"
)
RESUME_FIT_SCALES = (1.0, 0.97, 0.94)
RESUME_LAST_RESORT_FIT_SCALE = 0.9
COVER_LETTER_FIT_SCALES = (1.0, 0.96, 0.92, 0.88)
_CENTERED_HEADER_TEMPLATES = frozenset({"swiss_classic", "swiss_local_german"})


class DocumentRenderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "document_render_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DocumentTemplateInfo:
    id: str
    name: str
    description: str
    columns: int
    ats_safe: bool
    version: str
    is_default: bool


@dataclass(frozen=True)
class RenderedDocument:
    document_type: DocumentKind
    pdf: bytes
    page_count: int
    template_id: str
    template_version: str
    design_sha256: str
    fit_scale: float = 1.0
    dropped_statement_ids: tuple[str, ...] = ()
    # Empty when the text extracted from the PDF matches the content in order.
    text_check_error: str = ""

    @property
    def ats_readable(self) -> bool:
        return not self.text_check_error


@dataclass(frozen=True)
class ResumeRender:
    resume: FinalResume
    document: RenderedDocument


def normalize_document_template_id(template_id: str | None) -> str:
    requested = (template_id or "").strip()
    if not requested:
        return DEFAULT_DOCUMENT_TEMPLATE_ID
    return LEGACY_DOCUMENT_TEMPLATE_IDS.get(requested, requested)


def list_document_templates() -> tuple[DocumentTemplateInfo, ...]:
    templates: list[DocumentTemplateInfo] = []
    for template_id in DOCUMENT_TEMPLATE_ORDER:
        metadata = get_bundled_resume_template(template_id)
        templates.append(
            DocumentTemplateInfo(
                id=metadata.id,
                name=metadata.name,
                description=metadata.description,
                columns=metadata.columns,
                ats_safe=metadata.columns == 1,
                version=load_template_bundle(metadata.id).manifest.template_version,
                is_default=metadata.id == DEFAULT_DOCUMENT_TEMPLATE_ID,
            )
        )
    return tuple(templates)


def resolve_document_template(
    template_id: str | None,
    *,
    db: Session | None = None,
) -> ResolvedResumeTemplate:
    """Resolve a gallery template, or one of the owner's saved designs when `db` is given."""
    normalized = normalize_document_template_id(template_id)
    try:
        if is_bundled_resume_template_id(normalized):
            return resolve_bundled_resume_template(normalized)  # type: ignore[arg-type]
        if db is not None:
            return resolve_resume_template(db, normalized)
    except ResumePdfRenderError as exc:
        raise DocumentRenderError(str(exc), code="document_template_unsupported") from exc
    raise DocumentRenderError(
        f"Unsupported document template: {normalized}",
        code="document_template_unsupported",
    )


def pdf_page_count(pdf: bytes) -> int:
    try:
        return len(PdfReader(BytesIO(pdf)).pages)
    except Exception as exc:  # pypdf raises several unrelated error types
        raise DocumentRenderError("Rendered PDF cannot be parsed") from exc


# --- Resume -----------------------------------------------------------------


def droppable_item_ids(resume: FinalResume, drop_order: Sequence[str]) -> list[str]:
    """Items page fitting may remove, in this order.

    Projects go first, last listed first, as the resume's own experience matters
    more; then the optional statements of `drop_order`; certifications last.
    """
    return [
        *(project.id for project in reversed(resume.projects)),
        *droppable_statement_ids(resume, drop_order),
        *(certification.id for certification in reversed(resume.certifications)),
    ]


def droppable_statement_ids(resume: FinalResume, drop_order: Sequence[str]) -> list[str]:
    """Statements that may be removed, lowest value first, keeping one per role."""
    remaining = {experience.id: len(experience.bullets) for experience in resume.experiences}
    owner = {
        bullet.id: experience.id
        for experience in resume.experiences
        for bullet in experience.bullets
    }
    result: list[str] = []
    for bullet_id in drop_order:
        experience_id = owner.get(bullet_id)
        if experience_id is None or bullet_id in result or remaining[experience_id] <= 1:
            continue
        remaining[experience_id] -= 1
        result.append(bullet_id)
    return result


def without_statements(resume: FinalResume, item_ids: Sequence[str]) -> FinalResume:
    """The resume without these statements, projects or certifications."""
    if not item_ids:
        return resume
    removed = set(item_ids)
    experiences = [
        experience.model_copy(
            update={
                "bullets": [bullet for bullet in experience.bullets if bullet.id not in removed]
            }
        )
        for experience in resume.experiences
    ]
    projects = [item for item in resume.projects if item.id not in removed]
    certifications = [item for item in resume.certifications if item.id not in removed]
    emptied = {
        section
        for section, items in (("projects", projects), ("certifications", certifications))
        if not items
    }
    trimmed = resume.model_copy(
        update={
            "experiences": experiences,
            "projects": projects,
            "certifications": certifications,
            "section_order": [
                section for section in resume.section_order if section not in emptied
            ],
        }
    )
    referenced = set(resume_evidence_ids(trimmed))
    evidence = [item for item in resume.evidence if item.id in referenced]
    return FinalResume.model_validate(
        {
            **trimmed.model_dump(mode="json", by_alias=True),
            "evidence": [item.model_dump(mode="json", by_alias=True) for item in evidence]
            or [item.model_dump(mode="json", by_alias=True) for item in resume.evidence[:1]],
        }
    )


def render_resume_to_fit(
    resume: FinalResume,
    *,
    template: ResolvedResumeTemplate,
    max_pages: int,
    drop_order: Sequence[str] = (),
    session: ChromiumPdfSession | None = None,
) -> ResumeRender:
    """Render the resume within `max_pages`.

    Order of measures: a barely visible layout shrink, then removing projects,
    optional statements in `drop_order` and certifications, in that order
    (binary search over how many), then one stronger shrink. Statements outside
    `drop_order` and the last statement of a role are never removed. If the content still does not fit, the complete document is
    returned at full size and its page count tells the caller.
    """
    if session is None:
        with ChromiumPdfSession() as owned:
            return render_resume_to_fit(
                resume,
                template=template,
                max_pages=max_pages,
                drop_order=drop_order,
                session=owned,
            )

    bundle = load_template_bundle(template.base_template_id)

    def attempt(candidate: FinalResume, scale: float) -> tuple[bytes, int, tuple[str, ...]]:
        html, _ = render_resolved_final_resume_html(
            candidate.model_dump(mode="json", by_alias=True),
            template=template,
            fit_scale=scale,
        )
        rendered = session.render(html, bundle.manifest.page)
        return rendered.pdf, pdf_page_count(rendered.pdf), rendered.overflow_issues

    def finish(
        candidate: FinalResume,
        scale: float,
        dropped: Sequence[str],
        result: tuple[bytes, int, tuple[str, ...]],
    ) -> ResumeRender:
        pdf, pages, overflow = result
        return ResumeRender(
            resume=candidate,
            document=_checked_resume_document(
                pdf,
                pages,
                resume=candidate,
                bundle=bundle,
                template=template,
                fit_scale=scale,
                dropped=tuple(dropped),
                overflow=overflow,
                max_pages=max_pages,
            ),
        )

    result = attempt(resume, RESUME_FIT_SCALES[0])
    result_at_full_size = result
    for scale in RESUME_FIT_SCALES:
        if scale != RESUME_FIT_SCALES[0]:
            result = attempt(resume, scale)
        if result[1] <= max_pages:
            return finish(resume, scale, (), result)

    # The gentlest shrink still overflows: remove optional statements. Fewer
    # removed statements never produce fewer pages, so search for the minimum.
    scale = RESUME_FIT_SCALES[-1]
    candidates = droppable_item_ids(resume, drop_order)
    best: tuple[FinalResume, tuple[bytes, int, tuple[str, ...]], list[str]] | None = None
    low, high = 1, len(candidates)
    while low <= high:
        middle = (low + high) // 2
        dropped = candidates[:middle]
        trimmed = without_statements(resume, dropped)
        trimmed_result = attempt(trimmed, scale)
        if trimmed_result[1] <= max_pages:
            best = (trimmed, trimmed_result, dropped)
            high = middle - 1
        else:
            low = middle + 1
    if best is not None:
        return finish(best[0], scale, best[2], best[1])

    smallest = without_statements(resume, candidates)
    last = attempt(smallest, RESUME_LAST_RESORT_FIT_SCALE)
    if last[1] <= max_pages:
        return finish(smallest, RESUME_LAST_RESORT_FIT_SCALE, candidates, last)
    # Nothing fits. Shrinking or cutting without reaching the limit only costs
    # readability and content, so return the complete document at full size.
    return finish(resume, RESUME_FIT_SCALES[0], (), result_at_full_size)


def _checked_resume_document(
    pdf: bytes,
    pages: int,
    *,
    resume: FinalResume,
    bundle: ResumePdfTemplateBundle,
    template: ResolvedResumeTemplate,
    fit_scale: float,
    dropped: tuple[str, ...],
    overflow: tuple[str, ...],
    max_pages: int,
) -> RenderedDocument:
    try:
        stamped = stamp_resume_pdf_metadata(
            pdf,
            template_id=template.id,
            template_version=template.version,
            resume_schema_version=resume.schema_version,
        )
    except ResumePdfValidationError as exc:
        raise DocumentRenderError(str(exc)) from exc
    text_check_error = ""
    try:
        # The page limit is the caller's, not the template's upper bound.
        page_bundle = replace(
            bundle,
            manifest=bundle.manifest.model_copy(
                update={
                    "validation": bundle.manifest.validation.model_copy(
                        update={"min_pages": 1, "max_pages": max(pages, max_pages)}
                    )
                }
            ),
        )
        validate_rendered_pdf(
            stamped,
            resume=resume,
            bundle=page_bundle,
            resolved_template=template,
            html_overflow_issues=overflow,
        )
    except ResumePdfValidationError as exc:
        # The file is still usable by a person. The caller reports that machine
        # readers may not see every field, instead of failing the whole run.
        text_check_error = str(exc)
        if "missing expected text" in text_check_error or "reading order" in text_check_error:
            # Second opinion from Poppler before reporting a text problem.
            text_check_error = _missing_text_error(
                stamped,
                expected_resume_text_fragments(
                    resume,
                    reading_order=bundle.manifest.validation.reading_order,
                    sidebar_sections=template.design.sidebar_sections,
                    display_link_labels=template.base_template_id in _CENTERED_HEADER_TEMPLATES,
                ),
            )
    return RenderedDocument(
        document_type="tailored_resume",
        pdf=stamped,
        page_count=pages,
        template_id=template.id,
        template_version=template.version,
        design_sha256=template.design_sha256,
        fit_scale=fit_scale,
        dropped_statement_ids=dropped,
        text_check_error=text_check_error,
    )


# --- Cover letter -----------------------------------------------------------

_GERMAN_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)
_FRENCH_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
_ENGLISH_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def language_code(language: str) -> str:
    value = language.strip().lower()
    if value.startswith(("de", "german", "deutsch")):
        return "de"
    if value.startswith(("fr", "french", "français", "francais")):
        return "fr"
    return "en"


def format_letter_date(value: date, language: str) -> str:
    code = language_code(language)
    if code == "de":
        return f"{value.day}. {_GERMAN_MONTHS[value.month - 1]} {value.year}"
    if code == "fr":
        day = "1er" if value.day == 1 else str(value.day)
        return f"{day} {_FRENCH_MONTHS[value.month - 1]} {value.year}"
    return f"{value.day} {_ENGLISH_MONTHS[value.month - 1]} {value.year}"


def _city(location: str) -> str:
    return location.split(",")[0].strip()


def cover_letter_view_model(
    letter: CoverLetterDraft,
    *,
    sender: ResumeBasics,
    letter_date: date,
) -> dict[str, object]:
    def clean(value: str) -> str:
        return str(normalize_display_value(value)).strip()

    city = _city(sender.location)
    formatted_date = format_letter_date(letter_date, letter.language)
    contacts = [
        value
        for value in (sender.location, sender.phone, sender.email, _short_url(sender.linkedin))
        if value
    ]
    return {
        "sender": {
            "full_name": clean(sender.full_name),
            "contact_lines": [clean(value) for value in contacts],
        },
        "letter": {
            "language_code": language_code(letter.language),
            "recipient_lines": [
                clean(line) for line in letter.recipient.splitlines() if line.strip()
            ],
            "dateline": f"{clean(city)}, {formatted_date}" if city else formatted_date,
            "subject": clean(letter.subject),
            "salutation": clean(letter.salutation),
            "paragraphs": [clean(paragraph.text) for paragraph in letter.paragraphs],
            "closing": clean(letter.closing),
        },
    }


def _short_url(value: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", value.strip()).rstrip("/")


def cover_letter_stylesheet(template: ResolvedResumeTemplate, *, fit_scale: float = 1.0) -> str:
    base = (COVER_LETTER_TEMPLATE_ROOT / "letter.css").read_text(encoding="utf-8")
    # Reuse the resume design's font and accent so both documents match; the
    # letter keeps its own page margins, declared last.
    design_variables = resume_design_css(template.design).split("@page", 1)[0]
    stylesheet = f"{design_variables}\n{base}"
    if fit_scale != 1.0:
        if not MIN_FIT_SCALE <= fit_scale <= 1.0:
            raise DocumentRenderError("Cover letter fit scale is outside the supported range")
        stylesheet += f"\n.letter-shell {{ zoom: {format(fit_scale, '.6g')}; }}"
    return stylesheet


def cover_letter_design_sha256(template: ResolvedResumeTemplate) -> str:
    source = (
        (COVER_LETTER_TEMPLATE_ROOT / "letter.html.j2").read_bytes()
        + b"\0"
        + (COVER_LETTER_TEMPLATE_ROOT / "letter.css").read_bytes()
    )
    return hashlib.sha256(
        f"cover_letter\0{COVER_LETTER_TEMPLATE_VERSION}\0{template.design_sha256}\0".encode()
        + source
    ).hexdigest()


def render_cover_letter_html(
    letter: CoverLetterDraft,
    *,
    sender: ResumeBasics,
    letter_date: date,
    template: ResolvedResumeTemplate,
    fit_scale: float = 1.0,
) -> str:
    environment = Environment(
        autoescape=select_autoescape(("html", "xml"), default=True),
        undefined=StrictUndefined,
    )
    source = (COVER_LETTER_TEMPLATE_ROOT / "letter.html.j2").read_text(encoding="utf-8")
    sentinel = "RUFINA_SERVER_OWNED_STYLESHEET"
    try:
        html = environment.from_string(source).render(
            **cover_letter_view_model(letter, sender=sender, letter_date=letter_date),
            stylesheet=sentinel,
            template_id=template.base_template_id,
            header_align=(
                "center" if template.base_template_id in _CENTERED_HEADER_TEMPLATES else "left"
            ),
        )
    except Exception as exc:
        raise DocumentRenderError("Cover letter HTML rendering failed") from exc
    return html.replace(sentinel, cover_letter_stylesheet(template, fit_scale=fit_scale), 1)


def cover_letter_expected_fragments(
    letter: CoverLetterDraft,
    *,
    sender: ResumeBasics,
) -> list[str]:
    return [
        sender.full_name,
        letter.subject,
        letter.salutation,
        *(paragraph.text for paragraph in letter.paragraphs),
        letter.closing,
    ]


def render_cover_letter(
    letter: CoverLetterDraft,
    *,
    sender: ResumeBasics,
    letter_date: date,
    template: ResolvedResumeTemplate,
    max_pages: int = 1,
    session: ChromiumPdfSession | None = None,
) -> RenderedDocument:
    if session is None:
        with ChromiumPdfSession() as owned:
            return render_cover_letter(
                letter,
                sender=sender,
                letter_date=letter_date,
                template=template,
                max_pages=max_pages,
                session=owned,
            )
    page = ResumePdfPageManifest()
    pdf = b""
    pages = 0
    used_scale = COVER_LETTER_FIT_SCALES[0]
    for scale in COVER_LETTER_FIT_SCALES:
        html = render_cover_letter_html(
            letter, sender=sender, letter_date=letter_date, template=template, fit_scale=scale
        )
        pdf = session.render(html, page, probe_overflow=False).pdf
        pages = pdf_page_count(pdf)
        used_scale = scale
        if pages <= max_pages:
            break
    return RenderedDocument(
        document_type="cover_letter",
        pdf=pdf,
        page_count=pages,
        template_id=template.id,
        template_version=COVER_LETTER_TEMPLATE_VERSION,
        design_sha256=cover_letter_design_sha256(template),
        fit_scale=used_scale,
        text_check_error=_missing_text_error(
            pdf, cover_letter_expected_fragments(letter, sender=sender)
        ),
    )


def _normalized_text(value: str) -> str:
    value = str(normalize_display_value(value))
    value = value.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"\s+", " ", value).strip().casefold()


def extract_pdf_text(pdf: bytes) -> str:
    """Text as a machine reader sees it: Poppler when installed, otherwise pypdf.

    Poppler also reads fonts that Chromium embeds as Type 3, which pypdf cannot.
    """
    poppler_text = extract_pdf_text_with_poppler(pdf)
    if poppler_text is not None:
        return poppler_text
    try:
        reader = PdfReader(BytesIO(pdf))
        return "\n".join(page.extract_text(extraction_mode="plain") or "" for page in reader.pages)
    except Exception as exc:
        raise DocumentRenderError("Rendered PDF text cannot be extracted") from exc


def _missing_text_error(pdf: bytes, fragments: Sequence[str]) -> str:
    extracted = _normalized_text(extract_pdf_text(pdf))
    # A line may break inside a hyphenated word, and text extractors then either
    # keep the hyphen or join the halves. Compare without spaces and hyphens.
    compact = re.sub(r"[\s-]", "", extracted)
    missing = [
        fragment
        for fragment in fragments
        if (normalized := _normalized_text(fragment))
        and normalized not in extracted
        and re.sub(r"[\s-]", "", normalized) not in compact
    ]
    if not missing:
        return ""
    return "Rendered PDF is missing expected text: " + "; ".join(
        f"{item[:60]}..." if len(item) > 60 else item for item in missing[:3]
    )


__all__ = [
    "COVER_LETTER_TEMPLATE_VERSION",
    "DEFAULT_DOCUMENT_TEMPLATE_ID",
    "DOCUMENT_TEMPLATE_ORDER",
    "LEGACY_DOCUMENT_TEMPLATE_IDS",
    "DocumentKind",
    "DocumentRenderError",
    "DocumentTemplateInfo",
    "RenderedDocument",
    "ResumeRender",
    "cover_letter_design_sha256",
    "cover_letter_view_model",
    "droppable_item_ids",
    "droppable_statement_ids",
    "extract_pdf_text",
    "format_letter_date",
    "language_code",
    "list_document_templates",
    "normalize_document_template_id",
    "pdf_page_count",
    "render_cover_letter",
    "render_cover_letter_html",
    "render_resume_to_fit",
    "resolve_document_template",
    "without_statements",
]
