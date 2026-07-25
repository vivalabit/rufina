from __future__ import annotations

import base64
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict

from app.core.settings import Settings
from app.models.profile import ImportedEducationEntry, ImportedExperienceEntry
from app.services.ai_backend import (
    AIBackend,
    AIBackendError,
    AIRequest,
    OpenClawCodexBackend,
    create_configured_ai_backend,
    generate_with_retries,
)
from app.services.resume_headings import (
    ALL_RESUME_HEADINGS,
    CERTIFICATION_HEADINGS as RESUME_CERTIFICATION_HEADINGS,
    EDUCATION_HEADINGS as RESUME_EDUCATION_HEADINGS,
    EXPERIENCE_HEADINGS as RESUME_EXPERIENCE_HEADINGS,
    SKILL_HEADINGS as RESUME_SKILL_HEADINGS,
    normalize_resume_heading,
)
from app.services.resume_source_extraction import (
    ResumeSourceExtractionError,
    extract_resume_source,
)

EXPERIENCE_HEADINGS = RESUME_EXPERIENCE_HEADINGS
EDUCATION_HEADINGS = frozenset().union(
    RESUME_EDUCATION_HEADINGS,
    RESUME_CERTIFICATION_HEADINGS,
)
SKILLS_HEADINGS = RESUME_SKILL_HEADINGS
SECTION_STOP_HEADINGS = ALL_RESUME_HEADINGS - EXPERIENCE_HEADINGS
SKILLS_STOP_HEADINGS = ALL_RESUME_HEADINGS - SKILLS_HEADINGS
EDUCATION_STOP_HEADINGS = ALL_RESUME_HEADINGS - EDUCATION_HEADINGS


class ResumeExperienceStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experience: list[ImportedExperienceEntry]


class ResumeEducationStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    education: list[ImportedEducationEntry]


class ResumeSkillsStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[str]

TITLE_HINTS = {
    "administrator",
    "analyst",
    "architect",
    "consultant",
    "designer",
    "developer",
    "engineer",
    "founder",
    "intern",
    "lead",
    "manager",
    "owner",
    "product",
    "programmer",
    "specialist",
    "technician",
}

CREDENTIAL_HINTS = {
    "bachelor",
    "bsc",
    "bs",
    "master",
    "msc",
    "ms",
    "phd",
    "doctor",
    "degree",
    "diploma",
    "certificate",
    "certification",
    "course",
    "bootcamp",
    "training",
}

MONTHS = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}

DATE_TOKEN = (
    r"(?:"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{4}"
    r"|\d{1,2}/\d{4}"
    r"|\d{4}"
    r"|Present|Current|Now"
    r")"
)
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?:-|–|—|to)\s*(?P<end>{DATE_TOKEN})",
    re.IGNORECASE,
)


class ResumeImportError(RuntimeError):
    pass


# Backward-compatible name for the locked OpenClaw import surface.
OpenClawResumeImportError = ResumeImportError


@dataclass(frozen=True)
class ResumeImportAIFacade:
    backend: AIBackend
    command: str
    agent_id: str
    thinking: str
    timeout_seconds: int
    model: str
    max_attempts: int
    retry_backoff_seconds: float

    def parse_experience(self, text: str) -> list[ImportedExperienceEntry]:
        return parse_experience_with_ai(
            text=text,
            command=self.command,
            agent_id=self.agent_id,
            thinking=self.thinking,
            timeout_seconds=self.timeout_seconds,
            model=self.model,
            backend=self.backend,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
        )

    def parse_education(self, text: str) -> list[ImportedEducationEntry]:
        return parse_education_with_ai(
            text=text,
            command=self.command,
            agent_id=self.agent_id,
            thinking=self.thinking,
            timeout_seconds=self.timeout_seconds,
            model=self.model,
            backend=self.backend,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
        )

    def parse_skills(self, text: str) -> list[str]:
        return parse_skills_with_ai(
            text=text,
            command=self.command,
            agent_id=self.agent_id,
            thinking=self.thinking,
            timeout_seconds=self.timeout_seconds,
            model=self.model,
            backend=self.backend,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
        )


def create_resume_import_ai_facade(settings: Settings) -> ResumeImportAIFacade:
    return ResumeImportAIFacade(
        backend=create_configured_ai_backend(settings),
        command=settings.openclaw_command,
        agent_id=settings.openclaw_agent_id,
        thinking=settings.ai_reasoning_for(settings.openclaw_resume_import_thinking),
        timeout_seconds=settings.ai_timeout_for(
            settings.openclaw_resume_import_timeout_seconds
        ),
        model=(
            settings.openai_api_model
            if settings.ai_backend_mode == "openai_api"
            else ""
        ),
        max_attempts=settings.ai_max_attempts_for(1),
        retry_backoff_seconds=settings.ai_retry_backoff_for(0),
    )


@dataclass
class ParsedExperience:
    title: str = ""
    company: str = ""
    employment_type: str = "Full-time"
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    description_lines: list[str] | None = None

    def to_model(self) -> ImportedExperienceEntry:
        description = "\n".join(self.description_lines or [])
        return ImportedExperienceEntry(
            title=self.title.strip(),
            company=self.company.strip(),
            employment_type=self.employment_type,
            location=self.location.strip(),
            start_date=self.start_date,
            end_date="" if self.is_current else self.end_date,
            is_current=self.is_current,
            description=description.strip(),
        )


@dataclass
class ParsedEducation:
    institution: str = ""
    credential: str = ""
    field_of_study: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    description_lines: list[str] | None = None

    def to_model(self) -> ImportedEducationEntry:
        description = "\n".join(self.description_lines or [])
        return ImportedEducationEntry(
            institution=self.institution.strip(),
            credential=self.credential.strip(),
            field_of_study=self.field_of_study.strip(),
            location=self.location.strip(),
            start_date=self.start_date,
            end_date="" if self.is_current else self.end_date,
            is_current=self.is_current,
            description=description.strip(),
        )


def decode_resume_data_url(data_url: str) -> tuple[str, bytes]:
    header, separator, payload = data_url.partition(",")
    if not separator:
        return "", data_url.encode()

    content_type = header.removeprefix("data:").split(";")[0]
    if ";base64" in header:
        return content_type, base64.b64decode(payload, validate=False)

    return content_type, payload.encode()


def extract_resume_text(file_name: str, data_url: str) -> str:
    content_type, content = decode_resume_data_url(data_url)
    lower_name = file_name.lower()

    if (
        lower_name.endswith((".docx", ".pdf"))
        or "wordprocessingml" in content_type
        or content_type == "application/pdf"
    ):
        try:
            extraction = extract_resume_source(
                file_name=file_name,
                content_type=content_type,
                content=content,
            )
            if extraction.text:
                return extraction.text
        except ResumeSourceExtractionError:
            if content.startswith(b"%PDF"):
                return ""

    if lower_name.endswith(".docx") or "wordprocessingml" in content_type:
        text = extract_docx_text(content)
        if text:
            return text

    if lower_name.endswith(".pdf") or content_type == "application/pdf":
        text = extract_pdf_text(content)
        if text:
            return text

    return decode_text_bytes(content)


def extract_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = [
                name
                for name in archive.namelist()
                if name == "word/document.xml"
                or name.startswith("word/header")
                or name.startswith("word/footer")
            ]
            parts: list[str] = []
            for name in names:
                lines = extract_docx_part_lines(archive.read(name))
                if lines:
                    parts.append("\n".join(lines))
            return "\n".join(parts)
    except (ElementTree.ParseError, KeyError, OSError, zipfile.BadZipFile):
        return ""


def extract_docx_body_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            return "\n".join(extract_docx_part_lines(archive.read("word/document.xml")))
    except (ElementTree.ParseError, KeyError, OSError, zipfile.BadZipFile):
        return ""


def extract_docx_part_lines(content: bytes) -> list[str]:
    root = ElementTree.fromstring(content)
    lines: list[str] = []
    for paragraph in root.iter():
        if not (paragraph.tag.endswith("}p") or paragraph.tag == "p"):
            continue
        text = "".join(iter_paragraph_text(paragraph)).strip()
        if text:
            lines.append(text)
    return lines


def iter_paragraph_text(element):
    for child in element:
        if child.tag.endswith("}p") or child.tag == "p":
            continue
        if child.tag.endswith("}t") or child.tag == "t":
            yield child.text or ""
        else:
            yield from iter_paragraph_text(child)


def extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return extract_pdf_text_fallback(content)


def extract_pdf_text_fallback(content: bytes) -> str:
    decoded = decode_text_bytes(content)
    literal_strings = re.findall(r"\(([^()]*(?:\\.[^()]*)*)\)\s*Tj", decoded)
    if not literal_strings:
        literal_strings = re.findall(r"\(([^()]*(?:\\.[^()]*)*)\)", decoded)

    if literal_strings:
        return "\n".join(unescape_pdf_string(item) for item in literal_strings)

    return decoded


def unescape_pdf_string(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\n")
        .replace(r"\t", "\t")
    )


def decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def parse_experience_from_text(text: str) -> list[ImportedExperienceEntry]:
    lines = normalize_lines(text)
    section_lines = get_experience_section(lines)
    if not section_lines:
        section_lines = lines

    entries = parse_experience_lines(section_lines)
    return [
        entry.to_model()
        for entry in entries
        if entry.title and entry.company and (entry.start_date or entry.description_lines)
    ][:12]


def parse_education_from_text(text: str) -> list[ImportedEducationEntry]:
    lines = normalize_lines(text)
    section_lines = get_education_section(lines)
    if not section_lines:
        return []

    entries = parse_education_lines(section_lines)
    return [
        entry.to_model()
        for entry in entries
        if entry.institution or entry.credential or entry.field_of_study
    ][:12]


def parse_skills_from_text(text: str) -> list[str]:
    lines = normalize_lines(text)
    section_lines = get_skills_section(lines)
    if not section_lines:
        return []

    return normalize_skill_list(extract_skill_candidates(section_lines))


def parse_experience_with_ai(
    text: str,
    command: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
    model: str = "",
    backend: AIBackend | None = None,
    max_attempts: int = 1,
    retry_backoff_seconds: float = 0,
) -> list[ImportedExperienceEntry]:
    resume_text = text.strip()
    if not resume_text:
        return []

    prompt = build_openclaw_resume_prompt(resume_text[:50000])
    parsed = run_resume_ai_backend(
        prompt=prompt,
        command=command,
        agent_id=agent_id,
        thinking=thinking,
        timeout_seconds=timeout_seconds,
        model=model,
        backend=backend,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        payload_extractor=extract_openclaw_experience_payload,
        response_model=ResumeExperienceStructuredOutput,
    )
    entries = parsed.get("experience", [])
    if not isinstance(entries, list):
        return []

    return [
        ImportedExperienceEntry.model_validate(entry)
        for entry in entries
        if isinstance(entry, dict)
    ][:12]


def parse_education_with_ai(
    text: str,
    command: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
    model: str = "",
    backend: AIBackend | None = None,
    max_attempts: int = 1,
    retry_backoff_seconds: float = 0,
) -> list[ImportedEducationEntry]:
    resume_text = text.strip()
    if not resume_text:
        return []

    prompt = build_openclaw_education_prompt(resume_text[:50000])
    parsed = run_resume_ai_backend(
        prompt=prompt,
        command=command,
        agent_id=agent_id,
        thinking=thinking,
        timeout_seconds=timeout_seconds,
        model=model,
        backend=backend,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        payload_extractor=extract_openclaw_education_payload,
        response_model=ResumeEducationStructuredOutput,
    )
    entries = parsed.get("education", [])
    if not isinstance(entries, list):
        return []

    return [
        ImportedEducationEntry.model_validate(entry)
        for entry in entries
        if isinstance(entry, dict)
    ][:12]


def parse_skills_with_ai(
    text: str,
    command: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
    model: str = "",
    backend: AIBackend | None = None,
    max_attempts: int = 1,
    retry_backoff_seconds: float = 0,
) -> list[str]:
    resume_text = text.strip()
    if not resume_text:
        return []

    prompt = build_openclaw_skills_prompt(resume_text[:50000])
    parsed = run_resume_ai_backend(
        prompt=prompt,
        command=command,
        agent_id=agent_id,
        thinking=thinking,
        timeout_seconds=timeout_seconds,
        model=model,
        backend=backend,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        payload_extractor=extract_openclaw_skills_payload,
        response_model=ResumeSkillsStructuredOutput,
    )
    skills = parsed.get("skills", [])
    if not isinstance(skills, list):
        return []

    return normalize_skill_list([skill for skill in skills if isinstance(skill, str)])


def parse_experience_with_openclaw(*args, **kwargs) -> list[ImportedExperienceEntry]:
    return parse_experience_with_ai(*args, **kwargs)


def parse_education_with_openclaw(*args, **kwargs) -> list[ImportedEducationEntry]:
    return parse_education_with_ai(*args, **kwargs)


def parse_skills_with_openclaw(*args, **kwargs) -> list[str]:
    return parse_skills_with_ai(*args, **kwargs)


def run_resume_ai_backend(
    *,
    prompt: str,
    command: str,
    agent_id: str,
    thinking: str,
    timeout_seconds: int,
    model: str,
    backend: AIBackend | None,
    max_attempts: int,
    retry_backoff_seconds: float,
    payload_extractor,
    response_model: type[BaseModel],
) -> dict[str, object]:
    selected_backend = backend or OpenClawCodexBackend(
        command=command,
        sync_runner=subprocess.run,
    )
    try:
        result = generate_with_retries(
            selected_backend,
            AIRequest(
                prompt=prompt,
                model=model,
                agent_id=agent_id,
                thinking=thinking,
                timeout_seconds=timeout_seconds,
                session_id=f"agent:{agent_id}:resume-import-{uuid4().hex}",
                structured=True,
                response_model=response_model,
            ),
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
    except AIBackendError as exc:
        if exc.code == "runtime_missing":
            message = (
                f"OpenClaw command was not found: {command}"
                if selected_backend.name == "openclaw_codex"
                else "The configured AI runtime is unavailable"
            )
            raise ResumeImportError(message) from exc
        if exc.code == "timeout":
            message = (
                "OpenClaw resume import timed out"
                if selected_backend.name == "openclaw_codex"
                else "AI resume import timed out"
            )
            raise ResumeImportError(message) from exc
        message = (
            summarize_openclaw_error(str(exc))
            if selected_backend.name == "openclaw_codex"
            else "AI resume import failed"
        )
        raise ResumeImportError(message) from exc

    if isinstance(result.structured_data, dict):
        return result.structured_data
    return payload_extractor(result.raw_response)


def summarize_openclaw_error(error_output: str) -> str:
    if "GatewayCredentialsRequiredError" in error_output or "gateway agent requires credentials" in error_output:
        return (
            "OpenClaw gateway credentials are not available in the API container. "
            "Mount ~/.openclaw or configure model auth/API key for the container."
        )

    if "No API key found" in error_output:
        return (
            "OpenClaw model auth is not configured for the selected agent. "
            "Run `openclaw models status` and configure a usable model/auth profile."
        )

    if "No target session selected" in error_output:
        return "OpenClaw needs an agent or session target. Set OPENCLAW_AGENT_ID to a configured agent."

    if "Model override" in error_output and "not allowed" in error_output:
        return "OpenClaw rejected the configured model override for this agent."

    first_line = next((line.strip() for line in error_output.splitlines() if line.strip()), "")
    return first_line[:240] or "OpenClaw command failed"


def extract_openclaw_experience_payload(value: str) -> dict[str, object]:
    return extract_openclaw_payload(value, "experience")


def extract_openclaw_education_payload(value: str) -> dict[str, object]:
    return extract_openclaw_payload(value, "education")


def extract_openclaw_skills_payload(value: str) -> dict[str, object]:
    return extract_openclaw_payload(value, "skills")


def extract_openclaw_payload(value: str, key: str) -> dict[str, object]:
    for payload in extract_json_objects(value):
        if isinstance(payload.get(key), list):
            return payload

        for text in extract_openclaw_text_payloads(payload):
            final_payload = extract_json_object(text)
            if isinstance(final_payload.get(key), list):
                return final_payload

        result = payload.get("result")
        if not isinstance(result, dict):
            continue

        final_text = result.get("finalAssistantVisibleText") or result.get("finalAssistantRawText")
        if isinstance(final_text, str):
            final_payload = extract_json_object(final_text)
            if isinstance(final_payload.get(key), list):
                return final_payload

        nested_result = result.get("result")
        if isinstance(nested_result, dict):
            final_text = nested_result.get("finalAssistantVisibleText") or nested_result.get("finalAssistantRawText")
            if isinstance(final_text, str):
                final_payload = extract_json_object(final_text)
                if isinstance(final_payload.get(key), list):
                    return final_payload

    return {}


def extract_openclaw_text_payloads(payload: dict[str, object]) -> list[str]:
    texts: list[str] = []

    def append_payload_texts(container: dict[str, object]) -> None:
        payloads = container.get("payloads")
        if not isinstance(payloads, list):
            return
        for item in payloads:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                texts.append(text)

    append_payload_texts(payload)
    result = payload.get("result")
    if isinstance(result, dict):
        append_payload_texts(result)
        nested_result = result.get("result")
        if isinstance(nested_result, dict):
            append_payload_texts(nested_result)

    return texts


def build_openclaw_resume_prompt(resume_text: str) -> str:
    return (
        "You are extracting work experience from a resume for a job search app.\n"
        "Return ONLY one valid JSON object, no markdown and no prose.\n"
        "JSON shape:\n"
        "{\n"
        '  "experience": [\n'
        "    {\n"
        '      "title": "string",\n'
        '      "company": "string",\n'
        '      "employment_type": "Full-time|Part-time|Internship|Freelance|Contract|Project|string",\n'
        '      "location": "string",\n'
        '      "start_date": "YYYY-MM or empty string",\n'
        '      "end_date": "YYYY-MM or empty string",\n'
        '      "is_current": true,\n'
        '      "description": "one responsibility or achievement per line"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Extract only real work, internship, freelance, contract, and substantial project roles.\n"
        "- Do not include education, skills, summary, or contact sections.\n"
        "- Do not merge separate roles into one item.\n"
        "- Preserve separate companies/projects as separate objects.\n"
        "- If a field is unknown, use an empty string.\n"
        "- For current roles, set is_current true and end_date empty.\n"
        "- Use YYYY-MM when a month is known; for year-only start use YYYY-01, for year-only end use YYYY-12.\n\n"
        f"Resume text:\n{resume_text}"
    )


def build_openclaw_education_prompt(resume_text: str) -> str:
    return (
        "You are extracting education, courses, and certifications from a resume for a job search app.\n"
        "Return ONLY one valid JSON object, no markdown and no prose.\n"
        "JSON shape:\n"
        "{\n"
        '  "education": [\n'
        "    {\n"
        '      "institution": "string",\n'
        '      "credential": "degree, certification, course, bootcamp, or training name",\n'
        '      "field_of_study": "string",\n'
        '      "location": "string",\n'
        '      "start_date": "YYYY-MM or empty string",\n'
        '      "end_date": "YYYY-MM or empty string",\n'
        '      "is_current": true,\n'
        '      "description": "relevant details, honors, coursework, or credential notes; one item per line"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Extract degrees, universities, colleges, bootcamps, courses, certificates, certifications, and relevant training.\n"
        "- Do not include work experience, skills, summary, contact sections, or unrelated projects.\n"
        "- Do not merge separate credentials into one item.\n"
        "- If a field is unknown, use an empty string.\n"
        "- For current studies, set is_current true and end_date empty.\n"
        "- Use YYYY-MM when a month is known; for year-only start use YYYY-01, for year-only end use YYYY-12.\n\n"
        f"Resume text:\n{resume_text}"
    )


def build_openclaw_skills_prompt(resume_text: str) -> str:
    return (
        "You are extracting skills from a resume for a job search app.\n"
        "Return ONLY one valid JSON object, no markdown and no prose.\n"
        "JSON shape:\n"
        "{\n"
        '  "skills": ["skill name"]\n'
        "}\n"
        "Rules:\n"
        "- Extract concrete skills, programming languages, frameworks, libraries, tools, platforms, databases, methodologies, and relevant technical domains.\n"
        "- Do not include employers, schools, job titles, dates, responsibilities, contact details, or generic soft phrases unless they are listed as explicit skills.\n"
        "- Keep each skill short and canonical, for example \"Python\", \"FastAPI\", \"Docker\", \"Machine Learning\".\n"
        "- Do not duplicate skills, including case-only duplicates.\n"
        "- Preserve common capitalization such as SQL, CI/CD, AWS, React, TypeScript, and OpenAI API.\n"
        "- Return at most 80 skills.\n\n"
        f"Resume text:\n{resume_text}"
    )


def extract_json_object(value: str) -> dict[str, object]:
    for payload in extract_json_objects(value):
        return payload

    return {}


def extract_json_objects(value: str) -> list[dict[str, object]]:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    payloads: list[dict[str, object]] = []
    for match in re.finditer(r"{", stripped):
        try:
            parsed, _ = decoder.raw_decode(stripped[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)

    return payloads


def normalize_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip(" \t-•*")
        for line in text.replace("\r", "\n").split("\n")
        if line.strip(" \t-•*")
    ]


def normalize_heading(line: str) -> str:
    return normalize_resume_heading(line)


def get_experience_section(lines: list[str]) -> list[str]:
    start_index: int | None = None
    for index, line in enumerate(lines):
        heading = normalize_heading(line)
        if heading in EXPERIENCE_HEADINGS:
            start_index = index + 1
            break

    if start_index is None:
        return []

    end_index = len(lines)
    for index in range(start_index, len(lines)):
        heading = normalize_heading(lines[index])
        if heading in SECTION_STOP_HEADINGS:
            end_index = index
            break

    return lines[start_index:end_index]


def get_education_section(lines: list[str]) -> list[str]:
    start_index: int | None = None
    for index, line in enumerate(lines):
        heading = normalize_heading(line)
        if heading in EDUCATION_HEADINGS:
            start_index = index + 1
            break

    if start_index is None:
        return []

    end_index = len(lines)
    for index in range(start_index, len(lines)):
        heading = normalize_heading(lines[index])
        if heading in EDUCATION_STOP_HEADINGS:
            end_index = index
            break

    return lines[start_index:end_index]


def get_skills_section(lines: list[str]) -> list[str]:
    start_index: int | None = None
    for index, line in enumerate(lines):
        heading = normalize_heading(line)
        if heading in SKILLS_HEADINGS:
            start_index = index + 1
            break

    if start_index is None:
        return []

    end_index = len(lines)
    for index in range(start_index, len(lines)):
        heading = normalize_heading(lines[index])
        if heading in SKILLS_STOP_HEADINGS:
            end_index = index
            break

    return lines[start_index:end_index]


def extract_skill_candidates(lines: list[str]) -> list[str]:
    candidates: list[str] = []
    for line in lines:
        value = re.sub(r"\s+", " ", line).strip(" \t-•*")
        if not value:
            continue

        category, separator, rest = value.partition(":")
        if separator and len(category.split()) <= 4:
            value = rest.strip()

        if re.search(r"[,;|•]", value):
            candidates.extend(re.split(r"\s*[,;|•]\s*", value))
        elif len(value.split()) <= 5:
            candidates.append(value)

    return candidates


def normalize_skill_list(values: list[str]) -> list[str]:
    normalized_skills: list[str] = []
    seen: set[str] = set()

    for value in values:
        skill = re.sub(r"\s+", " ", value).strip(" \t-•*,.;:")
        if not is_valid_skill(skill):
            continue

        key = skill.lower()
        if key in seen:
            continue

        seen.add(key)
        normalized_skills.append(skill)

    return normalized_skills[:80]


def is_valid_skill(value: str) -> bool:
    if len(value) < 2 or len(value) > 60:
        return False

    lowered = value.lower()
    if lowered in SKILLS_HEADINGS or lowered in SKILLS_STOP_HEADINGS:
        return False

    if "@" in value or re.search(r"https?://|www\.", value, re.IGNORECASE):
        return False

    if DATE_RANGE_RE.search(value) or re.fullmatch(r"\d{4}(?:\s*-\s*\d{4})?", value):
        return False

    return bool(re.search(r"[A-Za-z+#./]", value))


def parse_experience_lines(lines: list[str]) -> list[ParsedExperience]:
    entries: list[ParsedExperience] = []
    current: ParsedExperience | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        is_header = looks_like_entry_header(line) or (
            bool(next_line and DATE_RANGE_RE.search(next_line)) and not looks_like_description(line)
        )

        if is_header:
            if current:
                entries.append(current)

            date_line = next_line if next_line and DATE_RANGE_RE.search(next_line) else ""
            current = parse_entry_header(line, date_line)
            index += 2 if date_line else 1
            continue

        if current:
            current.description_lines = current.description_lines or []
            current.description_lines.append(line)

        index += 1

    if current:
        entries.append(current)

    return entries


def parse_education_lines(lines: list[str]) -> list[ParsedEducation]:
    entries: list[ParsedEducation] = []
    current: ParsedEducation | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        is_header = looks_like_education_header(line) or (
            bool(next_line and DATE_RANGE_RE.search(next_line)) and not looks_like_description(line)
        )

        if is_header:
            if current:
                entries.append(current)

            date_line = next_line if next_line and DATE_RANGE_RE.search(next_line) else ""
            current = parse_education_header(line, date_line)
            index += 2 if date_line else 1
            continue

        if current:
            current.description_lines = current.description_lines or []
            current.description_lines.append(line)
        else:
            current = parse_education_header(line)

        index += 1

    if current:
        entries.append(current)

    return entries


def looks_like_entry_header(line: str) -> bool:
    if looks_like_description(line):
        return False

    lowered = line.lower()
    has_date = bool(DATE_RANGE_RE.search(line))
    has_title_hint = any(hint in lowered for hint in TITLE_HINTS)
    has_separator = bool(re.search(r"\s(?:at|@)\s|[|•–—]", line, re.IGNORECASE))
    return has_date or (has_title_hint and has_separator)


def looks_like_education_header(line: str) -> bool:
    if looks_like_description(line):
        return False

    lowered = line.lower()
    if lowered.startswith(("coursework", "relevant coursework", "honors", "thesis")):
        return False

    has_date = bool(DATE_RANGE_RE.search(line))
    has_credential_hint = any(hint in lowered for hint in CREDENTIAL_HINTS)
    has_separator = bool(re.search(r"\s(?:at|@)\s|[|•–—]", line, re.IGNORECASE))
    return has_date or has_credential_hint or has_separator


def looks_like_description(line: str) -> bool:
    lowered = line.lower()
    return lowered.startswith(("built ", "created ", "developed ", "managed ", "led ", "worked ", "improved "))


def parse_entry_header(line: str, date_line: str = "") -> ParsedExperience:
    combined = f"{line} {date_line}".strip()
    date_match = DATE_RANGE_RE.search(combined)
    start_date = ""
    end_date = ""
    is_current = False

    if date_match:
        start_date = normalize_date(date_match.group("start"), is_start=True)
        end_raw = date_match.group("end")
        is_current = end_raw.lower().strip(".") in {"present", "current", "now"}
        end_date = "" if is_current else normalize_date(end_raw, is_start=False)

    cleaned = DATE_RANGE_RE.sub("", line)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—|•,")
    title, company, location = split_title_company_location(cleaned)

    return ParsedExperience(
        title=title,
        company=company,
        location=location,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
        description_lines=[],
    )


def parse_education_header(line: str, date_line: str = "") -> ParsedEducation:
    combined = f"{line} {date_line}".strip()
    date_match = DATE_RANGE_RE.search(combined)
    start_date = ""
    end_date = ""
    is_current = False

    if date_match:
        start_date = normalize_date(date_match.group("start"), is_start=True)
        end_raw = date_match.group("end")
        is_current = end_raw.lower().strip(".") in {"present", "current", "now"}
        end_date = "" if is_current else normalize_date(end_raw, is_start=False)

    cleaned = DATE_RANGE_RE.sub("", line)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—|•,")
    institution, credential, field_of_study, location = split_education_parts(cleaned)

    return ParsedEducation(
        institution=institution,
        credential=credential,
        field_of_study=field_of_study,
        location=location,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
        description_lines=[],
    )


def split_title_company_location(value: str) -> tuple[str, str, str]:
    at_match = re.match(r"(?P<title>.+?)\s+(?:at|@)\s+(?P<company>.+)$", value, re.IGNORECASE)
    if at_match:
        return at_match.group("title").strip(), at_match.group("company").strip(), ""

    parts = [part.strip() for part in re.split(r"\s*[|•–—]\s*", value) if part.strip()]
    if len(parts) < 2:
        parts = [part.strip() for part in value.split(",") if part.strip()]

    if len(parts) >= 2:
        first, second = parts[0], parts[1]
        title, company = infer_title_company(first, second)
        location = " • ".join(parts[2:])
        return title, company, location

    return value.strip(), "", ""


def split_education_parts(value: str) -> tuple[str, str, str, str]:
    at_match = re.match(r"(?P<credential>.+?)\s+(?:at|@)\s+(?P<institution>.+)$", value, re.IGNORECASE)
    if at_match:
        return at_match.group("institution").strip(), at_match.group("credential").strip(), "", ""

    parts = [part.strip() for part in re.split(r"\s*[|•–—]\s*", value) if part.strip()]
    if len(parts) < 2:
        parts = [part.strip() for part in value.split(",") if part.strip()]

    if len(parts) >= 2:
        first, second = parts[0], parts[1]
        first_is_credential = any(hint in first.lower() for hint in CREDENTIAL_HINTS)
        second_is_credential = any(hint in second.lower() for hint in CREDENTIAL_HINTS)
        if first_is_credential and not second_is_credential:
            credential, institution = first, second
        elif second_is_credential and not first_is_credential:
            institution, credential = first, second
        else:
            institution, credential = first, second

        field_of_study = parts[2] if len(parts) >= 3 else ""
        location = " • ".join(parts[3:])
        return institution, credential, field_of_study, location

    if any(hint in value.lower() for hint in CREDENTIAL_HINTS):
        return "", value.strip(), "", ""

    return value.strip(), "", "", ""


def infer_title_company(first: str, second: str) -> tuple[str, str]:
    first_is_title = any(hint in first.lower() for hint in TITLE_HINTS)
    second_is_title = any(hint in second.lower() for hint in TITLE_HINTS)

    if second_is_title and not first_is_title:
        return second, first

    return first, second


def normalize_date(value: str, is_start: bool) -> str:
    cleaned = value.strip().strip(".")
    month_match = re.match(r"(?P<month>[A-Za-z]+)\.?\s+(?P<year>\d{4})", cleaned)
    if month_match:
        month = MONTHS.get(month_match.group("month").lower(), "01")
        return f"{month_match.group('year')}-{month}"

    numeric_match = re.match(r"(?P<month>\d{1,2})/(?P<year>\d{4})", cleaned)
    if numeric_match:
        return f"{numeric_match.group('year')}-{int(numeric_match.group('month')):02d}"

    year_match = re.match(r"\d{4}", cleaned)
    if year_match:
        return f"{year_match.group(0)}-{'01' if is_start else '12'}"

    return ""
