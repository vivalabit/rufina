import json
import re
import zipfile
from copy import deepcopy
from datetime import date
from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

from app.services.cover_letter_blocks import (
    extract_cover_letter_blocks_from_docx,
    header_placeholder_type,
    is_date_line,
    parse_cover_letter_blocks,
    replace_date_in_line,
    replace_cover_letter_text_span,
)
from app.services.word_structure import set_text_node_value
from app.services.resume_pdf_renderer import (
    render_final_resume_json as render_final_resume_pdf_json,
)


BODY_FONT = "Calibri"
HEADING_BLUE = RGBColor(0x2E, 0x74, 0xB5)
HEADING_DARK_BLUE = RGBColor(0x1F, 0x4D, 0x78)
MUTED = RGBColor(0x66, 0x66, 0x66)


def render_final_resume_json(
    final_resume_json: dict[str, object],
) -> bytes:
    """Render a canonical FinalResume JSON payload to PDF."""
    return render_final_resume_pdf_json(final_resume_json)


def build_document_docx(
    *,
    title: str,
    content: str,
    document_type: str,
    version: int,
) -> bytes:
    document = Document()
    configure_document(document)
    add_title_block(document, title, document_type)
    add_document_content(document, content)
    add_footer(document, document_type, version)

    output = BytesIO()
    document.save(output)
    return output.getvalue()


def build_document_from_template(
    *,
    template_content: bytes,
    content: str,
    document_type: str,
) -> bytes:
    """Replace text inside a copied DOCX while retaining its visual structure."""
    if document_type == "tailored_resume":
        raise ValueError(
            "Legacy DOCX resume patching was removed; render FinalResume as PDF"
        )
    if is_structured_cover_letter_content(content):
        return build_cover_letter_from_template_package(template_content, content)

    document = Document(BytesIO(template_content))
    replace_cover_letter_text(document, content)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def build_cover_letter_from_template_package(template_content: bytes, content: str) -> bytes:
    """Patch editable cover-letter spans without rebuilding the DOCX package."""
    with zipfile.ZipFile(BytesIO(template_content)) as source:
        document_xml = source.read("word/document.xml")
        root = etree.fromstring(document_xml)
        body = root.find(qn("w:body"))
        if body is None:
            raise ValueError("Cover-letter template has no document body")
        replace_cover_letter_spans(body, content)
        rendered_xml = etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            standalone=True,
        )

        output = BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for item in source.infolist():
                target.writestr(
                    item,
                    rendered_xml if item.filename == "word/document.xml" else source.read(item.filename),
                )
    return output.getvalue()


def ensure_cover_letter_date_replacement(
    *,
    template_content: bytes,
    content: str,
    generation_date: str,
    language: str,
    vacancy: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    recipient_name: str = "",
    official_company_name: str = "",
    recipient_address_line: str = "",
) -> str:
    """Fill known cover-letter metadata placeholders from authoritative context."""
    generated_date = date.fromisoformat(generation_date)
    localized_date = format_cover_letter_date(generated_date, language)
    paragraphs = extract_cover_letter_blocks_from_docx(template_content)
    replacements = parse_cover_letter_replacements(content)
    replacements_by_span = {
        str(replacement["spanId"]): replacement for replacement in replacements
    }
    changed = False

    def upsert_replacement(
        *,
        paragraph_id: str,
        span_id: str,
        original: str,
        replacement: str,
        reason: str,
        evidence_ids: list[str],
    ) -> None:
        nonlocal changed
        payload = {
            "paragraphId": paragraph_id,
            "spanId": span_id,
            "original": original,
            "replacement": replacement,
            "reason": reason,
            "evidenceIds": [f"source:{span_id}", *evidence_ids],
        }
        existing = replacements_by_span.get(span_id)
        if existing is None:
            replacements.append(payload)
        else:
            existing.update(payload)
        replacements_by_span[span_id] = payload
        changed = True

    vacancy_data = vacancy or {}
    profile_data = profile or {}
    company = (
        official_company_name.strip()
        or str(vacancy_data.get("company") or "").strip()
    )
    vacancy_title = collapse_repeated_text(
        str(vacancy_data.get("title") or "").strip()
    )
    vacancy_location = str(vacancy_data.get("location") or "").strip()
    candidate_location = str(profile_data.get("location") or "").strip()
    recipient = recipient_name.strip()
    company_location = location_without_country(vacancy_location)
    recipient_street, recipient_postal_line = split_recipient_address(
        recipient_address_line
    )
    if not recipient_postal_line:
        recipient_postal_line = company_location
    candidate_city = city_from_location(candidate_location)
    candidate_name = str(profile_data.get("name") or "").strip()
    company_evidence = (
        ["confirmation:company-header-research"]
        if official_company_name.strip()
        else ["vacancy:company"]
    )
    address_evidence = (
        ["confirmation:company-header-research"]
        if recipient_address_line.strip()
        else (["vacancy:location"] if company_location else [])
    )

    for paragraph in paragraphs:
        for span in paragraph["spans"]:
            original = span.get("original")
            span_id = span.get("spanId")
            if (
                not span.get("editable")
                or not isinstance(original, str)
                or not isinstance(span_id, str)
            ):
                continue
            placeholder_type = header_placeholder_type(original)
            if placeholder_type == "recipientCompany":
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=company,
                    reason="Fills the recipient's official company name",
                    evidence_ids=company_evidence,
                )
            elif placeholder_type == "recipientName":
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=recipient or "Hiring Team",
                    reason="Fills the recruiter or hiring-team recipient",
                    evidence_ids=(
                        ["confirmation:cover-letter-recipient-name"]
                        if recipient
                        else []
                    ),
                )
            elif placeholder_type == "recipientStreet":
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=recipient_street,
                    reason="Fills the recipient's verified street and building number",
                    evidence_ids=address_evidence,
                )
            elif placeholder_type == "recipientCity":
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=recipient_postal_line,
                    reason="Fills the verified postal code, city, and country",
                    evidence_ids=address_evidence,
                )
            elif placeholder_type == "recipientCountry":
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement="",
                    reason="Moves the country into the postal-address line",
                    evidence_ids=address_evidence,
                )
            elif placeholder_type == "letterDate":
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=(
                        f"{candidate_city}, {localized_date}"
                        if candidate_city
                        else localized_date
                    ),
                    reason="Fills the candidate city and current letter date",
                    evidence_ids=(
                        (["profile:location"] if candidate_city else [])
                        + ["generation:date"]
                    ),
                )
            elif placeholder_type == "candidateName":
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=candidate_name,
                    reason="Fills the signature with the candidate's verified name",
                    evidence_ids=["profile:name"] if candidate_name else [],
                )
            elif paragraph["type"] == "subject" and vacancy_title:
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=(
                        f"Bewerbung als {vacancy_title}"
                        if language == "German"
                        else f"Application for {vacancy_title}"
                    ),
                    reason="Fills the subject with the exact vacancy title",
                    evidence_ids=["vacancy:title"],
                )
            elif paragraph["type"] == "greeting" and (recipient or company):
                team_name = company_team_name(company)
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=(
                        f"Dear {recipient},"
                        if recipient
                        else (
                            f"Dear {team_name} Hiring Team,"
                            if team_name
                            else "Dear Hiring Team,"
                        )
                    ),
                    reason="Addresses the verified recruiter or the company hiring team",
                    evidence_ids=(
                        ["confirmation:cover-letter-recipient-name"]
                        if recipient
                        else company_evidence
                    ),
                )
            elif is_date_line(original):
                upsert_replacement(
                    paragraph_id=paragraph["paragraphId"],
                    span_id=span_id,
                    original=original,
                    replacement=replace_date_in_line(original, localized_date),
                    reason="Updates the letter date to the generation date",
                    evidence_ids=["generation:date"],
                )
    if not changed:
        return content
    return json.dumps(
        {"replacements": replacements},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def split_recipient_address(value: str) -> tuple[str, str]:
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return "", ""
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if len(parts) >= 2:
        return parts[0], ", ".join(parts[1:])
    postal_match = re.search(r"(?<!\d)\d{4,6}\s+", normalized)
    if postal_match and postal_match.start() > 0:
        return (
            normalized[: postal_match.start()].rstrip(" ,"),
            normalized[postal_match.start() :],
        )
    return normalized, ""


def location_without_country(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) > 1 and parts[-1].casefold() in {
        "switzerland",
        "schweiz",
        "suisse",
        "svizzera",
    }:
        parts.pop()
    return ", ".join(parts)


def city_from_location(value: str) -> str:
    return location_without_country(value).split(",", maxsplit=1)[0].strip()


def collapse_repeated_text(value: str) -> str:
    midpoint = len(value) // 2
    if len(value) % 2 == 0 and value[:midpoint] == value[midpoint:]:
        return value[:midpoint].strip()
    return value


def company_team_name(value: str) -> str:
    return re.sub(
        r"\s+(?:AG|GmbH|SA|S\.A\.|Ltd\.?|Limited|Inc\.?|LLC|SE)$",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    ).strip()


def format_cover_letter_date(value: date, language: str) -> str:
    if language == "German":
        months = (
            "Januar",
            "Februar",
            "März",
            "April",
            "Mai",
            "Juni",
            "Juli",
            "August",
            "September",
            "Oktober",
            "November",
            "Dezember",
        )
        return f"{value.day}. {months[value.month - 1]} {value.year}"
    months = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    return f"{months[value.month - 1]} {value.day}, {value.year}"


def replace_cover_letter_spans(body, content: str) -> None:
    paragraphs = parse_cover_letter_blocks(body)
    paragraphs_by_id = {paragraph.paragraph_id: paragraph for paragraph in paragraphs}
    paragraph_elements = {
        paragraph.paragraph_id: element
        for paragraph, element in zip(
            paragraphs,
            list(body.iter(qn("w:p"))),
            strict=True,
        )
    }
    replacements = parse_cover_letter_replacements(content)
    replacements_by_span_id = {
        str(replacement["spanId"]): replacement for replacement in replacements
    }
    seen_span_ids: set[str] = set()
    for replacement in replacements:
        paragraph_id = replacement["paragraphId"]
        paragraph = paragraphs_by_id.get(paragraph_id)
        if paragraph is None:
            raise ValueError(f"Unknown cover-letter paragraph: {paragraph_id}")
        span_id = replacement["spanId"]
        if span_id in seen_span_ids:
            raise ValueError(f"Duplicate cover-letter replacement for {span_id}")
        seen_span_ids.add(span_id)
        span = next(
            (candidate for candidate in paragraph.spans if candidate.span_id == span_id),
            None,
        )
        if span is None:
            raise ValueError(f"Unknown cover-letter span for {paragraph_id}: {span_id}")
        if replacement["original"] != span.original:
            raise ValueError(
                f"Cover-letter original text does not match {span_id}"
            )
        replace_cover_letter_text_span(span, replacement["replacement"])

    for paragraph in paragraphs:
        placeholder_spans = {
            placeholder_type: span
            for span in paragraph.spans
            if (placeholder_type := header_placeholder_type(span.original)) is not None
        }
        if {
            "recipientCompany",
            "recipientName",
            "recipientStreet",
            "recipientCity",
        }.issubset(placeholder_spans):
            lines = []
            for placeholder_type in (
                "recipientCompany",
                "recipientName",
                "recipientStreet",
                "recipientCity",
                "recipientCountry",
            ):
                if placeholder_type not in placeholder_spans:
                    continue
                span = placeholder_spans[placeholder_type]
                replacement = replacements_by_span_id.get(span.span_id)
                value = (
                    str(replacement["replacement"])
                    if replacement is not None
                    else span.original
                )
                if value.strip():
                    lines.append(value.strip())
            set_paragraph_element_lines(
                paragraph_elements[paragraph.paragraph_id],
                lines,
            )
            continue

        if paragraph.paragraph_type not in {"recipientCity", "recipientCountry"}:
            continue
        text_spans = [span for span in paragraph.spans if span.span_type == "text"]
        if len(text_spans) != 1:
            continue
        replacement = replacements_by_span_id.get(text_spans[0].span_id)
        if replacement is None or str(replacement["replacement"]).strip():
            continue
        element = paragraph_elements[paragraph.paragraph_id]
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def set_paragraph_element_lines(element, lines: list[str]) -> None:
    """Replace a header paragraph while retaining its paragraph and run formatting."""
    run_properties = element.find(".//" + qn("w:rPr"))
    for child in list(element):
        if child.tag != qn("w:pPr"):
            element.remove(child)
    if not lines:
        return
    run = OxmlElement("w:r")
    if run_properties is not None:
        run.append(deepcopy(run_properties))
    for index, line in enumerate(lines):
        if index:
            run.append(OxmlElement("w:br"))
        node = OxmlElement("w:t")
        set_text_node_value(node, line)
        run.append(node)
    element.append(run)


def replace_cover_letter_text(document: Document, content: str) -> None:
    paragraphs = document.paragraphs
    generated = normalized_content_paragraphs(content)
    if not generated:
        raise ValueError("Generated document content is empty")

    marker_index = next(
        (
            index
            for index, paragraph in enumerate(paragraphs)
            if "{{cover_letter_body}}" in paragraph.text.lower()
            or "{{content}}" in paragraph.text.lower()
        ),
        None,
    )
    if marker_index is not None:
        replace_paragraph_elements(
            paragraphs[marker_index : marker_index + 1],
            generated,
        )
    else:
        greeting_index = next(
            (
                index
                for index, paragraph in enumerate(paragraphs)
                if re.match(r"^\s*(?:dear|hello|hi|to\b)", paragraph.text, re.IGNORECASE)
            ),
            None,
        )
        closing_index = next(
            (
                index
                for index, paragraph in enumerate(paragraphs)
                if greeting_index is not None
                and index > greeting_index
                and re.match(
                    r"^\s*(?:sincerely|best|kind regards|warm regards|regards|thank you)",
                    paragraph.text,
                    re.IGNORECASE,
                )
            ),
            None,
        )
        if greeting_index is None or closing_index is None or closing_index <= greeting_index:
            raise ValueError(
                "Template needs {{cover_letter_body}} or recognizable greeting and closing paragraphs"
            )

        generated_greeting, generated_body, generated_closing = split_generated_letter(generated)
        if generated_greeting:
            set_paragraph_element_text(paragraphs[greeting_index]._p, generated_greeting)
        body_paragraphs = paragraphs[greeting_index + 1 : closing_index]
        if not body_paragraphs:
            body_paragraphs = [paragraphs[greeting_index]]
        replace_paragraph_elements(body_paragraphs, generated_body or generated)
        if generated_closing:
            set_paragraph_element_text(paragraphs[closing_index]._p, generated_closing)



def is_structured_cover_letter_content(content: str) -> bool:
    cleaned = content.strip()
    if cleaned.lower().startswith("```json"):
        return True
    if not cleaned.startswith(("{", "[")):
        return False
    try:
        payload = parse_json_content(cleaned)
    except ValueError:
        return True
    return isinstance(payload, (dict, list))


def parse_cover_letter_replacements(content: str) -> list[dict[str, object]]:
    payload = parse_json_content(
        content, error_message="Generated cover letter must be structured JSON"
    )
    if isinstance(payload, dict) and isinstance(payload.get("replacements"), list):
        raw_replacements = payload["replacements"]
    elif isinstance(payload, list):
        raw_replacements = payload
    elif isinstance(payload, dict) and "paragraphId" in payload:
        raw_replacements = [payload]
    else:
        raise ValueError("Generated cover-letter JSON must contain a replacements array")

    replacements: list[dict[str, object]] = []
    required_fields = ("paragraphId", "spanId", "original", "replacement", "reason")
    for index, raw_replacement in enumerate(raw_replacements):
        if not isinstance(raw_replacement, dict) or not all(
            isinstance(raw_replacement.get(field), str) for field in required_fields
        ):
            raise ValueError(
                f"Cover-letter replacement {index + 1} must contain string fields: "
                "paragraphId, spanId, original, replacement, reason"
            )
        evidence_ids = raw_replacement.get("evidenceIds")
        if (
            not isinstance(evidence_ids, list)
            or not 1 <= len(evidence_ids) <= 20
            or not all(
                isinstance(evidence_id, str)
                and evidence_id == evidence_id.strip()
                and 1 <= len(evidence_id) <= 200
                for evidence_id in evidence_ids
            )
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise ValueError(
                f"Cover-letter replacement {index + 1} must contain 1-20 unique evidenceIds strings"
            )
        replacements.append(
            {
                **{field: raw_replacement[field] for field in required_fields},
                "evidenceIds": evidence_ids,
            }
        )
    return replacements


def parse_json_content(content: str, *, error_message: str = "Generated content must be JSON"):
    cleaned = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(error_message) from exc


def normalized_content_paragraphs(content: str) -> list[str]:
    lines = [line.strip() for line in content.replace("\r\n", "\n").split("\n")]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        cleaned = re.sub(r"^#{1,3}\s+", "", line)
        current.append(cleaned)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def split_generated_letter(paragraphs: list[str]) -> tuple[str, list[str], str]:
    greeting = paragraphs[0] if re.match(
        r"^(?:dear|hello|hi|to\b)", paragraphs[0], re.IGNORECASE
    ) else ""
    closing_index = next(
        (
            index
            for index, paragraph in enumerate(paragraphs)
            if re.match(
                r"^(?:sincerely|best|kind regards|warm regards|regards|thank you)",
                paragraph,
                re.IGNORECASE,
            )
        ),
        None,
    )
    body_start = 1 if greeting else 0
    body_end = closing_index if closing_index is not None else len(paragraphs)
    closing = paragraphs[closing_index] if closing_index is not None else ""
    return greeting, paragraphs[body_start:body_end], closing


def replace_paragraph_elements(paragraphs, replacement_texts: list[str]) -> None:
    if not paragraphs:
        raise ValueError("Template has no editable body paragraphs")
    elements = [getattr(paragraph, "_p", paragraph) for paragraph in paragraphs]
    prototype = elements[0]
    parent = prototype.getparent()
    insert_at = parent.index(prototype)
    for element in elements:
        parent.remove(element)
    for offset, replacement in enumerate(replacement_texts):
        clone = deepcopy(prototype)
        set_paragraph_element_text(clone, replacement)
        parent.insert(insert_at + offset, clone)


def set_paragraph_element_text(element, text: str) -> None:
    text_nodes = list(element.iter(qn("w:t")))
    if not text_nodes:
        run = OxmlElement("w:r")
        node = OxmlElement("w:t")
        run.append(node)
        element.append(run)
        text_nodes = [node]
    first, *remaining = text_nodes
    set_text_node_value(first, text)
    for node in remaining:
        set_text_node_value(node, "")


def configure_document(document: Document) -> None:
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.right_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)
    section.start_type = WD_SECTION.NEW_PAGE

    normal = document.styles["Normal"]
    set_style_font(normal, BODY_FONT, 11, RGBColor(0, 0, 0))
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.1

    heading_tokens = {
        "Heading 1": (16, HEADING_BLUE, 16, 8),
        "Heading 2": (13, HEADING_BLUE, 12, 6),
        "Heading 3": (12, HEADING_DARK_BLUE, 8, 4),
    }
    for style_name, (size, color, before, after) in heading_tokens.items():
        style = document.styles[style_name]
        set_style_font(style, BODY_FONT, size, color, bold=True)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    for style_name in ("List Bullet", "List Number"):
        style = document.styles[style_name]
        set_style_font(style, BODY_FONT, 11, RGBColor(0, 0, 0))
        style.paragraph_format.left_indent = Inches(0.5)
        style.paragraph_format.first_line_indent = Inches(-0.25)
        style.paragraph_format.space_after = Pt(8)
        style.paragraph_format.line_spacing = 1.167


def add_title_block(document: Document, title: str, document_type: str) -> None:
    label = "Cover Letter" if document_type == "cover_letter" else "Tailored Resume"
    label_paragraph = document.add_paragraph()
    label_paragraph.paragraph_format.space_after = Pt(4)
    label_run = label_paragraph.add_run(label.upper())
    set_run_font(label_run, BODY_FONT, 9, MUTED, bold=True)

    title_paragraph = document.add_paragraph()
    title_paragraph.paragraph_format.space_after = Pt(14)
    title_paragraph.paragraph_format.keep_with_next = True
    title_run = title_paragraph.add_run(title)
    set_run_font(title_run, BODY_FONT, 22, RGBColor(0, 0, 0), bold=True)


def add_document_content(document: Document, content: str) -> None:
    for raw_line in content.replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(3)
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            document.add_paragraph(
                heading_match.group(2).strip(),
                style=f"Heading {len(heading_match.group(1))}",
            )
            continue

        bullet_match = re.match(r"^(?:[-*•])\s+(.+)$", line)
        if bullet_match:
            document.add_paragraph(bullet_match.group(1).strip(), style="List Bullet")
            continue

        numbered_match = re.match(r"^\d+[.)]\s+(.+)$", line)
        if numbered_match:
            document.add_paragraph(numbered_match.group(1).strip(), style="List Number")
            continue

        paragraph = document.add_paragraph(line)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT


def add_footer(document: Document, document_type: str, version: int) -> None:
    label = "Cover letter" if document_type == "cover_letter" else "Tailored resume"
    paragraph = document.sections[0].footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(f"Rufina · {label} · v{version} · ")
    set_run_font(run, BODY_FONT, 8, MUTED)
    append_page_field(paragraph)


def append_page_field(paragraph) -> None:
    run = paragraph.add_run()
    set_run_font(run, BODY_FONT, 8, MUTED)
    field_begin = OxmlElement("w:fldChar")
    field_begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    field_end = OxmlElement("w:fldChar")
    field_end.set(qn("w:fldCharType"), "end")
    run._r.extend((field_begin, instruction, field_end))


def set_style_font(style, name: str, size: int, color: RGBColor, *, bold: bool = False) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    style.font.color.rgb = color
    style.font.bold = bold
    style._element.rPr.rFonts.set(qn("w:ascii"), name)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), name)


def set_run_font(
    run,
    name: str,
    size: int,
    color: RGBColor,
    *,
    bold: bool = False,
) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.bold = bold
    run._element.rPr.rFonts.set(qn("w:ascii"), name)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), name)
