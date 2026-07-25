from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ResumeTemplateId = Literal[
    "classic_single",
    "modern_single",
    "modern_two_column",
]


@dataclass(frozen=True)
class BundledResumeTemplate:
    """Metadata for one server-owned HTML/CSS PDF template."""

    id: ResumeTemplateId
    name: str
    description: str
    layout: Literal["single_column", "two_column"]
    columns: Literal[1, 2]


BUNDLED_RESUME_TEMPLATES: tuple[BundledResumeTemplate, ...] = (
    BundledResumeTemplate(
        id="classic_single",
        name="Classic",
        description="Traditional single-column layout optimized for ATS parsing.",
        layout="single_column",
        columns=1,
    ),
    BundledResumeTemplate(
        id="modern_single",
        name="Modern",
        description=(
            "Contemporary single-column layout with restrained visual hierarchy."
        ),
        layout="single_column",
        columns=1,
    ),
    BundledResumeTemplate(
        id="modern_two_column",
        name="Modern two-column",
        description=(
            "Two-column layout with a compact skills rail and primary career timeline."
        ),
        layout="two_column",
        columns=2,
    ),
)
_TEMPLATES_BY_ID = {
    template.id: template for template in BUNDLED_RESUME_TEMPLATES
}


def list_bundled_resume_templates() -> tuple[BundledResumeTemplate, ...]:
    return BUNDLED_RESUME_TEMPLATES


def is_bundled_resume_template_id(template_id: str) -> bool:
    return template_id in _TEMPLATES_BY_ID


def get_bundled_resume_template(template_id: str) -> BundledResumeTemplate:
    try:
        return _TEMPLATES_BY_ID[template_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown bundled resume template: {template_id}"
        ) from exc


__all__ = [
    "BUNDLED_RESUME_TEMPLATES",
    "BundledResumeTemplate",
    "ResumeTemplateId",
    "get_bundled_resume_template",
    "is_bundled_resume_template_id",
    "list_bundled_resume_templates",
]
