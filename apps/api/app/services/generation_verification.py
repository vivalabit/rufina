from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.models.generation_workflow import DraftBundle, FitKeyword
from app.services.generation_latex import CompiledDocument
from app.services.generation_resources import RESOURCE_ROOT

VERIFY_LAYOUT_PATH = RESOURCE_ROOT / "upstream" / "tools" / "verify_layout.py"


class PdfCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: Literal["passed", "failed", "warning"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PdfVerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    document_type: Literal["tailored_resume", "cover_letter"] = Field(alias="documentType")
    page_count: int = Field(alias="pageCount", ge=0)
    extracted_text: str = Field(alias="extractedText")
    checks: tuple[PdfCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.status != "failed" for check in self.checks)


@dataclass(frozen=True)
class VerifiedPdf:
    report: PdfVerificationReport
    page_images: tuple[bytes, ...]


def verify_compiled_document(
    document: CompiledDocument,
    *,
    bundle: DraftBundle,
    keywords: tuple[FitKeyword, ...] = (),
    max_pages: int | None = None,
) -> VerifiedPdf:
    checks: list[PdfCheck] = []
    try:
        reader = PdfReader(BytesIO(document.pdf))
        pages = len(reader.pages)
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        checks.append(_check("pdf_readable", True, f"PDF opened with {pages} page(s)"))
    except (PdfReadError, TypeError, ValueError) as exc:
        report = PdfVerificationReport(
            documentType=document.document_type,
            pageCount=0,
            extractedText="",
            checks=(_check("pdf_readable", False, f"PDF could not be read: {exc}"),),
        )
        return VerifiedPdf(report=report, page_images=())

    normalized = _normalized(extracted)
    checks.append(
        _check(
            "text_layer",
            len(normalized) >= 50,
            f"Extracted {len(normalized)} non-layout characters",
        )
    )
    effective_max = max_pages or (2 if document.document_type == "tailored_resume" else 1)
    checks.append(
        _check(
            "page_count",
            1 <= pages <= effective_max,
            f"Found {pages} page(s); allowed 1-{effective_max}",
            {"actual": pages, "maximum": effective_max},
        )
    )
    basics = bundle.resume.basics if bundle.resume is not None else None
    full_name = basics.full_name if basics is not None else bundle.cover_letter.signature
    checks.append(
        _check(
            "candidate_name",
            _contains(extracted, full_name),
            "Candidate name is present"
            if _contains(extracted, full_name)
            else "Candidate name is missing",
        )
    )
    forbidden = "�" in extracted or bool(re.search(r"\(cid:\d+\)", extracted))
    checks.append(
        _check(
            "glyph_integrity",
            not forbidden,
            "No replacement glyphs or cid markers found"
            if not forbidden
            else "Broken glyph markers found",
        )
    )
    is_resume = document.document_type == "tailored_resume"
    if basics is not None and is_resume:
        for label, value in (("email", basics.email), ("phone", basics.phone)):
            if value:
                present = _contains(extracted, value)
                checks.append(
                    _check(
                        f"contact_{label}",
                        present,
                        f"{label.title()} is present" if present else f"{label.title()} is missing",
                    )
                )
        for experience in bundle.resume.experiences:
            present = _contains(extracted, experience.period)
            checks.append(
                _check(
                    f"role_dates:{experience.master_experience_id}",
                    present,
                    f"Role period {experience.period!r} is {'present' if present else 'missing'}",
                )
            )
    checks.extend(_keyword_checks(extracted, keywords))

    with tempfile.TemporaryDirectory(prefix="tasko-pdf-check-") as temp_directory:
        workdir = Path(temp_directory)
        pdf_path = workdir / "document.pdf"
        pdf_path.write_bytes(document.pdf)
        images, image_check = _render_pages(pdf_path, workdir)
        checks.append(image_check)
        checks.append(_layout_check(pdf_path))
    return VerifiedPdf(
        report=PdfVerificationReport(
            documentType=document.document_type,
            pageCount=pages,
            extractedText=extracted,
            checks=tuple(checks),
        ),
        page_images=images,
    )


def _render_pages(pdf_path: Path, workdir: Path) -> tuple[tuple[bytes, ...], PdfCheck]:
    executable = shutil.which("pdftoppm")
    if executable is None:
        return (), _check("page_images", False, "pdftoppm is unavailable")
    prefix = workdir / "page"
    try:
        subprocess.run(
            [executable, "-png", "-r", "120", str(pdf_path), str(prefix)],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (), _check("page_images", False, f"Could not render page images: {exc}")
    paths = sorted(workdir.glob("page-*.png"))
    images = tuple(path.read_bytes() for path in paths)
    return images, _check(
        "page_images",
        bool(images),
        f"Rendered {len(images)} page image(s)",
    )


def _layout_check(pdf_path: Path) -> PdfCheck:
    try:
        result = subprocess.run(
            [sys.executable, str(VERIFY_LAYOUT_PATH), str(pdf_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _check("layout_geometry", False, f"Layout check could not run: {exc}")
    detail = (result.stdout or result.stderr or "Layout check returned no detail").strip()
    return PdfCheck(
        name="layout_geometry",
        status="passed" if result.returncode == 0 else "failed",
        message=detail[-2_000:],
        details={"exitCode": result.returncode},
    )


def _keyword_checks(
    text: str,
    keywords: tuple[FitKeyword, ...],
) -> list[PdfCheck]:
    checks: list[PdfCheck] = []
    for keyword in keywords:
        present = _contains(text, keyword.term)
        if keyword.support == "gap":
            status: Literal["passed", "failed", "warning"] = "warning"
            message = f"Honest gap retained: {keyword.term}"
        elif present:
            status = "passed"
            message = f"Keyword present: {keyword.term}"
        else:
            status = "warning"
            message = f"Keyword represented by synonym or omitted: {keyword.term}"
        checks.append(
            PdfCheck(
                name=f"keyword:{keyword.term}",
                status=status,
                message=message,
                details={
                    "importance": keyword.importance,
                    "support": keyword.support,
                    "present": present,
                },
            )
        )
    return checks


def _check(
    name: str, passed: bool, message: str, details: dict[str, Any] | None = None
) -> PdfCheck:
    return PdfCheck(
        name=name,
        status="passed" if passed else "failed",
        message=message,
        details=details or {},
    )


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _contains(haystack: str, needle: str) -> bool:
    return _normalized(needle) in _normalized(haystack)


__all__ = [
    "PdfCheck",
    "PdfVerificationReport",
    "VerifiedPdf",
    "verify_compiled_document",
]
