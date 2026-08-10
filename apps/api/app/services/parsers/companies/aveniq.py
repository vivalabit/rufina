from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AVENIQ_JOBS_BASE_URL = "https://aveniq.recruitee.com/"
AVENIQ_JOBS_API_URL = "https://aveniq.recruitee.com/api/offers/"
AVENIQ_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
PERCENTAGE_PATTERN = re.compile(r"^\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%$")
EMPLOYMENT_TYPE_LABELS = {
    "fulltime_permanent": "Full-time, permanent",
    "parttime_permanent": "Part-time, permanent",
    "fulltime_temporary": "Full-time, temporary",
    "parttime_temporary": "Part-time, temporary",
    "internship": "Internship",
}
EXPERIENCE_LABELS = {
    "no_experience": "Entry level",
    "experienced": "Experienced",
    "manager": "Manager",
    "executive": "Executive",
}


class AveniqParseError(DirectCompanyRequestError):
    pass


class AveniqJobsParser:
    """Collect the complete Aveniq catalog from its public Recruitee API."""

    parser_id = "aveniq"

    def __init__(
        self,
        *,
        base_url: str = AVENIQ_JOBS_BASE_URL,
        api_url: str = AVENIQ_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 1000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**AVENIQ_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records = parse_catalog_payload(
                    response.json(),
                    max_jobs=self.max_jobs,
                )
        except AveniqParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Aveniq vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Aveniq vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_aveniq_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Aveniq vacancies from the full Recruitee catalog"),
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        salary = record.get("salary")
        salary = salary if isinstance(salary, dict) else {}
        salary_min = optional_int(salary.get("min"))
        salary_max = optional_int(salary.get("max"))
        salary_currency = optional_text(salary.get("currency"))
        salary_unit = optional_text(salary.get("period"))

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=optional_text(record.get("company_name")) or "Aveniq AG",
            location=extract_location(record),
            url=optional_text(record.get("careers_url")),
            apply_url=optional_text(record.get("careers_apply_url")),
            posted_at=optional_text(record.get("published_at")),
            employment_type=extract_employment_type(record),
            seniority=format_code(record.get("experience_code"), EXPERIENCE_LABELS),
            description=extract_description(record),
            salary=format_salary(
                salary_min,
                salary_max,
                salary_currency,
                salary_unit,
            ),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_unit=salary_unit,
            raw=dict(record),
        )


def parse_catalog_payload(payload: Any, *, max_jobs: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("offers"), list):
        raise AveniqParseError("Aveniq jobs response is missing its offers catalog")

    offers = payload["offers"]
    if len(offers) > max_jobs:
        raise AveniqParseError(
            f"Aveniq exposes {len(offers)} vacancies, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in offers:
        if not isinstance(item, dict):
            raise AveniqParseError("Aveniq jobs response contains an invalid vacancy")
        job_id = extract_job_id(item.get("id"))
        title = optional_text(item.get("title"))
        public_url = optional_text(item.get("careers_url"))
        apply_url = optional_text(item.get("careers_apply_url"))
        if (
            not job_id
            or not title
            or not valid_offer_url(public_url)
            or not valid_offer_url(apply_url, apply=True)
            or optional_text(item.get("status")) != "published"
            or optional_text(item.get("country_code")) != "CH"
            or not has_only_swiss_locations(item.get("locations"))
        ):
            raise AveniqParseError(
                "Aveniq jobs response contains an incomplete or non-Swiss vacancy"
            )
        if job_id in seen_ids:
            raise AveniqParseError("Aveniq jobs response contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(dict(item))
    return records


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    return text if text and text.isdigit() and int(text) > 0 else None


def valid_offer_url(value: str | None, *, apply: bool = False) -> bool:
    if not value:
        return False
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.netloc != "aveniq.recruitee.com":
        return False
    if not parts.path.startswith("/o/"):
        return False
    return parts.path.endswith("/c/new") if apply else not parts.path.endswith("/c/new")


def has_only_swiss_locations(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(
        isinstance(location, dict)
        and optional_text(location.get("country_code")) == "CH"
        and optional_text(location.get("city"))
        for location in value
    )


def extract_location(record: dict[str, Any]) -> str | None:
    locations = record.get("locations")
    values: list[str] = []
    if isinstance(locations, Sequence) and not isinstance(locations, (str, bytes)):
        for location in locations:
            if not isinstance(location, dict):
                continue
            parts = [
                optional_text(location.get("city")),
                optional_text(location.get("state")),
                optional_text(location.get("country")),
            ]
            label = ", ".join(part for part in parts if part)
            if label and label not in values:
                values.append(label)
    return "; ".join(values) or optional_text(record.get("location"))


def extract_employment_type(record: dict[str, Any]) -> str | None:
    tags = record.get("tags")
    if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes)):
        for tag in tags:
            text = optional_text(tag)
            if text and PERCENTAGE_PATTERN.fullmatch(text):
                return re.sub(r"\s*[-–]\s*", "-", text)
    return format_code(record.get("employment_type_code"), EMPLOYMENT_TYPE_LABELS)


def extract_description(record: dict[str, Any]) -> str | None:
    sections = [
        text
        for field in ("highlight", "description", "requirements")
        if (text := html_to_text(optional_text(record.get(field))))
    ]
    return "\n\n".join(dict.fromkeys(sections)) or None


def deduplicate_aveniq_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def format_code(value: Any, labels: dict[str, str]) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    return labels.get(text, text.replace("_", " ").capitalize())


def format_salary(
    minimum: int | None,
    maximum: int | None,
    currency: str | None,
    unit: str | None,
) -> str | None:
    if minimum is None and maximum is None:
        return None
    amount = (
        f"{minimum:,}-{maximum:,}"
        if minimum is not None and maximum is not None
        else f"{minimum or maximum:,}"
    )
    suffix = " ".join(value for value in (currency, unit) if value)
    return f"{amount} {suffix}".strip()


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
