from __future__ import annotations

import csv
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from statistics import median
from xml.etree import ElementTree

from app.models.resume import (
    ResumeSourceBoundingBox,
    ResumeSourceExtraction,
    ResumeSourceFragment,
)
from app.services.document_security import (
    DocumentSecurityError,
    validate_and_read_docx_package,
)


PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MIN_TEXT_LAYER_CHARACTERS = 24
PDF_EXTRACTION_TIMEOUT_SECONDS = 30
OCR_TIMEOUT_SECONDS = 60
MAX_PDF_PAGES = 50
MAX_SOURCE_FRAGMENTS = 10_000
MAX_SOURCE_BYTES = 15_000_000
DEFAULT_OCR_LANGUAGES = "eng+deu+fra"


class ResumeSourceExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class _SourceLine:
    page_number: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    extraction_method: str
    column_index: int | None = None

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class _PdfPage:
    page_number: int
    width: float
    height: float
    lines: tuple[_SourceLine, ...]


def extract_resume_source(
    *,
    file_name: str,
    content_type: str,
    content: bytes,
    ocr_languages: str = DEFAULT_OCR_LANGUAGES,
) -> ResumeSourceExtraction:
    if not content:
        raise ResumeSourceExtractionError("Resume source is empty")
    if len(content) > MAX_SOURCE_BYTES:
        raise ResumeSourceExtractionError(
            f"Resume source exceeds the {MAX_SOURCE_BYTES}-byte import limit"
        )
    lower_name = file_name.casefold()
    if lower_name.endswith(".docx") or content_type == DOCX_CONTENT_TYPE:
        return extract_docx_source_fragments(content)
    if lower_name.endswith(".pdf") or content_type == PDF_CONTENT_TYPE:
        return extract_pdf_source_fragments(
            content,
            ocr_languages=ocr_languages,
        )
    raise ResumeSourceExtractionError("Resume source must be a PDF or DOCX file")


def extract_docx_source_fragments(content: bytes) -> ResumeSourceExtraction:
    try:
        package = validate_and_read_docx_package(content)
        document_root = ElementTree.fromstring(package.read("word/document.xml"))
    except (DocumentSecurityError, ElementTree.ParseError) as exc:
        raise ResumeSourceExtractionError(f"Could not read DOCX source: {exc}") from exc

    raw_fragments: list[tuple[str, str, int | None]] = []
    for name in sorted(
        part_name
        for part_name in package.parts
        if re.fullmatch(r"word/header\d+\.xml", part_name)
    ):
        raw_fragments.extend(
            (text, "header", None)
            for text in _all_docx_paragraph_texts(package.read(name))
        )

    body = next(
        (element for element in document_root.iter() if _local_name(element.tag) == "body"),
        None,
    )
    if body is None:
        raise ResumeSourceExtractionError("DOCX source does not contain a document body")

    declared_columns = _declared_docx_column_count(body)
    current_column = 0
    for child in body:
        child_name = _local_name(child.tag)
        if child_name == "p":
            text = _docx_paragraph_text(child)
            if text:
                column = current_column if declared_columns > 1 else None
                raw_fragments.append((text, "paragraph", column))
            if _contains_docx_column_break(child):
                current_column = min(current_column + 1, 1)
        elif child_name == "tbl":
            raw_fragments.extend(_docx_table_fragments(child))

    for name in sorted(
        part_name
        for part_name in package.parts
        if re.fullmatch(r"word/footer\d+\.xml", part_name)
    ):
        raw_fragments.extend(
            (text, "footer", None)
            for text in _all_docx_paragraph_texts(package.read(name))
        )

    has_second_column = declared_columns > 1 or any(
        column == 1 for _, _, column in raw_fragments
    )
    fragments = [
        ResumeSourceFragment(
            id=f"source:fragment-{index + 1:06d}",
            text=text,
            order=index,
            page_number=None,
            column_index=column,
            kind=kind,
            extraction_method="docx",
            bbox=None,
        )
        for index, (text, kind, column) in enumerate(
            raw_fragments[:MAX_SOURCE_FRAGMENTS]
        )
    ]
    return ResumeSourceExtraction(
        source_format="docx",
        layout="two_column" if has_second_column else "one_column",
        page_count=None,
        used_ocr=False,
        fragments=fragments,
    )


def extract_pdf_source_fragments(
    content: bytes,
    *,
    ocr_languages: str = DEFAULT_OCR_LANGUAGES,
) -> ResumeSourceExtraction:
    with tempfile.TemporaryDirectory(prefix="rufina-resume-import-") as directory:
        workdir = Path(directory)
        input_path = workdir / "resume.pdf"
        input_path.write_bytes(content)
        pages = _extract_pdf_text_pages(input_path, workdir)
        if len(pages) > MAX_PDF_PAGES:
            raise ResumeSourceExtractionError(
                f"Resume PDF exceeds the {MAX_PDF_PAGES}-page import limit"
            )

        used_ocr = False
        resolved_pages: list[_PdfPage] = []
        for page in pages:
            text_characters = sum(
                sum(character.isalnum() for character in line.text)
                for line in page.lines
            )
            if text_characters >= MIN_TEXT_LAYER_CHARACTERS:
                resolved_pages.append(page)
                continue
            ocr_lines = _extract_pdf_ocr_page(
                input_path,
                workdir,
                page=page,
                ocr_languages=ocr_languages,
            )
            ocr_characters = sum(
                sum(character.isalnum() for character in line.text)
                for line in ocr_lines
            )
            if ocr_characters > text_characters:
                used_ocr = True
                resolved_pages.append(replace(page, lines=tuple(ocr_lines)))
            else:
                resolved_pages.append(page)

    ordered_lines: list[_SourceLine] = []
    page_layouts: list[str] = []
    for page in resolved_pages:
        page_lines, page_layout = _order_pdf_page_lines(list(page.lines))
        ordered_lines.extend(page_lines)
        page_layouts.append(page_layout)

    if not ordered_lines:
        raise ResumeSourceExtractionError("Could not extract text from resume PDF")
    if len(ordered_lines) > MAX_SOURCE_FRAGMENTS:
        raise ResumeSourceExtractionError(
            f"Resume source exceeds the {MAX_SOURCE_FRAGMENTS}-fragment import limit"
        )

    fragments = [
        ResumeSourceFragment(
            id=f"source:fragment-{index + 1:06d}",
            text=line.text,
            order=index,
            page_number=line.page_number,
            column_index=line.column_index,
            kind="line",
            extraction_method=line.extraction_method,
            bbox=ResumeSourceBoundingBox(
                x0=line.x0,
                y0=line.y0,
                x1=line.x1,
                y1=line.y1,
            ),
        )
        for index, line in enumerate(ordered_lines)
    ]
    unique_layouts = set(page_layouts)
    layout = (
        "mixed"
        if len(unique_layouts) > 1
        else ("two_column" if "two_column" in unique_layouts else "one_column")
    )
    return ResumeSourceExtraction(
        source_format="pdf",
        layout=layout,
        page_count=len(resolved_pages),
        used_ocr=used_ocr,
        fragments=fragments,
    )


def _extract_pdf_text_pages(input_path: Path, workdir: Path) -> list[_PdfPage]:
    executable = shutil.which("pdftotext")
    if executable is None:
        raise ResumeSourceExtractionError("Poppler pdftotext is required for PDF import")
    output_path = workdir / "resume-bbox.xhtml"
    try:
        result = subprocess.run(
            [
                executable,
                "-bbox-layout",
                "-enc",
                "UTF-8",
                str(input_path),
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=PDF_EXTRACTION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ResumeSourceExtractionError("Resume PDF text extraction timed out") from exc
    except OSError as exc:
        raise ResumeSourceExtractionError("Could not start Poppler PDF extraction") from exc
    if result.returncode != 0 or not output_path.exists():
        detail = _subprocess_error_detail(result)
        raise ResumeSourceExtractionError(
            f"Could not read resume PDF text layer ({detail})"
        )
    try:
        return _parse_pdf_bbox_xml(output_path.read_bytes())
    except ElementTree.ParseError as exc:
        raise ResumeSourceExtractionError("Poppler returned malformed PDF layout") from exc


def _parse_pdf_bbox_xml(content: bytes) -> list[_PdfPage]:
    root = ElementTree.fromstring(content)
    pages: list[_PdfPage] = []
    for page_number, page_element in enumerate(
        (
            element
            for element in root.iter()
            if _local_name(element.tag) == "page"
        ),
        start=1,
    ):
        width = max(_float_attribute(page_element, "width"), 1)
        height = max(_float_attribute(page_element, "height"), 1)
        lines: list[_SourceLine] = []
        for line_element in page_element.iter():
            if _local_name(line_element.tag) != "line":
                continue
            words = [
                _normalize_fragment_text(word.text or "")
                for word in line_element.iter()
                if _local_name(word.tag) == "word"
            ]
            text = _normalize_fragment_text(" ".join(word for word in words if word))
            if not text:
                continue
            box = _normalized_xml_box(line_element, width=width, height=height)
            if box is None:
                continue
            lines.append(
                _SourceLine(
                    page_number=page_number,
                    text=text,
                    x0=box[0],
                    y0=box[1],
                    x1=box[2],
                    y1=box[3],
                    extraction_method="pdf_text",
                )
            )
        pages.append(
            _PdfPage(
                page_number=page_number,
                width=width,
                height=height,
                lines=tuple(lines),
            )
        )
    if not pages:
        raise ResumeSourceExtractionError("Resume PDF does not contain any pages")
    return pages


def _extract_pdf_ocr_page(
    input_path: Path,
    workdir: Path,
    *,
    page: _PdfPage,
    ocr_languages: str,
) -> list[_SourceLine]:
    rasterizer = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if rasterizer is None or tesseract is None:
        if page.lines:
            return list(page.lines)
        raise ResumeSourceExtractionError(
            "Tesseract OCR and Poppler pdftoppm are required for scanned PDF import"
        )

    output_prefix = workdir / f"ocr-page-{page.page_number:04d}"
    try:
        raster_result = subprocess.run(
            [
                rasterizer,
                "-f",
                str(page.page_number),
                "-l",
                str(page.page_number),
                "-r",
                "240",
                "-png",
                "-singlefile",
                str(input_path),
                str(output_prefix),
            ],
            capture_output=True,
            text=True,
            timeout=OCR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ResumeSourceExtractionError(
            "Scanned resume page rasterization timed out"
        ) from exc
    except OSError as exc:
        raise ResumeSourceExtractionError(
            "Could not start scanned resume rasterization"
        ) from exc
    image_path = output_prefix.with_suffix(".png")
    if raster_result.returncode != 0 or not image_path.exists():
        raise ResumeSourceExtractionError(
            f"Could not rasterize scanned resume page "
            f"({_subprocess_error_detail(raster_result)})"
        )

    try:
        ocr_result = subprocess.run(
            [
                tesseract,
                str(image_path),
                "stdout",
                "-l",
                ocr_languages,
                "--psm",
                "3",
                "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=OCR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ResumeSourceExtractionError("Scanned resume OCR timed out") from exc
    except OSError as exc:
        raise ResumeSourceExtractionError("Could not start Tesseract OCR") from exc
    if ocr_result.returncode != 0:
        raise ResumeSourceExtractionError(
            f"Could not OCR scanned resume page "
            f"({_subprocess_error_detail(ocr_result)})"
        )
    return _parse_tesseract_tsv(
        ocr_result.stdout,
        page_number=page.page_number,
    )


def _parse_tesseract_tsv(value: str, *, page_number: int) -> list[_SourceLine]:
    reader = csv.DictReader(StringIO(value), delimiter="\t")
    words_by_line: dict[tuple[str, str, str], list[tuple[str, int, int, int, int]]] = {}
    image_width = 0
    image_height = 0
    for row in reader:
        try:
            level = int(row.get("level") or 0)
            left = int(row.get("left") or 0)
            top = int(row.get("top") or 0)
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
        except ValueError:
            continue
        if level == 1:
            image_width = max(image_width, width)
            image_height = max(image_height, height)
            continue
        if level != 5:
            continue
        text = _normalize_fragment_text(row.get("text") or "")
        if not text or width <= 0 or height <= 0:
            continue
        try:
            confidence = float(row.get("conf") or -1)
        except ValueError:
            confidence = -1
        if confidence < 0:
            continue
        key = (
            row.get("block_num") or "",
            row.get("par_num") or "",
            row.get("line_num") or "",
        )
        words_by_line.setdefault(key, []).append((text, left, top, width, height))
        image_width = max(image_width, left + width)
        image_height = max(image_height, top + height)

    if image_width <= 0 or image_height <= 0:
        return []
    lines: list[_SourceLine] = []
    for words in words_by_line.values():
        ordered_words = sorted(words, key=lambda item: item[1])
        text = _normalize_fragment_text(" ".join(item[0] for item in ordered_words))
        x0 = min(item[1] for item in words) / image_width
        y0 = min(item[2] for item in words) / image_height
        x1 = max(item[1] + item[3] for item in words) / image_width
        y1 = max(item[2] + item[4] for item in words) / image_height
        if text and x1 > x0 and y1 > y0:
            lines.append(
                _SourceLine(
                    page_number=page_number,
                    text=text,
                    x0=_clamp_coordinate(x0),
                    y0=_clamp_coordinate(y0),
                    x1=_clamp_coordinate(x1),
                    y1=_clamp_coordinate(y1),
                    extraction_method="pdf_ocr",
                )
            )
    return sorted(lines, key=lambda line: (line.y0, line.x0))


def _order_pdf_page_lines(
    lines: list[_SourceLine],
) -> tuple[list[_SourceLine], str]:
    if not lines:
        return [], "one_column"
    gutter = _detect_two_column_gutter(lines)
    if gutter is None:
        return (
            [
                replace(line, column_index=0)
                for line in sorted(lines, key=lambda item: (item.y0, item.x0))
            ],
            "one_column",
        )

    left = [line for line in lines if line.x1 <= gutter]
    right = [line for line in lines if line.x0 >= gutter]
    spanning = [
        line
        for line in lines
        if line not in left and line not in right
    ]
    ordered: list[_SourceLine] = []
    consumed: set[int] = set()

    def append_band(limit: float) -> None:
        for column_index, column_lines in ((0, left), (1, right)):
            for line in sorted(column_lines, key=lambda item: (item.y0, item.x0)):
                line_identity = id(line)
                if line_identity in consumed or line.center_y >= limit:
                    continue
                consumed.add(line_identity)
                ordered.append(replace(line, column_index=column_index))

    for separator in sorted(spanning, key=lambda item: (item.y0, item.x0)):
        append_band(separator.center_y)
        consumed.add(id(separator))
        ordered.append(replace(separator, column_index=None))
    append_band(float("inf"))
    return ordered, "two_column"


def _detect_two_column_gutter(lines: list[_SourceLine]) -> float | None:
    candidates = [
        line
        for line in lines
        if 0.06 <= line.width <= 0.72 and len(line.text) >= 2
    ]
    if len(candidates) < 4:
        return None

    best: tuple[float, float] | None = None
    for step in range(17):
        gutter = 0.25 + step * 0.025
        left = [line for line in candidates if line.x1 <= gutter]
        right = [line for line in candidates if line.x0 >= gutter]
        crossing_count = len(candidates) - len(left) - len(right)
        if len(left) < 2 or len(right) < 2:
            continue
        if median(line.width for line in left) < 0.075:
            continue
        if median(line.width for line in right) < 0.075:
            continue
        overlap_top = max(
            min(line.center_y for line in left),
            min(line.center_y for line in right),
        )
        overlap_bottom = min(
            max(line.center_y for line in left),
            max(line.center_y for line in right),
        )
        if overlap_bottom - overlap_top < 0.1:
            continue
        crossing_ratio = crossing_count / len(candidates)
        if crossing_ratio > 0.35:
            continue
        balance_penalty = abs(len(left) - len(right)) / len(candidates)
        score = crossing_ratio + balance_penalty * 0.1
        if best is None or score < best[0]:
            best = (score, gutter)
    return best[1] if best is not None else None


def _docx_table_fragments(
    table: ElementTree.Element,
) -> list[tuple[str, str, int | None]]:
    fragments: list[tuple[str, str, int | None]] = []
    rows = [child for child in table if _local_name(child.tag) == "tr"]
    for row in rows:
        cells = [child for child in row if _local_name(child.tag) == "tc"]
        use_columns = len(cells) == 2
        for cell_index, cell in enumerate(cells):
            column = cell_index if use_columns else None
            for paragraph in cell.iter():
                if _local_name(paragraph.tag) != "p":
                    continue
                text = _docx_paragraph_text(paragraph)
                if text:
                    fragments.append((text, "table_cell", column))
    return fragments


def _all_docx_paragraph_texts(content: bytes) -> list[str]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ResumeSourceExtractionError("DOCX contains malformed XML") from exc
    return [
        text
        for paragraph in root.iter()
        if _local_name(paragraph.tag) == "p"
        and (text := _docx_paragraph_text(paragraph))
    ]


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    tokens: list[str] = []
    for element in paragraph.iter():
        name = _local_name(element.tag)
        if name == "t":
            tokens.append(element.text or "")
        elif name == "tab":
            tokens.append("\t")
        elif name in {"br", "cr"}:
            tokens.append("\n")
    return _normalize_fragment_text("".join(tokens))


def _declared_docx_column_count(body: ElementTree.Element) -> int:
    counts: list[int] = []
    for element in body.iter():
        if _local_name(element.tag) != "cols":
            continue
        raw_number = next(
            (
                value
                for key, value in element.attrib.items()
                if _local_name(key) == "num"
            ),
            "",
        )
        try:
            counts.append(int(raw_number))
        except ValueError:
            explicit_columns = sum(
                1 for child in element if _local_name(child.tag) == "col"
            )
            if explicit_columns:
                counts.append(explicit_columns)
    return max(counts, default=1)


def _contains_docx_column_break(paragraph: ElementTree.Element) -> bool:
    return any(
        _local_name(element.tag) == "br"
        and any(
            _local_name(key) == "type" and value == "column"
            for key, value in element.attrib.items()
        )
        for element in paragraph.iter()
    )


def _normalized_xml_box(
    element: ElementTree.Element,
    *,
    width: float,
    height: float,
) -> tuple[float, float, float, float] | None:
    x0 = _float_attribute(element, "xMin") / width
    y0 = _float_attribute(element, "yMin") / height
    x1 = _float_attribute(element, "xMax") / width
    y1 = _float_attribute(element, "yMax") / height
    if x1 <= x0 or y1 <= y0:
        return None
    return (
        _clamp_coordinate(x0),
        _clamp_coordinate(y0),
        _clamp_coordinate(x1),
        _clamp_coordinate(y1),
    )


def _float_attribute(element: ElementTree.Element, name: str) -> float:
    try:
        return float(element.attrib.get(name, "0"))
    except ValueError:
        return 0


def _normalize_fragment_text(value: str) -> str:
    return re.sub(r"[ \t\f\v]+", " ", value).strip()


def _clamp_coordinate(value: float) -> float:
    return max(0, min(1, value))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _subprocess_error_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "unknown extraction error").strip()
    return detail[:240]


__all__ = [
    "DEFAULT_OCR_LANGUAGES",
    "DOCX_CONTENT_TYPE",
    "PDF_CONTENT_TYPE",
    "ResumeSourceExtractionError",
    "extract_docx_source_fragments",
    "extract_pdf_source_fragments",
    "extract_resume_source",
]
