from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identity import get_bound_owner_id
from app.models.resume import FinalResume
from app.models.resume_templates import (
    ResumeTemplateDefinitionRecord,
    ResumeTemplateDesignTokens,
)
from app.services.resume_pdf_validation import (
    ResumePdfValidationError,
    ResumePdfValidationPolicy,
    ResumePdfValidationReport,
    stamp_resume_pdf_metadata,
    validate_resume_pdf,
)
from app.services.resume_template_registry import (
    ResumeTemplateId,
    is_bundled_resume_template_id,
)


DEFAULT_RESUME_PDF_TEMPLATE_ID: ResumeTemplateId = "classic_single"
TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates" / "resume_pdf"
MAX_MANIFEST_BYTES = 16_000
MAX_TEMPLATE_BYTES = 256_000
MAX_STYLESHEET_BYTES = 256_000
PDF_RENDER_TIMEOUT_MS = 30_000
_SAFE_ASSET_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_UNSAFE_CSS = re.compile(
    r"@import|expression\s*\(|javascript\s*:|"
    r"url\s*\(\s*['\"]?\s*(?:https?:|//|data:)",
    re.IGNORECASE,
)
_UNSAFE_JINJA = re.compile(
    r"{%\s*(?:extends|include|import|from)\b",
    re.IGNORECASE,
)
_STYLESHEET_SENTINEL = "RUFINA_SERVER_OWNED_STYLESHEET"


class ResumePdfRenderError(RuntimeError):
    pass


class ResumeTemplateNotFoundError(ResumePdfRenderError):
    pass


class ResumePdfPageManifest(BaseModel):
    format: Literal["A4", "Letter"] = "A4"
    print_background: Literal[True] = Field(default=True, alias="printBackground")

    model_config = {"extra": "forbid", "populate_by_name": True}


class ResumePdfValidationManifest(BaseModel):
    min_pages: int = Field(ge=1, le=10, alias="minPages")
    max_pages: int = Field(ge=1, le=10, alias="maxPages")
    png_dpi: int = Field(ge=72, le=300, alias="pngDpi")
    reading_order: Literal[
        "resumeSectionOrder",
        "primaryThenSidebar",
    ] = Field(alias="readingOrder")

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def validate_page_range(self) -> ResumePdfValidationManifest:
        if self.min_pages > self.max_pages:
            raise ValueError("minPages cannot exceed maxPages")
        return self


class ResumePdfTemplateManifest(BaseModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    template_id: ResumeTemplateId = Field(alias="templateId")
    template_version: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$",
        alias="templateVersion",
    )
    renderer: Literal["chromium"]
    resume_schema_versions: list[Literal["1.0"]] = Field(
        min_length=1,
        max_length=4,
        alias="resumeSchemaVersions",
    )
    html_template: str = Field(
        min_length=1,
        max_length=80,
        alias="htmlTemplate",
    )
    stylesheets: list[str] = Field(min_length=1, max_length=4)
    page: ResumePdfPageManifest
    validation: ResumePdfValidationManifest

    model_config = {"extra": "forbid", "populate_by_name": True}

    def validation_policy(self) -> ResumePdfValidationPolicy:
        return ResumePdfValidationPolicy(
            min_pages=self.validation.min_pages,
            max_pages=self.validation.max_pages,
            png_dpi=self.validation.png_dpi,
            reading_order=self.validation.reading_order,
        )


@dataclass(frozen=True)
class ResumePdfTemplateBundle:
    manifest: ResumePdfTemplateManifest
    html_template: str
    stylesheet: str


@dataclass(frozen=True)
class ResolvedResumeTemplate:
    id: str
    version: str
    base_template_id: ResumeTemplateId
    design: ResumeTemplateDesignTokens
    html_template: str
    stylesheet: str

    @property
    def design_sha256(self) -> str:
        return resume_design_sha256(self.design)


@dataclass(frozen=True)
class ChromiumPdfRenderResult:
    pdf: bytes
    overflow_issues: tuple[str, ...]


def render_final_resume_json(final_resume_json: dict[str, object]) -> bytes:
    """Render validated FinalResume JSON with the default server-owned template."""
    return render_final_resume_pdf(
        final_resume_json,
        template_id=DEFAULT_RESUME_PDF_TEMPLATE_ID,
    )


def render_final_resume_pdf(
    final_resume_json: dict[str, object],
    *,
    template_id: ResumeTemplateId = DEFAULT_RESUME_PDF_TEMPLATE_ID,
) -> bytes:
    resolved = resolve_bundled_resume_template(template_id)
    return render_resolved_final_resume_pdf(
        final_resume_json,
        template=resolved,
    )


def render_resolved_final_resume_pdf(
    final_resume_json: dict[str, object],
    *,
    template: ResolvedResumeTemplate,
) -> bytes:
    try:
        resume = FinalResume.model_validate(final_resume_json)
    except ValidationError as exc:
        raise ResumePdfRenderError("FinalResume JSON failed schema validation") from exc
    html, bundle = render_resolved_final_resume_html(
        final_resume_json,
        template=template,
    )
    render_result = chromium_pdf_from_html(html, bundle.manifest.page)
    try:
        pdf = stamp_resume_pdf_metadata(
            render_result.pdf,
            template_id=template.id,
            template_version=template.version,
            resume_schema_version=resume.schema_version,
        )
        validate_rendered_pdf(
            pdf,
            resume=resume,
            bundle=bundle,
            resolved_template=template,
            html_overflow_issues=render_result.overflow_issues,
        )
    except ResumePdfValidationError as exc:
        raise ResumePdfRenderError(str(exc)) from exc
    return pdf


def render_final_resume_html(
    final_resume_json: dict[str, object],
    *,
    template_id: ResumeTemplateId = DEFAULT_RESUME_PDF_TEMPLATE_ID,
) -> tuple[str, ResumePdfTemplateBundle]:
    resolved = resolve_bundled_resume_template(template_id)
    return render_resolved_final_resume_html(
        final_resume_json,
        template=resolved,
    )


def render_resolved_final_resume_html(
    final_resume_json: dict[str, object],
    *,
    template: ResolvedResumeTemplate,
) -> tuple[str, ResumePdfTemplateBundle]:
    try:
        resume = FinalResume.model_validate(final_resume_json)
    except ValidationError as exc:
        raise ResumePdfRenderError("FinalResume JSON failed schema validation") from exc

    bundle = load_template_bundle(template.base_template_id)
    if resume.schema_version not in bundle.manifest.resume_schema_versions:
        raise ResumePdfRenderError(
            "FinalResume schema version is not supported by the PDF template"
        )
    if (
        template.html_template != bundle.html_template
        or template.stylesheet
        != resolved_stylesheet(bundle.stylesheet, template.design)
    ):
        raise ResumePdfRenderError(
            "Resolved resume template does not use its server-owned bundle"
        )

    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT)),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
        enable_async=False,
    )
    try:
        jinja_template = environment.from_string(template.html_template)
        html = jinja_template.render(
            resume=resume_view_model(resume),
            stylesheet=_STYLESHEET_SENTINEL,
            template_id=template.base_template_id,
            template_version=template.version,
            sidebar_sections=template.design.sidebar_sections,
        )
    except Exception as exc:
        raise ResumePdfRenderError("Resume HTML rendering failed") from exc

    if html.count(_STYLESHEET_SENTINEL) != 1:
        raise ResumePdfRenderError(
            "Resume HTML template has an invalid stylesheet slot"
        )
    html = html.replace(_STYLESHEET_SENTINEL, template.stylesheet, 1)
    if "<script" in html.lower():
        raise ResumePdfRenderError("Rendered resume HTML contains a script element")
    return html, bundle


def resolve_resume_template(
    db: Session,
    template_id: str,
) -> ResolvedResumeTemplate:
    if template_id in {
        "classic_single",
        "modern_single",
        "modern_two_column",
    }:
        return resolve_bundled_resume_template(
            cast(ResumeTemplateId, template_id)
        )
    record = db.scalar(
        select(ResumeTemplateDefinitionRecord).where(
            ResumeTemplateDefinitionRecord.id == template_id,
            ResumeTemplateDefinitionRecord.owner_id == get_bound_owner_id(),
        )
    )
    if record is None:
        raise ResumeTemplateNotFoundError("Resume template not found")
    try:
        design = ResumeTemplateDesignTokens.model_validate(record.design_json)
    except ValidationError as exc:
        raise ResumePdfRenderError(
            "Stored resume template design is invalid"
        ) from exc
    if not is_bundled_resume_template_id(record.base_template_id):
        raise ResumePdfRenderError(
            "Stored resume template base is not a bundled template"
        )
    bundle = load_template_bundle(record.base_template_id)
    return ResolvedResumeTemplate(
        id=record.id,
        version=str(record.version),
        base_template_id=bundle.manifest.template_id,
        design=design,
        html_template=bundle.html_template,
        stylesheet=resolved_stylesheet(bundle.stylesheet, design),
    )


def resolve_bundled_resume_template(
    template_id: ResumeTemplateId,
) -> ResolvedResumeTemplate:
    bundle = load_template_bundle(template_id)
    design = default_bundled_design_tokens(template_id)
    return ResolvedResumeTemplate(
        id=template_id,
        version=bundle.manifest.template_version,
        base_template_id=template_id,
        design=design,
        html_template=bundle.html_template,
        stylesheet=resolved_stylesheet(bundle.stylesheet, design),
    )


def resolved_stylesheet(
    server_owned_stylesheet: str,
    design: ResumeTemplateDesignTokens,
) -> str:
    return "\n".join(
        (
            server_owned_stylesheet,
            resume_design_css(design),
            server_owned_design_rules(design),
        )
    )


def resume_design_css(design: ResumeTemplateDesignTokens) -> str:
    margins = design.page_margins
    density_scale = {
        "compact": 0.86,
        "standard": 1.0,
        "comfortable": 1.15,
    }[design.density]
    sidebar_sections = ",".join(design.sidebar_sections)
    return "\n".join(
        (
            ":root {",
            f"  --resume-accent: {design.accent_color};",
            f'  --resume-font-family: "{design.font_family}", Arial, sans-serif;',
            f"  --resume-font-scale: {css_number(design.font_scale)};",
            f"  --resume-density-scale: {css_number(density_scale)};",
            f"  --resume-page-margin-top: {css_number(margins.top)}mm;",
            f"  --resume-page-margin-right: {css_number(margins.right)}mm;",
            f"  --resume-page-margin-bottom: {css_number(margins.bottom)}mm;",
            f"  --resume-page-margin-left: {css_number(margins.left)}mm;",
            f"  --resume-heading-style: {design.heading_style};",
            f"  --resume-skills-style: {design.skills_style};",
            f"  --resume-sidebar-width: {css_number(design.sidebar_width)}%;",
            f'  --resume-sidebar-sections: "{sidebar_sections}";',
            "}",
            "@page {",
            f"  margin: {css_number(margins.top)}mm"
            f" {css_number(margins.right)}mm"
            f" {css_number(margins.bottom)}mm"
            f" {css_number(margins.left)}mm;",
            "  margin: var(--resume-page-margin-top)"
            " var(--resume-page-margin-right)"
            " var(--resume-page-margin-bottom)"
            " var(--resume-page-margin-left);",
            "}",
        )
    )


def server_owned_design_rules(design: ResumeTemplateDesignTokens) -> str:
    heading_rules = {
        "plain": (
            "border-bottom: 0;",
            "padding-bottom: 0;",
            "color: var(--resume-accent);",
        ),
        "underlined": (
            "border-bottom: 1px solid var(--resume-accent);",
            "padding-bottom: 3px;",
            "color: var(--resume-accent);",
        ),
        "accent-rule": (
            "border-bottom: 0;",
            "padding-bottom: 0;",
            "color: var(--resume-accent);",
        ),
    }.get(
        design.heading_style,
        (
            "border-bottom: 0;",
            "padding-bottom: 0;",
            "color: var(--resume-accent);",
        ),
    )
    skills_rules = {
        "inline": (
            "display: flex;",
            "gap: 4px 16px;",
            "background: transparent;",
            "border-radius: 0;",
            "padding: 0;",
        ),
        "list": (
            "display: block;",
            "gap: 0;",
            "background: transparent;",
            "border-radius: 0;",
            "padding: 0;",
        ),
        "pills": (
            "display: flex;",
            "gap: 5px 8px;",
            "background: color-mix(in srgb, var(--resume-accent) 10%, white);",
            "border-radius: 999px;",
            "padding: 3px 8px;",
        ),
    }.get(
        design.skills_style,
        (
            "display: flex;",
            "gap: 4px 16px;",
            "background: transparent;",
            "border-radius: 0;",
            "padding: 0;",
        ),
    )
    accent_rule_display = (
        "block" if design.heading_style == "accent-rule" else "none"
    )
    return "\n".join(
        (
            ".resume-shell .resume-section h2 {",
            *(f"  {rule}" for rule in heading_rules),
            "}",
            ".resume-shell .resume-section h2::after {",
            f"  display: {accent_rule_display};",
            "  background: var(--resume-accent);",
            "}",
            ".resume-shell .skill-list {",
            f"  {skills_rules[0]}",
            f"  {skills_rules[1]}",
            "}",
            ".resume-shell .skill-list p {",
            *(f"  {rule}" for rule in skills_rules[2:]),
            "}",
        )
    )


def resume_design_sha256(design: ResumeTemplateDesignTokens) -> str:
    canonical = json.dumps(
        design.model_dump(mode="json", by_alias=True),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def css_number(value: float) -> str:
    return format(value, ".6g")


def default_bundled_design_tokens(
    template_id: ResumeTemplateId,
) -> ResumeTemplateDesignTokens:
    defaults: dict[ResumeTemplateId, dict[str, object]] = {
        "classic_single": {
            "accentColor": "#2B2B2B",
            "fontFamily": "Georgia",
            "fontScale": 1.0,
            "density": "standard",
            "pageMargins": {"top": 15, "right": 15, "bottom": 15, "left": 15},
            "headingStyle": "underlined",
            "skillsStyle": "inline",
            "sidebarWidth": 0,
            "sidebarSections": [],
        },
        "modern_single": {
            "accentColor": "#176B87",
            "fontFamily": "Inter",
            "fontScale": 1.0,
            "density": "standard",
            "pageMargins": {"top": 14, "right": 14, "bottom": 14, "left": 14},
            "headingStyle": "accent-rule",
            "skillsStyle": "pills",
            "sidebarWidth": 0,
            "sidebarSections": [],
        },
        "modern_two_column": {
            "accentColor": "#243B53",
            "fontFamily": "Inter",
            "fontScale": 1.0,
            "density": "compact",
            "pageMargins": {"top": 12, "right": 12, "bottom": 12, "left": 12},
            "headingStyle": "accent-rule",
            "skillsStyle": "pills",
            "sidebarWidth": 32,
            "sidebarSections": [
                "skills",
                "education",
                "certifications",
                "languages",
                "additional",
            ],
        },
    }
    return ResumeTemplateDesignTokens.model_validate(defaults[template_id])


def load_template_bundle(template_id: ResumeTemplateId) -> ResumePdfTemplateBundle:
    bundle_directory = TEMPLATE_ROOT / template_id
    manifest_path = bundle_directory / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ResumePdfRenderError("Resume PDF template manifest is unavailable") from exc
    if not manifest_bytes or len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ResumePdfRenderError("Resume PDF template manifest has an invalid size")

    try:
        manifest = ResumePdfTemplateManifest.model_validate(
            json.loads(manifest_bytes)
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ResumePdfRenderError("Resume PDF template manifest is invalid") from exc
    if manifest.template_id != template_id:
        raise ResumePdfRenderError("Resume PDF template manifest ID does not match")

    html_path = resolve_bundle_asset(
        bundle_directory,
        manifest.html_template,
        suffix=".j2",
    )
    stylesheet_paths = [
        resolve_bundle_asset(bundle_directory, name, suffix=".css")
        for name in manifest.stylesheets
    ]
    html_template = read_text_asset(
        html_path,
        max_bytes=MAX_TEMPLATE_BYTES,
        label="HTML template",
    )
    stylesheets = [
        read_text_asset(
            path,
            max_bytes=MAX_STYLESHEET_BYTES,
            label="stylesheet",
        )
        for path in stylesheet_paths
    ]
    if _UNSAFE_JINJA.search(html_template):
        raise ResumePdfRenderError("Resume HTML template cannot load external templates")
    stylesheet = "\n".join(stylesheets)
    if _UNSAFE_CSS.search(stylesheet):
        raise ResumePdfRenderError("Resume stylesheet contains an external resource")
    return ResumePdfTemplateBundle(
        manifest=manifest,
        html_template=html_template,
        stylesheet=stylesheet,
    )


def resolve_bundle_asset(
    bundle_directory: Path,
    asset_name: str,
    *,
    suffix: str,
) -> Path:
    if (
        not _SAFE_ASSET_NAME.fullmatch(asset_name)
        or Path(asset_name).name != asset_name
        or not asset_name.endswith(suffix)
    ):
        raise ResumePdfRenderError("Resume PDF template manifest has an unsafe asset path")
    path = (bundle_directory / asset_name).resolve()
    if path.parent != bundle_directory.resolve():
        raise ResumePdfRenderError("Resume PDF template asset escapes its bundle")
    return path


def read_text_asset(path: Path, *, max_bytes: int, label: str) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ResumePdfRenderError(f"Resume PDF template {label} is unavailable") from exc
    if not content or len(content) > max_bytes:
        raise ResumePdfRenderError(f"Resume PDF template {label} has an invalid size")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResumePdfRenderError(
            f"Resume PDF template {label} must be UTF-8"
        ) from exc


def resume_view_model(resume: FinalResume) -> dict[str, object]:
    basics = resume.basics
    contacts = [
        contact_view("email", basics.email, f"mailto:{basics.email}" if basics.email else ""),
        contact_view("phone", basics.phone, f"tel:{basics.phone}" if basics.phone else ""),
        contact_view("location", basics.location),
        contact_view("linkedin", basics.linkedin, safe_web_url(basics.linkedin)),
        contact_view("github", basics.github, safe_web_url(basics.github)),
        contact_view("portfolio", basics.portfolio, safe_web_url(basics.portfolio)),
    ]
    section_titles = resume_section_titles(resume)
    view_model = {
        "id": resume.id,
        "language": resume.language,
        "basics": {
            "full_name": basics.full_name,
            "headline": basics.headline,
            "contacts": [contact for contact in contacts if contact["value"]],
        },
        "summary": resume.summary.model_dump() if resume.summary else None,
        "experiences": [
            experience.model_dump(exclude={"master_experience_id"})
            for experience in resume.experiences
        ],
        "skills": [skill.model_dump() for skill in resume.skills],
        "skill_groups": skill_group_view(resume),
        "education": [item.model_dump() for item in resume.education],
        "projects": [item.model_dump() for item in resume.projects],
        "certifications": [
            item.model_dump() for item in resume.certifications
        ],
        "languages": [item.model_dump() for item in resume.languages],
        "additional_sections": [
            item.model_dump() for item in resume.additional_sections
        ],
        "section_order": list(resume.section_order),
        "section_titles": section_titles,
    }
    return normalize_display_mapping(view_model)


def skill_group_view(resume: FinalResume) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    indexes_by_category: dict[str, int] = {}
    for skill in resume.skills:
        category_key = skill.category.casefold()
        group_index = indexes_by_category.get(category_key)
        if group_index is None:
            group_index = len(groups)
            indexes_by_category[category_key] = group_index
            groups.append({"category": skill.category, "names": []})
        names = groups[group_index]["names"]
        if isinstance(names, list):
            names.append(skill.name)
    return groups


def resume_section_titles(resume: FinalResume) -> dict[str, str]:
    if resume.language.lower().startswith(("de", "german", "deutsch")):
        return {
            "summary": "Profil",
            "experience": "Berufserfahrung",
            "skills": "Kompetenzen",
            "education": "Ausbildung",
            "projects": "Projekte",
            "certifications": "Zertifikate",
            "languages": "Sprachen",
            "additional": "Weitere Angaben",
            "expires": "Gültig bis",
        }
    return {
        "summary": "Profile",
        "experience": "Experience",
        "skills": "Skills",
        "education": "Education",
        "projects": "Projects",
        "certifications": "Certifications",
        "languages": "Languages",
        "additional": "Additional",
        "expires": "Expires",
    }


def normalize_display_mapping(value: dict[str, object]) -> dict[str, object]:
    return {
        key: normalize_display_value(item)
        for key, item in value.items()
    }


def normalize_display_value(value: object) -> object:
    if isinstance(value, str):
        return re.sub(r"[\u2010-\u2015\u2212]", "-", value)
    if isinstance(value, list):
        return [normalize_display_value(item) for item in value]
    if isinstance(value, dict):
        return normalize_display_mapping(value)
    return value


def expected_resume_text_fragments(
    resume: FinalResume,
    *,
    reading_order: Literal["resumeSectionOrder", "primaryThenSidebar"],
    sidebar_sections: list[str] | None = None,
) -> list[str]:
    fragments = [
        resume.basics.full_name,
        resume.basics.headline,
        resume.basics.email,
        resume.basics.phone,
        resume.basics.location,
        resume.basics.linkedin,
        resume.basics.github,
        resume.basics.portfolio,
    ]
    sections = list(resume.section_order)
    if reading_order == "primaryThenSidebar":
        sidebar = set(
            sidebar_sections
            if sidebar_sections is not None
            else [
                "skills",
                "education",
                "certifications",
                "languages",
                "additional",
            ]
        )
        sections = [
            section for section in resume.section_order if section not in sidebar
        ] + [
            section for section in resume.section_order if section in sidebar
        ]
    titles = resume_section_titles(resume)
    for section in sections:
        fragments.append(titles[section])
        if section == "summary" and resume.summary:
            fragments.append(resume.summary.text)
        elif section == "experience":
            for experience in resume.experiences:
                fragments.extend(
                    [
                        experience.title,
                        experience.period,
                        experience.company,
                        experience.location,
                        *(bullet.text for bullet in experience.bullets),
                    ]
                )
        elif section == "skills":
            for group in skill_group_view(resume):
                category = group["category"]
                names = group["names"]
                if isinstance(category, str) and category:
                    fragments.append(category)
                if isinstance(names, list):
                    fragments.extend(
                        name for name in names if isinstance(name, str)
                    )
        elif section == "education":
            for education in resume.education:
                fragments.extend(
                    [
                        education.credential,
                        education.field_of_study,
                        education.start_date,
                        education.end_date,
                        education.institution,
                        education.location,
                        *(detail.text for detail in education.details),
                    ]
                )
        elif section == "projects":
            for project in resume.projects:
                fragments.extend(
                    [
                        project.name,
                        project.role,
                        project.url,
                        *(bullet.text for bullet in project.bullets),
                    ]
                )
        elif section == "certifications":
            for certification in resume.certifications:
                fragments.extend(
                    [
                        certification.name,
                        certification.issuer,
                        certification.issued_on,
                    ]
                )
                if certification.expires_on:
                    fragments.extend(
                        [titles["expires"], certification.expires_on]
                    )
        elif section == "languages":
            for language in resume.languages:
                fragments.extend([language.name, language.proficiency])
        elif section == "additional":
            for additional in resume.additional_sections:
                fragments.extend(
                    [
                        additional.title,
                        *(item.text for item in additional.items),
                    ]
                )
    return [fragment for fragment in fragments if fragment]


def contact_view(kind: str, value: str, href: str = "") -> dict[str, str]:
    return {"kind": kind, "value": value.strip(), "href": href}


def safe_web_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def chromium_pdf_from_html(
    html: str,
    page_manifest: ResumePdfPageManifest,
) -> ChromiumPdfRenderResult:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ResumePdfRenderError("Playwright is required for PDF rendering") from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(java_script_enabled=False)
                page = context.new_page()
                page.set_default_timeout(PDF_RENDER_TIMEOUT_MS)
                page.route("**/*", lambda route: route.abort())
                page.set_content(
                    html,
                    wait_until="load",
                    timeout=PDF_RENDER_TIMEOUT_MS,
                )
                page.emulate_media(media="print")
                overflow_issues = tuple(
                    page.evaluate(
                        """
                        () => {
                          const issues = [];
                          const root = document.documentElement;
                          if (root.scrollWidth > root.clientWidth + 1) {
                            issues.push("document has horizontal overflow");
                          }
                          const shell = document.querySelector(".resume-shell");
                          if (!shell) {
                            issues.push("resume shell is missing");
                            return issues;
                          }
                          const shellRect = shell.getBoundingClientRect();
                          for (const element of shell.querySelectorAll("*")) {
                            const rect = element.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) continue;
                            if (
                              element.scrollWidth > element.clientWidth + 1 ||
                              element.scrollHeight > element.clientHeight + 1
                            ) {
                              issues.push(
                                `${element.tagName.toLowerCase()} content exceeds its box`
                              );
                            }
                            if (
                              rect.left < shellRect.left - 1 ||
                              rect.right > shellRect.right + 1
                            ) {
                              issues.push(
                                `${element.tagName.toLowerCase()} exceeds resume width`
                              );
                            }
                            if (issues.length >= 20) break;
                          }
                          return issues;
                        }
                        """
                    )
                )
                pdf = page.pdf(
                    format=page_manifest.format,
                    print_background=page_manifest.print_background,
                    prefer_css_page_size=True,
                    display_header_footer=False,
                )
                return ChromiumPdfRenderResult(
                    pdf=pdf,
                    overflow_issues=overflow_issues,
                )
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise ResumePdfRenderError("Chromium PDF rendering failed") from exc


def validate_rendered_pdf(
    pdf: bytes,
    *,
    resume: FinalResume,
    bundle: ResumePdfTemplateBundle,
    resolved_template: ResolvedResumeTemplate | None = None,
    html_overflow_issues: tuple[str, ...] = (),
) -> ResumePdfValidationReport:
    template_id = (
        resolved_template.id
        if resolved_template is not None
        else bundle.manifest.template_id
    )
    template_version = (
        resolved_template.version
        if resolved_template is not None
        else bundle.manifest.template_version
    )
    return validate_resume_pdf(
        pdf,
        expected_text_fragments=expected_resume_text_fragments(
            resume,
            reading_order=bundle.manifest.validation.reading_order,
            sidebar_sections=(
                resolved_template.design.sidebar_sections
                if resolved_template is not None
                else None
            ),
        ),
        template_id=template_id,
        template_version=template_version,
        resume_schema_version=resume.schema_version,
        policy=bundle.manifest.validation_policy(),
        html_overflow_issues=html_overflow_issues,
    )


__all__ = [
    "ChromiumPdfRenderResult",
    "DEFAULT_RESUME_PDF_TEMPLATE_ID",
    "ResolvedResumeTemplate",
    "ResumePdfPageManifest",
    "ResumePdfRenderError",
    "ResumeTemplateNotFoundError",
    "ResumePdfTemplateBundle",
    "ResumePdfTemplateManifest",
    "ResumePdfValidationManifest",
    "chromium_pdf_from_html",
    "expected_resume_text_fragments",
    "default_bundled_design_tokens",
    "load_template_bundle",
    "normalize_display_mapping",
    "render_final_resume_html",
    "render_final_resume_json",
    "render_final_resume_pdf",
    "render_resolved_final_resume_html",
    "render_resolved_final_resume_pdf",
    "resolve_bundled_resume_template",
    "resolve_resume_template",
    "resume_design_css",
    "resume_design_sha256",
    "resume_section_titles",
    "resume_view_model",
    "validate_rendered_pdf",
]
