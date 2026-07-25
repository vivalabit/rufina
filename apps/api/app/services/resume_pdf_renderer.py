from __future__ import annotations

import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader

from app.models.resume import FinalResume
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

    model_config = {"extra": "forbid", "populate_by_name": True}


@dataclass(frozen=True)
class ResumePdfTemplateBundle:
    manifest: ResumePdfTemplateManifest
    html_template: str
    stylesheet: str


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
    html, bundle = render_final_resume_html(
        final_resume_json,
        template_id=template_id,
    )
    pdf = chromium_pdf_from_html(html, bundle.manifest.page)
    validate_rendered_pdf(pdf)
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
    section_titles = (
        {
            "summary": "Profil",
            "experience": "Berufserfahrung",
            "skills": "Kompetenzen",
            "education": "Ausbildung",
            "projects": "Projekte",
            "certifications": "Zertifikate",
            "languages": "Sprachen",
            "additional": "Weitere Angaben",
        }
        if resume.language.lower().startswith(("de", "german", "deutsch"))
        else {
            "summary": "Profile",
            "experience": "Experience",
            "skills": "Skills",
            "education": "Education",
            "projects": "Projects",
            "certifications": "Certifications",
            "languages": "Languages",
            "additional": "Additional",
        }
    )
    return {
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
) -> bytes:
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
                return page.pdf(
                    format=page_manifest.format,
                    print_background=page_manifest.print_background,
                    prefer_css_page_size=True,
                    display_header_footer=False,
                )
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise ResumePdfRenderError("Chromium PDF rendering failed") from exc


def validate_rendered_pdf(pdf: bytes) -> None:
    if not pdf.startswith(b"%PDF-"):
        raise ResumePdfRenderError("Chromium returned an invalid PDF")
    try:
        reader = PdfReader(BytesIO(pdf))
    except Exception as exc:
        raise ResumePdfRenderError("Rendered resume PDF cannot be parsed") from exc
    if not 1 <= len(reader.pages) <= 10:
        raise ResumePdfRenderError("Rendered resume PDF has an invalid page count")


__all__ = [
    "DEFAULT_RESUME_PDF_TEMPLATE_ID",
    "ResumePdfPageManifest",
    "ResumePdfRenderError",
    "ResumePdfTemplateBundle",
    "ResumePdfTemplateManifest",
    "chromium_pdf_from_html",
    "load_template_bundle",
    "render_final_resume_html",
    "render_final_resume_json",
    "render_final_resume_pdf",
    "resume_view_model",
    "validate_rendered_pdf",
]
