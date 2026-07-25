import re
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

from docx.oxml.ns import qn
from lxml import etree

from app.services.word_structure import (
    UnsupportedWordStructureError,
    set_text_node_value,
    symbol_label,
    validate_supported_word_structure,
)


CoverLetterSpanType = Literal[
    "text",
    "hyperlink",
    "tab",
    "lineBreak",
    "drawing",
    "symbol",
    "field",
]
XML_RELATIONSHIP_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
GREETING_PREFIXES = (
    "dear ",
    "hello ",
    "hi ",
    "to ",
    "a quien corresponda",
    "beste ",
    "bästa ",
    "basta ",
    "bonjour",
    "buongiorno",
    "buenos días",
    "buenos dias",
    "cara ",
    "caro ",
    "chère ",
    "chères ",
    "cher ",
    "chers ",
    "dzień dobry",
    "dzien dobry",
    "egregia ",
    "egregio ",
    "estimada ",
    "estimadas ",
    "estimado ",
    "estimados ",
    "geachte ",
    "gentile ",
    "goedendag",
    "guten tag",
    "hallo ",
    "hej ",
    "hola ",
    "liebe ",
    "lieber ",
    "liebes ",
    "madame",
    "monsieur",
    "olá ",
    "ola ",
    "prezada ",
    "prezadas ",
    "prezado ",
    "prezados ",
    "sehr geehrte",
    "sehr geehrter",
    "szanowna ",
    "szanowni ",
    "szanowny ",
    "stimat ",
    "stimată ",
    "stimate ",
    "spettabile ",
    "tisztelt ",
    "vážená ",
    "vážený ",
    "vazena ",
    "vazeny ",
)
CLOSING_PREFIXES = (
    "sincerely",
    "atenciosamente",
    "atentamente",
    "best regards",
    "best wishes",
    "bien cordialement",
    "com os melhores cumprimentos",
    "con i migliori saluti",
    "cordiali saluti",
    "cordialement",
    "cu stimă",
    "cu stima",
    "cumprimentos",
    "distinti saluti",
    "kind regards",
    "hoogachtend",
    "warm regards",
    "regards",
    "saludos cordiales",
    "s pozdravem",
    "sincères salutations",
    "sinceres salutations",
    "thank you",
    "un cordial saludo",
    "z poważaniem",
    "z powazaniem",
    "beste grüsse",
    "beste grüße",
    "freundliche grüsse",
    "freundliche grüße",
    "med vänliga hälsningar",
    "med vanliga halsningar",
    "met vriendelijke groet",
    "mit freundlichen grüssen",
    "mit freundlichen grüßen",
    "pozdrawiam serdecznie",
    "üdvözlettel",
    "udvozlettel",
    "vriendelijke groeten",
)
BODY_MARKERS = ("{{cover_letter_body}}", "{{content}}")
SUBJECT_PREFIXES = (
    "application for ",
    "application: ",
    "applying for ",
    "betreff:",
    "bewerbung als ",
    "bewerbung auf ",
    "bewerbung für ",
    "bewerbung um ",
    "cover letter",
    "motivationsschreiben",
    "motivation letter",
    "subject:",
)
DATE_LINE_PATTERN = re.compile(
    r"(?:\b(?:0?[1-9]|[12]\d|3[01])\.?(?:\s+)(?:"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|januar|februar|märz|maerz|mai|juni|juli|oktober|"
    r"dezember)(?:\s+\d{4})?\b)"
    r"|(?:\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(?:0?[1-9]|[12]\d|3[01])(?:,\s*\d{4})?\b)"
    r"|(?:\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-]\d{2,4}\b)"
    r"|(?:\b\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b)",
    re.IGNORECASE,
)


class UnsupportedCoverLetterStructureError(ValueError):
    pass


@dataclass(frozen=True)
class CoverLetterSpan:
    span_id: str
    span_type: CoverLetterSpanType
    original: str
    style: dict[str, Any]
    editable: bool
    hyperlink: dict[str, str] | None = None
    text_nodes: tuple[Any, ...] = ()

    def as_context(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "spanId": self.span_id,
            "type": self.span_type,
            "original": self.original,
            "style": self.style,
            "editable": self.editable,
            "evidenceId": f"source:{self.span_id}",
        }
        if self.hyperlink is not None:
            payload["hyperlink"] = self.hyperlink
        return payload


@dataclass(frozen=True)
class CoverLetterParagraph:
    paragraph_id: str
    paragraph_type: str
    original: str
    style: dict[str, Any]
    editable: bool
    spans: tuple[CoverLetterSpan, ...]
    hyperlinks: tuple[dict[str, str], ...]
    protected_elements: tuple[dict[str, str], ...]

    def as_context(self) -> dict[str, Any]:
        return {
            "paragraphId": self.paragraph_id,
            "type": self.paragraph_type,
            "original": self.original,
            "style": self.style,
            "editable": self.editable,
            "spans": [span.as_context() for span in self.spans],
            "hyperlinks": list(self.hyperlinks),
            "protectedElements": list(self.protected_elements),
        }


@dataclass(frozen=True)
class InlineToken:
    token_type: CoverLetterSpanType
    original: str
    text_node: Any | None
    run: Any | None
    hyperlink: Any | None


def extract_cover_letter_blocks_from_docx(content: bytes) -> list[dict[str, Any]]:
    from app.services.document_analysis import analyze_docx_source

    analysis = analyze_docx_source(content, "cover_letter")
    if analysis.structure_error:
        raise UnsupportedCoverLetterStructureError(analysis.structure_error)
    return analysis.structured_elements()


def parse_cover_letter_blocks(
    body: Any,
    *,
    hyperlink_targets: dict[str, str] | None = None,
    validate_structure: bool = True,
) -> list[CoverLetterParagraph]:
    if validate_structure:
        try:
            validate_supported_word_structure(body)
        except UnsupportedWordStructureError as exc:
            raise UnsupportedCoverLetterStructureError(str(exc)) from exc
    targets = hyperlink_targets or {}
    elements = list(body.iter(qn("w:p")))
    originals = [paragraph_text(element) for element in elements]
    greeting_index = next(
        (index for index, text in enumerate(originals) if is_greeting(text)),
        None,
    )
    closing_index = next(
        (
            index
            for index, text in enumerate(originals)
            if greeting_index is not None and index > greeting_index and is_closing(text)
        ),
        None,
    )
    if greeting_index is not None and closing_index is None:
        closing_index = next(
            (
                index
                for index, (element, text) in enumerate(zip(elements, originals, strict=True))
                if index > greeting_index and is_signature_drawing_boundary(element, text)
            ),
            None,
        )
    marker_indexes = {
        index
        for index, text in enumerate(originals)
        if any(marker in text.lower() for marker in BODY_MARKERS)
    }
    subject_indexes = {
        index
        for index, text in enumerate(originals)
        if greeting_index is not None and index < greeting_index and is_subject(text)
    }

    paragraphs: list[CoverLetterParagraph] = []
    for index, (element, original) in enumerate(zip(elements, originals, strict=True)):
        paragraph_id = f"paragraph-{index + 1:04d}"
        paragraph_type, allows_edits = classify_paragraph(
            element,
            original,
            index=index,
            greeting_index=greeting_index,
            closing_index=closing_index,
            marker_indexes=marker_indexes,
            subject_indexes=subject_indexes,
        )
        spans, hyperlinks, protected_elements = build_spans(
            element,
            paragraph_id=paragraph_id,
            paragraph_editable=allows_edits,
            hyperlink_targets=targets,
        )
        paragraphs.append(
            CoverLetterParagraph(
                paragraph_id=paragraph_id,
                paragraph_type=paragraph_type,
                original=original,
                style=paragraph_style(element),
                editable=any(span.editable for span in spans),
                spans=tuple(spans),
                hyperlinks=tuple(hyperlinks),
                protected_elements=tuple(protected_elements),
            )
        )
    return paragraphs


def classify_paragraph(
    paragraph: Any,
    original: str,
    *,
    index: int,
    greeting_index: int | None,
    closing_index: int | None,
    marker_indexes: set[int],
    subject_indexes: set[int],
) -> tuple[str, bool]:
    if nearest_ancestor(paragraph, qn("w:tc")) is not None:
        return "tableCell", False
    if not original:
        return "empty", False
    if index in marker_indexes:
        return "body", True
    if index in subject_indexes:
        return "subject", True
    if index == greeting_index:
        return "greeting", True
    if index == closing_index:
        return "closing", False
    if closing_index is not None and index > closing_index:
        return "signature", False
    if greeting_index is not None and closing_index is not None:
        if greeting_index < index < closing_index:
            return "body", True
        return "protected", False
    return "protected", False


def is_greeting(text: str) -> bool:
    normalized = " ".join(text.strip().casefold().split())
    return any(normalized.startswith(prefix) for prefix in GREETING_PREFIXES)


def is_subject(text: str) -> bool:
    normalized = " ".join(text.strip().casefold().split())
    return any(normalized.startswith(prefix) for prefix in SUBJECT_PREFIXES)


def is_closing(text: str) -> bool:
    normalized = normalized_marker_free_text(text)
    return any(normalized.startswith(prefix) for prefix in CLOSING_PREFIXES)


def normalized_marker_free_text(text: str) -> str:
    normalized = " ".join(text.strip().casefold().split())
    for marker in ("[drawing]", "[symbol]", "[field]"):
        while normalized.startswith(marker):
            normalized = normalized.removeprefix(marker).lstrip()
    return normalized


def is_signature_drawing_boundary(paragraph: Any, text: str) -> bool:
    return (
        paragraph.find(".//" + qn("w:drawing")) is not None
        and not normalized_marker_free_text(text)
    )


def build_spans(
    paragraph: Any,
    *,
    paragraph_id: str,
    paragraph_editable: bool,
    hyperlink_targets: dict[str, str],
) -> tuple[list[CoverLetterSpan], list[dict[str, str]], list[dict[str, str]]]:
    tokens = inline_tokens(paragraph)
    spans: list[CoverLetterSpan] = []
    hyperlinks: list[dict[str, str]] = []
    protected_elements: list[dict[str, str]] = []
    hyperlink_ids: dict[int, str] = {}
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if token.hyperlink is not None:
            end = cursor + 1
            while end < len(tokens) and tokens[end].hyperlink is token.hyperlink:
                end += 1
            group = tokens[cursor:end]
            hyperlink_key = id(token.hyperlink)
            hyperlink_id = hyperlink_ids.setdefault(
                hyperlink_key,
                f"{paragraph_id}-hyperlink-{len(hyperlink_ids) + 1:04d}",
            )
            relationship_id = token.hyperlink.get(XML_RELATIONSHIP_ID, "")
            hyperlink = {
                "hyperlinkId": hyperlink_id,
                "target": hyperlink_targets.get(relationship_id, ""),
                "anchor": token.hyperlink.get(qn("w:anchor"), ""),
            }
            if not any(item["hyperlinkId"] == hyperlink_id for item in hyperlinks):
                hyperlinks.append(hyperlink)
            append_span(
                spans,
                paragraph_id=paragraph_id,
                span_type="hyperlink",
                tokens=group,
                editable=False,
                hyperlink=hyperlink,
            )
            protected_elements.append(
                {
                    "elementId": hyperlink_id,
                    "type": "hyperlink",
                    "original": "".join(item.original for item in group),
                }
            )
            cursor = end
            continue
        if token.token_type != "text":
            append_span(
                spans,
                paragraph_id=paragraph_id,
                span_type=token.token_type,
                tokens=[token],
                editable=False,
            )
            protected_elements.append(
                {
                    "elementId": f"{paragraph_id}-element-{len(protected_elements) + 1:04d}",
                    "type": token.token_type,
                    "original": token.original,
                }
            )
            cursor += 1
            continue

        signature = run_style_signature(token.run)
        end = cursor + 1
        while (
            end < len(tokens)
            and tokens[end].token_type == "text"
            and tokens[end].hyperlink is None
            and run_style_signature(tokens[end].run) == signature
        ):
            end += 1
        group = tokens[cursor:end]
        original = "".join(item.original for item in group)
        append_span(
            spans,
            paragraph_id=paragraph_id,
            span_type="text",
            tokens=group,
            editable=(paragraph_editable or is_date_line(original))
            and bool(original.strip()),
        )
        cursor = end
    return spans, hyperlinks, protected_elements


def is_date_line(text: str) -> bool:
    return DATE_LINE_PATTERN.search(text) is not None


def replace_date_in_line(text: str, replacement: str) -> str:
    return DATE_LINE_PATTERN.sub(replacement, text, count=1)


def append_span(
    spans: list[CoverLetterSpan],
    *,
    paragraph_id: str,
    span_type: CoverLetterSpanType,
    tokens: list[InlineToken],
    editable: bool,
    hyperlink: dict[str, str] | None = None,
) -> None:
    original = "".join(token.original for token in tokens)
    if not original:
        return
    spans.append(
        CoverLetterSpan(
            span_id=f"{paragraph_id}-span-{len(spans) + 1:04d}",
            span_type=span_type,
            original=original,
            style=run_style(tokens[0].run),
            editable=editable,
            hyperlink=hyperlink,
            text_nodes=tuple(token.text_node for token in tokens if token.text_node is not None),
        )
    )


def inline_tokens(paragraph: Any) -> list[InlineToken]:
    tokens: list[InlineToken] = []
    complex_field_depth = 0
    for node in paragraph.iter():
        if node is paragraph or nearest_paragraph(node) is not paragraph:
            continue
        run = nearest_ancestor(node, qn("w:r"))
        hyperlink = nearest_ancestor(node, qn("w:hyperlink"))
        if nearest_ancestor(node, qn("w:fldSimple")) is not None:
            continue
        if nearest_ancestor(node, qn("w:drawing")) is not None:
            continue
        if nearest_ancestor(node, qn("w:pict")) is not None:
            continue
        if node.tag == qn("w:fldSimple"):
            tokens.append(InlineToken("field", "[Field]", None, run, hyperlink))
            continue
        if node.tag == qn("w:fldChar"):
            field_type = node.get(qn("w:fldCharType"), "")
            if field_type == "begin":
                if complex_field_depth == 0:
                    tokens.append(InlineToken("field", "[Field]", None, run, hyperlink))
                complex_field_depth += 1
            elif field_type == "end":
                complex_field_depth = max(0, complex_field_depth - 1)
            continue
        if complex_field_depth:
            continue
        if node.tag in {qn("w:drawing"), qn("w:pict")}:
            tokens.append(InlineToken("drawing", "[Drawing]", None, run, hyperlink))
            continue
        if node.tag == qn("w:sym"):
            tokens.append(InlineToken("symbol", symbol_label(node), None, run, hyperlink))
            continue
        if node.tag == qn("w:t"):
            value = node.text or ""
            if "\t" in value or "\n" in value or "\r" in value:
                raise UnsupportedCoverLetterStructureError(
                    "Unsupported DOCX construction: literal tabs or line breaks inside w:t"
                )
            tokens.append(InlineToken("text", value, node, run, hyperlink))
        elif node.tag == qn("w:tab"):
            tokens.append(InlineToken("tab", "\t", None, run, hyperlink))
        elif node.tag in {qn("w:br"), qn("w:cr")}:
            tokens.append(InlineToken("lineBreak", "\n", None, run, hyperlink))
    return tokens


def replace_cover_letter_text_span(span: CoverLetterSpan, replacement: str) -> None:
    if not span.editable or span.span_type != "text":
        raise ValueError(f"Protected cover-letter span cannot be changed: {span.span_id}")
    if not replacement.strip():
        raise ValueError(f"Cover-letter span replacement cannot be empty: {span.span_id}")
    if any(control in replacement for control in ("\t", "\n", "\r")):
        raise ValueError(
            f"Cover-letter text span replacement cannot contain tabs or line breaks: {span.span_id}"
        )
    if not span.text_nodes:
        raise ValueError(f"Cover-letter span has no editable text node: {span.span_id}")
    first, *remaining = span.text_nodes
    set_text_node_value(first, replacement)
    for node in remaining:
        set_text_node_value(node, "")


def paragraph_text(paragraph: Any) -> str:
    return "".join(token.original for token in inline_tokens(paragraph))


def paragraph_style(paragraph: Any) -> dict[str, Any]:
    properties = paragraph.find(qn("w:pPr"))
    if properties is None:
        return {"paragraphStyle": "Normal"}
    style = properties.find(qn("w:pStyle"))
    alignment = properties.find(qn("w:jc"))
    return compact_dict(
        {
            "paragraphStyle": (style.get(qn("w:val"), "Normal") if style is not None else "Normal"),
            "alignment": alignment.get(qn("w:val"), "") if alignment is not None else "",
            "numbered": properties.find(qn("w:numPr")) is not None,
        }
    )


def run_style(run: Any | None) -> dict[str, Any]:
    properties = run.find(qn("w:rPr")) if run is not None else None
    if properties is None:
        return {}
    style = properties.find(qn("w:rStyle"))
    color = properties.find(qn("w:color"))
    size = properties.find(qn("w:sz"))
    fonts = properties.find(qn("w:rFonts"))
    underline = properties.find(qn("w:u"))
    return compact_dict(
        {
            "runStyle": style.get(qn("w:val"), "") if style is not None else "",
            "bold": properties.find(qn("w:b")) is not None,
            "italic": properties.find(qn("w:i")) is not None,
            "underline": underline.get(qn("w:val"), "single") if underline is not None else "",
            "color": color.get(qn("w:val"), "") if color is not None else "",
            "sizeHalfPoints": size.get(qn("w:val"), "") if size is not None else "",
            "font": fonts.get(qn("w:ascii"), "") if fonts is not None else "",
        },
    )


def run_style_signature(run: Any | None) -> bytes:
    properties = run.find(qn("w:rPr")) if run is not None else None
    return etree.tostring(properties) if properties is not None else b""


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", False)}


def extract_hyperlink_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    relationships_path = "word/_rels/document.xml.rels"
    if relationships_path not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read(relationships_path))
    return {
        relationship.get("Id", ""): relationship.get("Target", "")
        for relationship in root
        if relationship.get("Type", "").endswith("/hyperlink")
    }


def extract_hyperlink_targets_from_parts(parts: dict[str, bytes] | Any) -> dict[str, str]:
    relationships_path = "word/_rels/document.xml.rels"
    relationships = parts.get(relationships_path)
    if relationships is None:
        return {}
    root = etree.fromstring(relationships)
    return {
        relationship.get("Id", ""): relationship.get("Target", "")
        for relationship in root
        if relationship.get("Type", "").endswith("/hyperlink")
    }


def nearest_ancestor(element: Any | None, tag: str) -> Any | None:
    if element is None:
        return None
    ancestor = element.getparent()
    while ancestor is not None:
        if ancestor.tag == tag:
            return ancestor
        ancestor = ancestor.getparent()
    return None


def nearest_paragraph(element: Any) -> Any | None:
    return nearest_ancestor(element, qn("w:p"))
