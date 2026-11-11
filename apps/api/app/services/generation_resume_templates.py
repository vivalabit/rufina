"""Server-owned CV templates supported by the LaTeX generation workflow."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

GenerationResumeTemplateId = Literal["moderncv_banking", "roman"]
DEFAULT_GENERATION_RESUME_TEMPLATE_ID: GenerationResumeTemplateId = "moderncv_banking"

RENAMED_GENERATION_RESUME_TEMPLATE_IDS = {"ishchenko_classic": "roman"}

# The previous generation UI saved HTML-template IDs even though every CV was
# rendered with ModernCV Banking. Keep those saved requests runnable while
# recording the template that the generator actually uses.
LEGACY_GENERATION_RESUME_TEMPLATE_IDS = frozenset(
    {
        "classic_single",
        "modern_single",
        "modern_two_column",
        "swiss_classic",
        "swiss_local_german",
    }
)
_TEMPLATE_VERSIONS: dict[GenerationResumeTemplateId, str] = {
    "moderncv_banking": "1.0.3",
    "roman": "1.0.2",
}
_RENDERER_SOURCE = Path(__file__).with_name("generation_latex.py")
_SKILL_GROUPING_SOURCE = Path(__file__).with_name("resume_skills.py")


@dataclass(frozen=True)
class GenerationResumeTemplate:
    id: GenerationResumeTemplateId
    version: str
    content_sha256: str
    renderer: Literal["lualatex"] = "lualatex"


def resolve_generation_resume_template(template_id: str | None = None) -> GenerationResumeTemplate:
    requested = (template_id or DEFAULT_GENERATION_RESUME_TEMPLATE_ID).strip()
    if requested in LEGACY_GENERATION_RESUME_TEMPLATE_IDS:
        requested = DEFAULT_GENERATION_RESUME_TEMPLATE_ID
    requested = RENAMED_GENERATION_RESUME_TEMPLATE_IDS.get(requested, requested)
    if requested not in _TEMPLATE_VERSIONS:
        raise ValueError(f"Unsupported generation resume template: {requested}")
    # Include the complete implementation, including shared escaping/contact
    # helpers, so persisted runs cannot claim to use an older renderer revision.
    version = _TEMPLATE_VERSIONS[requested]
    source = _RENDERER_SOURCE.read_bytes() + b"\0" + _SKILL_GROUPING_SOURCE.read_bytes()
    digest = hashlib.sha256(f"{requested}\0{version}\0".encode() + source).hexdigest()
    return GenerationResumeTemplate(
        id=requested,
        version=version,
        content_sha256=digest,
    )


__all__ = [
    "DEFAULT_GENERATION_RESUME_TEMPLATE_ID",
    "LEGACY_GENERATION_RESUME_TEMPLATE_IDS",
    "RENAMED_GENERATION_RESUME_TEMPLATE_IDS",
    "GenerationResumeTemplate",
    "GenerationResumeTemplateId",
    "resolve_generation_resume_template",
]
