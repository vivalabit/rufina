from __future__ import annotations

from functools import lru_cache

from app.services.document_thumbnail import (
    PdfThumbnailRenderError,
    render_pdf_first_page_thumbnail,
)
from app.services.document_validation import DocumentValidationError, render_docx_to_pdf


class CoverLetterTemplatePreviewError(RuntimeError):
    pass


@lru_cache(maxsize=32)
def render_cover_letter_template_thumbnail(content: bytes) -> bytes:
    try:
        pdf = render_docx_to_pdf(content)
        return render_pdf_first_page_thumbnail(pdf)
    except (DocumentValidationError, PdfThumbnailRenderError) as exc:
        raise CoverLetterTemplatePreviewError(str(exc)) from exc


__all__ = [
    "CoverLetterTemplatePreviewError",
    "render_cover_letter_template_thumbnail",
]
