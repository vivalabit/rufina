import re
from dataclasses import dataclass
from typing import Any

from docx.oxml.ns import qn
from lxml import etree


UNSUPPORTED_ELEMENTS = {
    "altChunk": "embedded alternative content",
    "customXml": "custom XML blocks",
    "del": "tracked deletions",
    "ins": "tracked insertions",
    "moveFrom": "tracked moves",
    "moveTo": "tracked moves",
    "noBreakHyphen": "special hyphen runs",
    "object": "embedded objects",
    "oMath": "equations",
    "oMathPara": "equations",
    "ptab": "positional tabs",
    "softHyphen": "special hyphen runs",
    "smartTag": "smart tags",
    "txbxContent": "text boxes",
}
SUPPORTED_WORD_FIELDS = {
    "AUTHOR",
    "COMMENTS",
    "CREATEDATE",
    "DATE",
    "DOCPROPERTY",
    "FILENAME",
    "FILESIZE",
    "HYPERLINK",
    "KEYWORDS",
    "LASTSAVEDBY",
    "NUMPAGES",
    "PAGE",
    "PAGEREF",
    "PRINTDATE",
    "REF",
    "REVNUM",
    "SAVEDATE",
    "SECTION",
    "SECTIONPAGES",
    "SUBJECT",
    "TIME",
    "TITLE",
}
UNSUPPORTED_CONTENT_CONTROL_PROPERTIES = {
    "checkBox": "checkbox content controls",
    "comboBox": "combo-box content controls",
    "date": "date content controls",
    "docPartObj": "document-part content controls",
    "dropDownList": "drop-down content controls",
    "picture": "picture content controls",
    "repeatingSection": "repeating-section content controls",
}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


class UnsupportedWordStructureError(ValueError):
    pass


@dataclass(frozen=True)
class UnsupportedWordConstruction:
    element: str
    description: str

    @property
    def message(self) -> str:
        return (
            "Unsupported DOCX construction: "
            f"{self.description} ({self.element})"
        )


def symbol_label(node: Any) -> str:
    return f"symbol:{node.get(qn('w:font'), '')}:{node.get(qn('w:char'), '')}"


def set_text_node_value(node: Any, value: str) -> None:
    node.text = value
    if value.startswith(" ") or value.endswith(" "):
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def validate_supported_word_structure(body: Any) -> None:
    unsupported = find_unsupported_word_constructions(body)
    if unsupported:
        raise UnsupportedWordStructureError(unsupported[0].message)


def find_unsupported_word_constructions(
    body: Any,
) -> list[UnsupportedWordConstruction]:
    issues: list[UnsupportedWordConstruction] = []
    seen: set[tuple[str, str]] = set()

    def append_issue(element: str, description: str) -> None:
        key = (element, description)
        if key not in seen:
            seen.add(key)
            issues.append(
                UnsupportedWordConstruction(
                    element=element,
                    description=description,
                )
            )

    field_stack: list[tuple[Any | None, list[str]]] = []
    for element in body.iter():
        local_name = etree.QName(element).localname
        unsupported = UNSUPPORTED_ELEMENTS.get(local_name)
        if unsupported:
            append_issue(local_name, unsupported)
        if local_name == "blip" and element.get(qn("r:link")):
            append_issue("drawing", "externally linked drawings")
        if local_name == "t":
            value = element.text or ""
            if "\t" in value or "\n" in value or "\r" in value:
                append_issue("t", "literal tabs or line breaks inside w:t")
        if local_name == "sdtPr":
            for property_element in element.iterchildren():
                property_name = etree.QName(property_element).localname
                unsupported_property = (
                    UNSUPPORTED_CONTENT_CONTROL_PROPERTIES.get(property_name)
                )
                if unsupported_property:
                    append_issue(property_name, unsupported_property)
        if local_name == "fldSimple":
            append_field_issue(
                append_issue,
                element.get(qn("w:instr"), ""),
            )
        elif local_name == "fldChar":
            field_type = element.get(qn("w:fldCharType"), "")
            if field_type == "begin":
                if field_stack:
                    append_issue("field", "nested Word fields")
                field_stack.append((nearest_paragraph(element), []))
            elif field_type == "end":
                if not field_stack:
                    append_issue(
                        "field",
                        "field end without a matching begin",
                    )
                else:
                    field_paragraph, instructions = field_stack.pop()
                    if field_paragraph is not nearest_paragraph(element):
                        append_issue(
                            "field",
                            "Word fields spanning multiple paragraphs",
                        )
                    append_field_issue(
                        append_issue,
                        "".join(instructions),
                    )
            elif field_type not in {"separate"}:
                append_issue(
                    "field",
                    f"unknown field marker {field_type or 'empty'}",
                )
        elif local_name == "instrText":
            if not field_stack:
                append_issue(
                    "field",
                    "field instruction without a matching begin",
                )
            else:
                field_stack[-1][1].append(element.text or "")
    if field_stack:
        append_issue("field", "field begin without a matching end")
    return issues


def append_field_issue(append_issue: Any, instruction: str) -> None:
    match = re.match(r"\s*([A-Za-z][A-Za-z0-9]*)\b", instruction)
    if not match:
        append_issue("field", "Word field has no supported instruction")
        return
    field_name = match.group(1).upper()
    if field_name not in SUPPORTED_WORD_FIELDS:
        append_issue("field", f"unsupported Word field {field_name}")


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


__all__ = [
    "UnsupportedWordConstruction",
    "UnsupportedWordStructureError",
    "find_unsupported_word_constructions",
    "set_text_node_value",
    "symbol_label",
    "validate_supported_word_structure",
]
