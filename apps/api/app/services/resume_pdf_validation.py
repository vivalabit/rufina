from __future__ import annotations

import re
import shutil
import struct
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

import pdfplumber
from pypdf import PdfReader, PdfWriter


PDF_RASTER_TIMEOUT_SECONDS = 30
PDF_TEMPLATE_ID_METADATA_KEY = "/ResumeTemplateId"
PDF_TEMPLATE_VERSION_METADATA_KEY = "/ResumeTemplateVersion"
PDF_RESUME_SCHEMA_METADATA_KEY = "/ResumeSchemaVersion"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PAGE_BOUNDARY_TOLERANCE_POINTS = 0.75


class ResumePdfValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResumePdfValidationPolicy:
    min_pages: int
    max_pages: int
    png_dpi: int
    reading_order: Literal["resumeSectionOrder", "primaryThenSidebar"]


@dataclass(frozen=True)
class ResumePdfValidationReport:
    page_count: int
    expected_text_fragment_count: int
    png_page_count: int
    template_id: str
    template_version: str
    overflow_issue_count: int


def stamp_resume_pdf_metadata(
    pdf: bytes,
    *,
    template_id: str,
    template_version: str,
    resume_schema_version: str,
) -> bytes:
    try:
        reader = PdfReader(BytesIO(pdf))
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        metadata = {
            key: str(value)
            for key, value in (reader.metadata or {}).items()
            if isinstance(key, str) and value is not None
        }
        metadata.update(
            {
                PDF_TEMPLATE_ID_METADATA_KEY: template_id,
                PDF_TEMPLATE_VERSION_METADATA_KEY: template_version,
                PDF_RESUME_SCHEMA_METADATA_KEY: resume_schema_version,
            }
        )
        writer.add_metadata(metadata)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()
    except Exception as exc:
        raise ResumePdfValidationError(
            "Rendered resume PDF metadata could not be written"
        ) from exc


def validate_resume_pdf(
    pdf: bytes,
    *,
    expected_text_fragments: list[str],
    template_id: str,
    template_version: str,
    resume_schema_version: str,
    policy: ResumePdfValidationPolicy,
    html_overflow_issues: tuple[str, ...] = (),
) -> ResumePdfValidationReport:
    if not pdf.startswith(b"%PDF-"):
        raise ResumePdfValidationError("Chromium returned an invalid PDF")
    try:
        reader = PdfReader(BytesIO(pdf))
    except Exception as exc:
        raise ResumePdfValidationError(
            "Rendered resume PDF cannot be parsed"
        ) from exc

    page_count = len(reader.pages)
    if not policy.min_pages <= page_count <= policy.max_pages:
        raise ResumePdfValidationError(
            "Rendered resume PDF page count is outside the template limits: "
            f"{page_count} not in {policy.min_pages}..{policy.max_pages}"
        )
    validate_template_metadata(
        reader,
        template_id=template_id,
        template_version=template_version,
        resume_schema_version=resume_schema_version,
    )

    extracted_pages = [
        page.extract_text(extraction_mode="plain") or ""
        for page in reader.pages
    ]
    if any(not normalize_pdf_text(page_text) for page_text in extracted_pages):
        raise ResumePdfValidationError(
            "Rendered resume PDF contains an empty text page"
        )
    extracted_text = normalize_pdf_text("\n".join(extracted_pages))
    normalized_fragments = [
        normalized
        for fragment in expected_text_fragments
        if (normalized := normalize_pdf_text(fragment))
    ]
    validate_expected_text(extracted_text, normalized_fragments)
    validate_reading_order(extracted_text, normalized_fragments)

    pdf_overflow_issues = inspect_pdf_overflow(pdf)
    overflow_issues = (*html_overflow_issues, *pdf_overflow_issues)
    if overflow_issues:
        raise ResumePdfValidationError(
            "Rendered resume PDF contains overflow: "
            + "; ".join(overflow_issues[:5])
        )

    png_page_count = render_and_validate_png_pages(
        pdf,
        expected_page_count=page_count,
        dpi=policy.png_dpi,
    )
    return ResumePdfValidationReport(
        page_count=page_count,
        expected_text_fragment_count=len(normalized_fragments),
        png_page_count=png_page_count,
        template_id=template_id,
        template_version=template_version,
        overflow_issue_count=0,
    )


def validate_template_metadata(
    reader: PdfReader,
    *,
    template_id: str,
    template_version: str,
    resume_schema_version: str,
) -> None:
    metadata = reader.metadata or {}
    actual = {
        PDF_TEMPLATE_ID_METADATA_KEY: metadata.get(PDF_TEMPLATE_ID_METADATA_KEY),
        PDF_TEMPLATE_VERSION_METADATA_KEY: metadata.get(
            PDF_TEMPLATE_VERSION_METADATA_KEY
        ),
        PDF_RESUME_SCHEMA_METADATA_KEY: metadata.get(
            PDF_RESUME_SCHEMA_METADATA_KEY
        ),
    }
    expected = {
        PDF_TEMPLATE_ID_METADATA_KEY: template_id,
        PDF_TEMPLATE_VERSION_METADATA_KEY: template_version,
        PDF_RESUME_SCHEMA_METADATA_KEY: resume_schema_version,
    }
    if actual != expected:
        raise ResumePdfValidationError(
            "Rendered resume PDF template metadata does not match the manifest"
        )


def validate_expected_text(
    extracted_text: str,
    expected_fragments: list[str],
) -> None:
    missing = [
        fragment
        for fragment in expected_fragments
        if fragment not in extracted_text
    ]
    if missing:
        raise ResumePdfValidationError(
            "Rendered resume PDF is missing expected text: "
            + ", ".join(repr(fragment) for fragment in missing[:5])
        )


def validate_reading_order(
    extracted_text: str,
    expected_fragments: list[str],
) -> None:
    cursor = 0
    for fragment in expected_fragments:
        position = extracted_text.find(fragment, cursor)
        if position < 0:
            raise ResumePdfValidationError(
                "Rendered resume PDF reading order does not match the template: "
                f"{fragment!r}"
            )
        cursor = position + len(fragment)


def inspect_pdf_overflow(pdf: bytes) -> tuple[str, ...]:
    issues: list[str] = []
    try:
        with pdfplumber.open(BytesIO(pdf)) as document:
            for page_number, page in enumerate(document.pages, start=1):
                for character in page.chars:
                    x0 = float(character.get("x0", 0))
                    x1 = float(character.get("x1", 0))
                    top = float(character.get("top", 0))
                    bottom = float(character.get("bottom", 0))
                    if (
                        x0 < -PAGE_BOUNDARY_TOLERANCE_POINTS
                        or top < -PAGE_BOUNDARY_TOLERANCE_POINTS
                        or x1 > page.width + PAGE_BOUNDARY_TOLERANCE_POINTS
                        or bottom > page.height + PAGE_BOUNDARY_TOLERANCE_POINTS
                    ):
                        issues.append(
                            f"page {page_number} has text outside its media box"
                        )
                        break
    except Exception as exc:
        raise ResumePdfValidationError(
            "Rendered resume PDF geometry could not be inspected"
        ) from exc
    return tuple(issues)


def render_and_validate_png_pages(
    pdf: bytes,
    *,
    expected_page_count: int,
    dpi: int,
) -> int:
    rasterizer = shutil.which("pdftoppm")
    if not rasterizer:
        raise ResumePdfValidationError(
            "Rendered resume PDF validation requires pdftoppm"
        )
    with tempfile.TemporaryDirectory(prefix="resume-pdf-validation-") as directory:
        workdir = Path(directory)
        pdf_path = workdir / "resume.pdf"
        pdf_path.write_bytes(pdf)
        try:
            result = subprocess.run(
                [
                    rasterizer,
                    "-png",
                    "-r",
                    str(dpi),
                    str(pdf_path),
                    str(workdir / "page"),
                ],
                capture_output=True,
                text=True,
                timeout=PDF_RASTER_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ResumePdfValidationError(
                "Rendered resume PDF PNG validation timed out"
            ) from exc
        images = sorted(workdir.glob("page-*.png"), key=png_page_number)
        if result.returncode != 0 or len(images) != expected_page_count:
            detail = (
                result.stderr
                or result.stdout
                or "incomplete PNG page rendering"
            ).strip()
            raise ResumePdfValidationError(
                "Rendered resume PDF PNG validation failed: "
                f"{detail[:240]}"
            )
        for image in images:
            validate_png(image)
        return len(images)


def validate_png(path: Path) -> None:
    content = path.read_bytes()
    if len(content) < 33 or not content.startswith(PNG_SIGNATURE):
        raise ResumePdfValidationError(
            "Rendered resume PDF produced an invalid PNG page"
        )
    width, height = struct.unpack(">II", content[16:24])
    if width < 100 or height < 100:
        raise ResumePdfValidationError(
            "Rendered resume PDF produced an invalid PNG page size"
        )


def png_page_number(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    return int(match.group(1)) if match else 0


def normalize_pdf_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"[\u2010-\u2015\u2212]", "-", normalized)
    return " ".join(normalized.split()).casefold()


__all__ = [
    "PDF_RESUME_SCHEMA_METADATA_KEY",
    "PDF_TEMPLATE_ID_METADATA_KEY",
    "PDF_TEMPLATE_VERSION_METADATA_KEY",
    "ResumePdfValidationError",
    "ResumePdfValidationPolicy",
    "ResumePdfValidationReport",
    "inspect_pdf_overflow",
    "normalize_pdf_text",
    "render_and_validate_png_pages",
    "stamp_resume_pdf_metadata",
    "validate_expected_text",
    "validate_reading_order",
    "validate_resume_pdf",
    "validate_template_metadata",
]
