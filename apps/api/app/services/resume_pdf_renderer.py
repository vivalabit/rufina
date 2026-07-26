from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.models.resume import FinalResume
from app.services.resume_pdf_validation import (
    ResumePdfValidationError,
    ResumePdfValidationPolicy,
    ResumePdfValidationReport,
    stamp_resume_pdf_metadata,
    validate_resume_pdf,
)
from app.services.resume_template_registry import ResumeTemplateId


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


class ResumePdfRenderError(RuntimeError):
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
    try:
        resume = FinalResume.model_validate(final_resume_json)
    except ValidationError as exc:
        raise ResumePdfRenderError("FinalResume JSON failed schema validation") from exc
    html, bundle = render_final_resume_html(
        final_resume_json,
        template_id=template_id,
    )
    render_result = chromium_pdf_from_html(html, bundle.manifest.page)
    try:
        pdf = stamp_resume_pdf_metadata(
            render_result.pdf,
            template_id=bundle.manifest.template_id,
            template_version=bundle.manifest.template_version,
            resume_schema_version=resume.schema_version,
        )
        validate_rendered_pdf(
            pdf,
            resume=resume,
            bundle=bundle,
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
    try:
        resume = FinalResume.model_validate(final_resume_json)
    except ValidationError as exc:
        raise ResumePdfRenderError("FinalResume JSON failed schema validation") from exc

    bundle = load_template_bundle(template_id)
    if resume.schema_version not in bundle.manifest.resume_schema_versions:
        raise ResumePdfRenderError(
            "FinalResume schema version is not supported by the PDF template"
        )

    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT)),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
        enable_async=False,
    )
    try:
        template = environment.from_string(bundle.html_template)
        html = template.render(
            resume=resume_view_model(resume),
            stylesheet=Markup(bundle.stylesheet),
            template_id=bundle.manifest.template_id,
            template_version=bundle.manifest.template_version,
        )
    except Exception as exc:
        raise ResumePdfRenderError("Resume HTML rendering failed") from exc

    if "<script" in html.lower():
        raise ResumePdfRenderError("Rendered resume HTML contains a script element")
    return html, bundle


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
        primary = {"summary", "experience", "projects"}
        sections = [
            section for section in resume.section_order if section in primary
        ] + [
            section for section in resume.section_order if section not in primary
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
    html_overflow_issues: tuple[str, ...] = (),
) -> ResumePdfValidationReport:
    return validate_resume_pdf(
        pdf,
        expected_text_fragments=expected_resume_text_fragments(
            resume,
            reading_order=bundle.manifest.validation.reading_order,
        ),
        template_id=bundle.manifest.template_id,
        template_version=bundle.manifest.template_version,
        resume_schema_version=resume.schema_version,
        policy=bundle.manifest.validation_policy(),
        html_overflow_issues=html_overflow_issues,
    )


__all__ = [
    "ChromiumPdfRenderResult",
    "DEFAULT_RESUME_PDF_TEMPLATE_ID",
    "ResumePdfPageManifest",
    "ResumePdfRenderError",
    "ResumePdfTemplateBundle",
    "ResumePdfTemplateManifest",
    "ResumePdfValidationManifest",
    "chromium_pdf_from_html",
    "expected_resume_text_fragments",
    "load_template_bundle",
    "normalize_display_mapping",
    "render_final_resume_html",
    "render_final_resume_json",
    "render_final_resume_pdf",
    "resume_section_titles",
    "resume_view_model",
    "validate_rendered_pdf",
]
