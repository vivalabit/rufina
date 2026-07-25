from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Any, Literal

from docx.oxml.ns import qn
from lxml import etree

from app.services.cover_letter_blocks import (
    UnsupportedCoverLetterStructureError,
    extract_hyperlink_targets_from_parts,
    parse_cover_letter_blocks,
)
from app.services.document_security import validate_and_read_docx_package
from app.services.word_structure import (
    find_unsupported_word_constructions,
)


AnalyzedDocumentType = Literal["cover_letter", "generic"]
SOURCE_CONTEXT_MAX_CHARS = 16_000
DOCUMENT_ANALYSIS_CACHE_SIZE = 64


@dataclass(frozen=True)
class DocumentAnalysisCacheInfo:
    hits: int
    misses: int
    size: int
    max_size: int


@dataclass(frozen=True)
class DocumentAnalysisResult:
    content_sha256: str
    document_type: AnalyzedDocumentType
    extracted_text: str
    format_name: str
    elements_key: str
    structured_elements_json: str
    preflight_json: str
    structure_error: str = ""

    def structured_elements(self) -> list[dict[str, Any]]:
        payload = json.loads(self.structured_elements_json)
        return payload if isinstance(payload, list) else []

    def preflight_report(self) -> dict[str, Any]:
        payload = json.loads(self.preflight_json)
        return payload if isinstance(payload, dict) else {}

    def build_ai_context(
        self,
        *,
        source_id: str,
        title: str,
        category: str,
        file_name: str,
        max_characters: int = SOURCE_CONTEXT_MAX_CHARS,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "id": source_id,
            "title": title,
            "category": category,
            "file_name": file_name,
            "format": self.format_name,
            self.elements_key: [],
        }
        elements = self.structured_elements()
        context[self.elements_key] = select_source_context_elements(
            elements,
            base_context=context,
            elements_key=self.elements_key,
            max_characters=max_characters,
        )
        return context


_analysis_cache: OrderedDict[tuple[str, AnalyzedDocumentType], DocumentAnalysisResult] = (
    OrderedDict()
)
_analysis_cache_lock = RLock()
_analysis_cache_hits = 0
_analysis_cache_misses = 0


def analyze_docx_source(
    content: bytes,
    document_type: AnalyzedDocumentType,
) -> DocumentAnalysisResult:
    global _analysis_cache_hits, _analysis_cache_misses

    content_sha256 = hashlib.sha256(content).hexdigest()
    cache_key = (content_sha256, document_type)
    with _analysis_cache_lock:
        cached = _analysis_cache.get(cache_key)
        if cached is not None:
            _analysis_cache.move_to_end(cache_key)
            _analysis_cache_hits += 1
            return cached
        _analysis_cache_misses += 1

    result = build_document_analysis(content, content_sha256, document_type)
    with _analysis_cache_lock:
        existing = _analysis_cache.get(cache_key)
        if existing is not None:
            _analysis_cache.move_to_end(cache_key)
            return existing
        _analysis_cache[cache_key] = result
        while len(_analysis_cache) > DOCUMENT_ANALYSIS_CACHE_SIZE:
            _analysis_cache.popitem(last=False)
    return result


def clear_document_analysis_cache() -> None:
    global _analysis_cache_hits, _analysis_cache_misses

    with _analysis_cache_lock:
        _analysis_cache.clear()
        _analysis_cache_hits = 0
        _analysis_cache_misses = 0


def document_analysis_cache_info() -> DocumentAnalysisCacheInfo:
    with _analysis_cache_lock:
        return DocumentAnalysisCacheInfo(
            hits=_analysis_cache_hits,
            misses=_analysis_cache_misses,
            size=len(_analysis_cache),
            max_size=DOCUMENT_ANALYSIS_CACHE_SIZE,
        )


def build_document_analysis(
    content: bytes,
    content_sha256: str,
    document_type: AnalyzedDocumentType,
) -> DocumentAnalysisResult:
    package = validate_and_read_docx_package(content)
    root = etree.fromstring(package.read("word/document.xml"))
    extracted_text = extract_body_text(root)
    body = root.find(qn("w:body"))
    format_name, elements_key, id_key = document_format(document_type)
    if body is None:
        report = unsupported_report(
            element="documentBody",
            description="DOCX has no document body",
        )
        return immutable_result(
            content_sha256=content_sha256,
            document_type=document_type,
            extracted_text=extracted_text,
            format_name=format_name,
            elements_key=elements_key,
            structured_elements=[],
            preflight=report,
            structure_error="DOCX has no document body",
        )

    document_issues = find_unsupported_word_constructions(body)
    if document_issues:
        rejected_elements = [
            {"element": issue.element, "description": issue.description}
            for issue in document_issues
        ]
        report = {
            "supported": False,
            "editableCount": 0,
            "immutableCount": 0,
            "immutableElements": [],
            "rejectedElements": rejected_elements,
            "sourceContext": empty_source_context(),
        }
        return immutable_result(
            content_sha256=content_sha256,
            document_type=document_type,
            extracted_text=extracted_text,
            format_name=format_name,
            elements_key=elements_key,
            structured_elements=[],
            preflight=report,
            structure_error=document_issues[0].message,
        )

    if document_type == "generic":
        return immutable_result(
            content_sha256=content_sha256,
            document_type=document_type,
            extracted_text=extracted_text,
            format_name=format_name,
            elements_key=elements_key,
            structured_elements=[],
            preflight={
                "supported": True,
                "editableCount": 0,
                "immutableCount": 0,
                "immutableElements": [],
                "rejectedElements": [],
                "sourceContext": empty_source_context(),
            },
        )

    try:
        hyperlink_targets = extract_hyperlink_targets_from_parts(package.parts)
        structured_elements = [
            paragraph.as_context()
            for paragraph in parse_cover_letter_blocks(
                body,
                hyperlink_targets=hyperlink_targets,
                validate_structure=False,
            )
        ]
    except UnsupportedCoverLetterStructureError as exc:
        description = str(exc).removeprefix("Unsupported DOCX construction: ")
        report = unsupported_report(element="mixedFormat", description=description)
        return immutable_result(
            content_sha256=content_sha256,
            document_type=document_type,
            extracted_text=extracted_text,
            format_name=format_name,
            elements_key=elements_key,
            structured_elements=[],
            preflight=report,
            structure_error=str(exc),
        )

    preflight = build_preflight_report(
        structured_elements,
        id_key=id_key,
        format_name=format_name,
    )
    return immutable_result(
        content_sha256=content_sha256,
        document_type=document_type,
        extracted_text=extracted_text,
        format_name=format_name,
        elements_key=elements_key,
        structured_elements=structured_elements,
        preflight=preflight,
    )


def immutable_result(
    *,
    content_sha256: str,
    document_type: AnalyzedDocumentType,
    extracted_text: str,
    format_name: str,
    elements_key: str,
    structured_elements: list[dict[str, Any]],
    preflight: dict[str, Any],
    structure_error: str = "",
) -> DocumentAnalysisResult:
    return DocumentAnalysisResult(
        content_sha256=content_sha256,
        document_type=document_type,
        extracted_text=extracted_text,
        format_name=format_name,
        elements_key=elements_key,
        structured_elements_json=json.dumps(
            structured_elements,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        preflight_json=json.dumps(
            preflight,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        structure_error=structure_error,
    )


def document_format(
    document_type: AnalyzedDocumentType,
) -> tuple[str, str, str]:
    if document_type == "generic":
        return "docx-text-v1", "elements", "id"
    return "cover-letter-blocks-v1", "paragraphs", "paragraphId"


def extract_body_text(root: Any) -> str:
    lines: list[str] = []
    for paragraph in root.iter(qn("w:p")):
        text = "".join(node.text or "" for node in paragraph.iter(qn("w:t"))).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def build_preflight_report(
    structured_elements: list[dict[str, Any]],
    *,
    id_key: str,
    format_name: str,
) -> dict[str, Any]:
    rejected_elements: list[dict[str, str]] = []
    immutable_elements: list[dict[str, str]] = []
    editable_count = 0
    for element in structured_elements:
        element_id = str(element[id_key])
        editable_spans = [span for span in element.get("spans", []) if span.get("editable")]
        editable_count += len(editable_spans)
        if not element.get("editable"):
            immutable_elements.append(
                immutable_item(
                    element_id,
                    str(element.get("type") or "protected"),
                    str(element.get("original") or ""),
                )
            )
        for span in element.get("spans", []):
            if span.get("editable"):
                continue
            if not element.get("editable") and span.get("type") == "text":
                continue
            immutable_elements.append(
                immutable_item(
                    str(span.get("spanId") or element_id),
                    str(span.get("type") or "protected"),
                    str(span.get("original") or ""),
                )
            )
    if editable_count == 0:
        rejected_elements.append(
            {
                "element": "editableText",
                "description": "no safely editable text spans were found",
            }
        )
    return {
        "supported": editable_count > 0 and not rejected_elements,
        "editableCount": editable_count,
        "immutableCount": len(immutable_elements),
        "immutableElements": immutable_elements[:100],
        "rejectedElements": rejected_elements,
        "sourceContext": source_context_report(
            structured_elements,
            elements_key=elements_key_for_id(id_key),
            format_name=format_name,
        ),
    }


def immutable_item(element_id: str, element_type: str, original: str) -> dict[str, str]:
    preview = " ".join(original.split())
    return {
        "id": element_id,
        "type": element_type,
        "text": preview[:180],
        "reason": "AI changes targeting this protected element will be rejected",
    }


def source_context_report(
    elements: list[dict[str, Any]],
    *,
    elements_key: str,
    format_name: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {"format": format_name, elements_key: []}
    total_characters = serialized_length({**base, elements_key: elements})
    included = select_source_context_elements(
        elements,
        base_context=base,
        elements_key=elements_key,
        max_characters=SOURCE_CONTEXT_MAX_CHARS,
    )
    included_characters = serialized_length({**base, elements_key: included})
    return {
        "totalElements": len(elements),
        "includedElements": len(included),
        "omittedElements": len(elements) - len(included),
        "estimatedCharacters": total_characters,
        "includedCharacters": included_characters,
        "truncated": len(included) < len(elements),
    }


def select_source_context_elements(
    elements: list[dict[str, Any]],
    *,
    base_context: dict[str, Any],
    elements_key: str,
    max_characters: int,
) -> list[dict[str, Any]]:
    selected_indexes: set[int] = set()

    def try_include(index: int) -> None:
        candidate_indexes = sorted({*selected_indexes, index})
        candidate = {
            **base_context,
            elements_key: [elements[item_index] for item_index in candidate_indexes],
        }
        if serialized_length(candidate) <= max_characters:
            selected_indexes.add(index)

    priority_indexes = [
        index
        for index, element in enumerate(elements)
        if element.get("editable") or element.get("type") == "heading"
    ]
    for index in priority_indexes:
        try_include(index)
    for index in range(len(elements)):
        if index not in selected_indexes:
            try_include(index)

    return [elements[index] for index in sorted(selected_indexes)]


def serialized_length(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def elements_key_for_id(id_key: str) -> str:
    return "blocks" if id_key == "blockId" else "paragraphs"


def empty_source_context() -> dict[str, int | bool]:
    return {
        "totalElements": 0,
        "includedElements": 0,
        "omittedElements": 0,
        "estimatedCharacters": 0,
        "includedCharacters": 0,
        "truncated": False,
    }


def unsupported_report(*, element: str, description: str) -> dict[str, Any]:
    return {
        "supported": False,
        "editableCount": 0,
        "immutableCount": 0,
        "immutableElements": [],
        "rejectedElements": [{"element": element, "description": description}],
        "sourceContext": empty_source_context(),
    }
