from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from app.models.resume import FinalResume
from app.services.document_thumbnail import (
    PdfThumbnailRenderError,
    render_pdf_first_page_thumbnail,
)
from app.services.resume_pdf_renderer import (
    ResolvedResumeTemplate,
    ResumePdfRenderError,
    render_resolved_final_resume_pdf,
)

PREVIEW_THUMBNAIL_CACHE_SIZE = 64


DEMO_FINAL_RESUME = FinalResume.model_validate(
    {
        "schemaVersion": "1.0",
        "id": "preview:final-resume",
        "masterResumeId": "preview:master-resume",
        "targetJobId": "preview:target-role",
        "language": "English",
        "basics": {
            "fullName": "Jordan Lee",
            "headline": "Product-minded Software Engineer",
            "email": "jordan.lee@example.test",
            "phone": "+41 44 000 00 00",
            "location": "Zurich, Switzerland",
            "workAuthorization": "Swiss Permit S",
            "linkedin": "https://example.test/jordan-lee",
            "github": "https://github.com/example",
        },
        "summary": {
            "text": (
                "Software engineer focused on reliable products, clear "
                "communication, and measurable customer outcomes."
            ),
            "evidenceIds": ["generation:preview-summary"],
        },
        "experiences": [
            {
                "id": "preview:experience",
                "masterExperienceId": "preview:master-experience",
                "company": "Example Technology AG",
                "title": "Senior Software Engineer",
                "location": "Zurich",
                "period": "2022 - Present",
                "bullets": [
                    {
                        "id": "preview:experience-bullet",
                        "text": (
                            "Improved release reliability by introducing "
                            "automated quality gates and observability."
                        ),
                        "evidenceIds": ["generation:preview-experience"],
                    }
                ],
            }
        ],
        "skills": [
            {
                "id": "preview:skill-python",
                "name": "Python",
                "category": "Engineering",
                "evidenceIds": ["generation:preview-skills"],
            },
            {
                "id": "preview:skill-systems",
                "name": "Distributed systems",
                "category": "Engineering",
                "evidenceIds": ["generation:preview-skills"],
            },
            {
                "id": "preview:skill-leadership",
                "name": "Technical leadership",
                "category": "Collaboration",
                "evidenceIds": ["generation:preview-skills"],
            },
        ],
        "education": [
            {
                "id": "preview:education",
                "institution": "Example University",
                "credential": "MSc",
                "fieldOfStudy": "Computer Science",
                "location": "Zurich",
                "startDate": "2015",
                "endDate": "2017",
                "details": [],
            }
        ],
        "projects": [],
        "certifications": [],
        "languages": [
            {
                "id": "preview:language-english",
                "name": "English",
                "proficiency": "Fluent",
                "evidenceIds": ["generation:preview-language"],
            },
            {
                "id": "preview:language-german",
                "name": "German",
                "proficiency": "Professional",
                "evidenceIds": ["generation:preview-language"],
            },
        ],
        "additionalSections": [],
        "evidence": [
            {
                "id": "generation:preview-summary",
                "type": "generation",
                "text": "Server-owned preview summary.",
            },
            {
                "id": "generation:preview-experience",
                "type": "generation",
                "text": "Server-owned preview experience.",
            },
            {
                "id": "generation:preview-skills",
                "type": "generation",
                "text": "Server-owned preview skills.",
            },
            {
                "id": "generation:preview-language",
                "type": "generation",
                "text": "Server-owned preview languages.",
            },
        ],
        "sectionOrder": [
            "summary",
            "experience",
            "skills",
            "education",
            "languages",
        ],
    }
)


@dataclass(frozen=True)
class PreviewRateLimitExceeded(Exception):
    retry_after_seconds: int


class ResumeTemplatePreviewRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def consume(
        self,
        owner_id: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> None:
        timestamp = monotonic() if now is None else now
        window_start = timestamp - window_seconds
        with self._lock:
            attempts = self._attempts.setdefault(owner_id, deque())
            while attempts and attempts[0] <= window_start:
                attempts.popleft()
            if len(attempts) >= limit:
                retry_after = max(
                    1,
                    int(attempts[0] + window_seconds - timestamp) + 1,
                )
                raise PreviewRateLimitExceeded(retry_after)
            attempts.append(timestamp)

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()


preview_rate_limiter = ResumeTemplatePreviewRateLimiter()
thumbnail_rate_limiter = ResumeTemplatePreviewRateLimiter()
_preview_thumbnail_cache: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()
_preview_thumbnail_cache_lock = Lock()


def render_resume_template_preview(
    template: ResolvedResumeTemplate,
) -> bytes:
    return render_resolved_final_resume_pdf(
        DEMO_FINAL_RESUME.model_dump(
            by_alias=True,
            exclude_none=True,
        ),
        template=template,
    )


def render_resume_template_thumbnail(
    template: ResolvedResumeTemplate,
) -> bytes:
    cache_key = (template.id, template.version, template.design_sha256)
    with _preview_thumbnail_cache_lock:
        cached = _preview_thumbnail_cache.get(cache_key)
        if cached is not None:
            _preview_thumbnail_cache.move_to_end(cache_key)
            return cached

    pdf = render_resume_template_preview(template)
    thumbnail = rasterize_resume_template_first_page(pdf)

    with _preview_thumbnail_cache_lock:
        _preview_thumbnail_cache[cache_key] = thumbnail
        _preview_thumbnail_cache.move_to_end(cache_key)
        while len(_preview_thumbnail_cache) > PREVIEW_THUMBNAIL_CACHE_SIZE:
            _preview_thumbnail_cache.popitem(last=False)
    return thumbnail


def rasterize_resume_template_first_page(pdf: bytes) -> bytes:
    try:
        return render_pdf_first_page_thumbnail(pdf)
    except PdfThumbnailRenderError as exc:
        raise ResumePdfRenderError(
            f"Resume template thumbnail rendering failed: {exc}"
        ) from exc


def clear_resume_template_thumbnail_cache() -> None:
    with _preview_thumbnail_cache_lock:
        _preview_thumbnail_cache.clear()


__all__ = [
    "DEMO_FINAL_RESUME",
    "PreviewRateLimitExceeded",
    "ResumeTemplatePreviewRateLimiter",
    "clear_resume_template_thumbnail_cache",
    "preview_rate_limiter",
    "render_resume_template_preview",
    "render_resume_template_thumbnail",
    "thumbnail_rate_limiter",
]
