"""PDF geometry checks against the visible page, independent of template margins.

Page margins and whitespace are design choices. Only text outside the actual
page boundary or an empty page is a hard geometry defect. Composition signals
remain advisory and the reviewer inspects the rendered pages for real orphans
and overlapping content. Do not use an assumed footer band as a content boundary.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any, Literal

import pdfplumber

_BOUNDARY_TOLERANCE_PT = 1.0


class GeometryUnavailable(RuntimeError):
    """The geometry extractor could not inspect the PDF; not a document defect."""


@dataclass(frozen=True)
class GeometryFinding:
    code: str
    severity: Literal["failed", "warning"]
    page: int
    message: str
    measurements: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PdfGeometry:
    findings: tuple[GeometryFinding, ...]
    pages: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _Line:
    left: float
    top: float
    bottom: float
    text: str


def inspect_pdf_geometry(path: Path) -> PdfGeometry:
    findings: list[GeometryFinding] = []
    metrics: list[dict[str, Any]] = []
    bodies: list[list[_Line]] = []
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise ValueError("No pages available to inspect")
            for number, page in enumerate(pdf.pages, 1):
                # Both boxes use pdfplumber's top-origin coordinates, including
                # rotation. A CropBox can hide text still present in extraction.
                media, crop = page.mediabox, page.cropbox
                bounds = (
                    max(media[0], crop[0]), max(media[1], crop[1]),
                    min(media[2], crop[2]), min(media[3], crop[3]),
                )
                left, top, right, bottom = bounds
                if right <= left or bottom <= top or not all(map(math.isfinite, bounds)):
                    raise ValueError("Invalid visible page bounds")
                chars = [char for char in page.chars if char["text"].strip()]
                if any(not math.isfinite(char[key]) for char in chars
                       for key in ("x0", "x1", "top", "bottom")):
                    raise ValueError("Invalid text geometry")
                clipped = [char for char in chars if (
                    char["x0"] < left - _BOUNDARY_TOLERANCE_PT
                    or char["x1"] > right + _BOUNDARY_TOLERANCE_PT
                    or char["top"] < top - _BOUNDARY_TOLERANCE_PT
                    or char["bottom"] > bottom + _BOUNDARY_TOLERANCE_PT
                )]
                if clipped:
                    findings.append(GeometryFinding(
                        "text_clipped", "failed", number,
                        f"Page {number}: text extends outside the visible page bounds.",
                        {"characterCount": len(clipped), "visibleBounds": list(bounds)},
                    ))
                lines = _text_lines(page.extract_words())
                body = [line for line in lines if not _is_page_number(
                    line, number, len(pdf.pages), top, bottom,
                )]
                bodies.append(body)
                page_metrics: dict[str, Any] = {
                    "page": number, "visibleBounds": list(bounds),
                    "clippedCharacters": len(clipped), "bodyLines": len(body),
                }
                metrics.append(page_metrics)
                if not body:
                    findings.append(GeometryFinding(
                        "empty_page", "failed", number,
                        f"Page {number}: no body text was found.",
                    ))
                    continue
                share = max(0.0, bottom - max(line.bottom for line in body)) / (bottom - top)
                gap = max((following.top - previous.bottom
                           for previous, following in pairwise(body)), default=0.0)
                page_metrics.update(bottomWhitespaceFraction=round(share, 4),
                                    largestGapPt=round(max(0.0, gap), 2))
                if gap > 100:
                    findings.append(GeometryFinding(
                        "internal_whitespace", "warning", number,
                        f"Page {number}: large space between text blocks; review the composition.",
                        {"gapPt": round(gap, 2)},
                    ))
                if len(pdf.pages) > 1 and share > (0.35 if number == len(pdf.pages) else 0.25):
                    findings.append(GeometryFinding(
                        "bottom_whitespace", "warning", number,
                        f"Page {number}: {share:.0%} bottom whitespace; this is a layout suggestion.",
                        {"fraction": round(share, 4)},
                    ))
    except Exception as exc:
        # pdfminer has several parser-specific error classes. An extraction error
        # must never turn into either a clean report or a repairable content defect.
        raise GeometryUnavailable("PDF geometry extraction failed") from exc

    document_left = min((line.left for body in bodies for line in body), default=0.0)
    for index, (body, following) in enumerate(pairwise(bodies), 1):
        if body and following:
            typical_height = median(line.bottom - line.top for line in body)
            ends_on_heading = body[-1].bottom - body[-1].top > typical_height * 1.25
            starts_indented = body[-1].left <= document_left + 8 < following[0].left
            if ends_on_heading or starts_indented:
                findings.append(GeometryFinding(
                    "possible_orphan_heading", "warning", index,
                    f"Page {index}: a possible heading ends the page; inspect the next page.",
                ))
    return PdfGeometry(tuple(findings), tuple(metrics))


def _text_lines(words: list[dict[str, Any]]) -> list[_Line]:
    groups: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        if groups and abs(word["top"] - groups[-1][0]["top"]) <= 2:
            groups[-1].append(word)
        else:
            groups.append([word])
    return [_Line(
        left=min(word["x0"] for word in group),
        top=min(word["top"] for word in group),
        bottom=max(word["bottom"] for word in group),
        text=" ".join(word["text"] for word in sorted(group, key=lambda item: item["x0"])),
    ) for group in groups]


def _is_page_number(line: _Line, number: int, total: int, top: float, bottom: float) -> bool:
    # Remove only a recognizable page-number line, never all text in a footer
    # region. Roman's valid closing/contact text can occupy this same region.
    if line.top < top + (bottom - top) * 0.85:
        return False
    return bool(re.fullmatch(
        rf"(?:page\s+)?{number}(?:\s*(?:/|of)\s*{total})?", line.text.strip(), re.IGNORECASE,
    ))
