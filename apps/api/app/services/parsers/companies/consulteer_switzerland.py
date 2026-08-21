from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

CONSULTEER_JOBS_BASE_URL = "https://www.consulteer.com/careers"
CONSULTEER_JOBS_API_URL = "https://consulteer1.recruitee.com/api/offers/"
CONSULTEER_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Consulteer"
GUID_PATTERN = re.compile(r"^[a-z0-9]+$")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")
RECRUITEE_TIMESTAMP_PATTERN = "%Y-%m-%d %H:%M:%S UTC"
EMPLOYMENT_TYPE_LABELS = {
    "fulltime_permanent": "Full-time, permanent",
    "parttime_permanent": "Part-time, permanent",
    "fulltime_fixed_term": "Full-time, fixed-term",
    "parttime_fixed_term": "Part-time, fixed-term",
    "fulltime": "Full-time",
    "parttime": "Part-time",
    "internship": "Internship",
    "apprenticeship": "Apprenticeship",
}
EXPERIENCE_LABELS = {
    "student_school": "Student",
    "no_experience": "Entry level",
    "entry_level": "Entry level",
    "mid_level": "Mid level",
    "experienced": "Experienced",
    "senior_manager": "Senior manager / Supervisor",
    "manager": "Manager",
    "executive": "Executive",
}


class ConsulteerSwitzerlandParseError(DirectCompanyRequestError):
    pass


class ConsulteerSwitzerlandJobsParser:
    """Collect Consulteer's complete catalog and expose its Swiss vacancies."""

    parser_id = "consulteer_switzerland"

    def __init__(
        self,
        *,
        base_url: str = CONSULTEER_JOBS_BASE_URL,
        api_url: str = CONSULTEER_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
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
                headers={**CONSULTEER_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                catalog = parse_catalog_payload(
                    response.json(),
                    max_jobs=self.max_jobs,
                )
        except ConsulteerSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Consulteer vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Consulteer vacancy parsing failed"
            ) from exc

        records = [record for record in catalog if record["swiss_locations"]]
        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_consulteer_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Consulteer Swiss vacancies from "
                f"{len(catalog)} global Recruitee records"
            ),
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        salary = record.get("salary")
        salary = salary if isinstance(salary, dict) else {}
        salary_min = optional_int(salary.get("min"))
        salary_max = optional_int(salary.get("max"))
        salary_currency = optional_text(salary.get("currency"))
        salary_unit = optional_text(salary.get("period"))
        slug = optional_text(record.get("slug"))
        raw = dict(record)
        raw["recruitee_url"] = optional_text(record.get("careers_url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=extract_swiss_location(record),
            url=f"{self.base_url.rstrip('/')}/{slug}" if slug else self.base_url,
            apply_url=optional_text(record.get("careers_apply_url")),
            posted_at=normalize_timestamp(record.get("published_at")),
            employment_type=format_code(
                record.get("employment_type_code"),
                EMPLOYMENT_TYPE_LABELS,
            ),
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
            raw=raw,
        )


def parse_catalog_payload(payload: Any, *, max_jobs: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("offers"), list):
        raise ConsulteerSwitzerlandParseError(
            "Consulteer jobs response is missing its offers catalog"
        )
    offers = payload["offers"]
    if not offers:
        raise ConsulteerSwitzerlandParseError("Consulteer offers catalog is empty")
    if len(offers) > max_jobs:
        raise ConsulteerSwitzerlandParseError(
            f"Consulteer exposes {len(offers)} vacancies, above the configured "
            f"limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_guids: set[str] = set()
    seen_slugs: set[str] = set()
    for item in offers:
        if not isinstance(item, dict):
            raise ConsulteerSwitzerlandParseError(
                "Consulteer jobs response contains an invalid vacancy"
            )
        job_id = extract_job_id(item.get("id"))
        guid = optional_text(item.get("guid"))
        slug = optional_text(item.get("slug"))
        locations = validate_locations(item)
        if (
            not job_id
            or not guid
            or not GUID_PATTERN.fullmatch(guid)
            or not slug
            or not SLUG_PATTERN.fullmatch(slug)
            or not optional_text(item.get("title"))
            or optional_text(item.get("company_name")) != EXPECTED_COMPANY
            or optional_text(item.get("status")) != "published"
            or not valid_offer_url(item.get("careers_url"), expected_slug=slug)
            or not valid_offer_url(
                item.get("careers_apply_url"),
                expected_slug=slug,
                apply=True,
            )
            or not normalize_timestamp(item.get("published_at"))
            or not html_to_text(optional_text(item.get("description")))
            or not optional_text(item.get("employment_type_code"))
            or not optional_text(item.get("experience_code"))
            or not valid_primary_location(item, locations)
        ):
            raise ConsulteerSwitzerlandParseError(
                "Consulteer jobs response contains an incomplete vacancy"
            )
        if job_id in seen_ids or guid in seen_guids or slug in seen_slugs:
            raise ConsulteerSwitzerlandParseError(
                "Consulteer jobs response contains duplicate vacancy identifiers"
            )
        seen_ids.add(job_id)
        seen_guids.add(guid)
        seen_slugs.add(slug)
        record = dict(item)
        record["swiss_locations"] = [
            dict(location) for location in locations if location["country_code"] == "CH"
        ]
        records.append(record)
    return records


def validate_locations(item: dict[str, Any]) -> list[dict[str, Any]]:
    value = item.get("locations")
    if not isinstance(value, list) or not value:
        raise ConsulteerSwitzerlandParseError(
            "Consulteer vacancy is missing structured locations"
        )
    locations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for location in value:
        if not isinstance(location, dict):
            raise ConsulteerSwitzerlandParseError(
                "Consulteer vacancy contains an invalid location"
            )
        country_code = optional_text(location.get("country_code"))
        city = optional_text(location.get("city"))
        state = optional_text(location.get("state"))
        if (
            not country_code
            or not COUNTRY_CODE_PATTERN.fullmatch(country_code)
            or not optional_text(location.get("country"))
            or not city
        ):
            raise ConsulteerSwitzerlandParseError(
                "Consulteer vacancy contains an incomplete location"
            )
        key = (country_code, city.casefold(), (state or "").casefold())
        if key in seen:
            raise ConsulteerSwitzerlandParseError(
                "Consulteer vacancy contains duplicate locations"
            )
        seen.add(key)
        locations.append(dict(location))
    return locations


def valid_primary_location(
    item: dict[str, Any],
    locations: list[dict[str, Any]],
) -> bool:
    country_code = optional_text(item.get("country_code"))
    city = optional_text(item.get("city"))
    if (
        not country_code
        or not COUNTRY_CODE_PATTERN.fullmatch(country_code)
        or not optional_text(item.get("country"))
        or not city
    ):
        return False
    return any(
        optional_text(location.get("country_code")) == country_code
        and optional_text(location.get("city")) == city
        for location in locations
    )


def valid_offer_url(
    value: Any,
    *,
    expected_slug: str,
    apply: bool = False,
) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    base_path = f"/o/{expected_slug}"
    expected_path = f"{base_path}/c/new" if apply else base_path
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "consulteer1.recruitee.com"
        and parts.path.rstrip("/") == expected_path
        and not parse_qs(parts.query, keep_blank_values=True)
        and not parts.fragment
    )


def extract_swiss_location(record: dict[str, Any]) -> str | None:
    value = record.get("swiss_locations")
    labels: list[str] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for location in value:
            if not isinstance(location, dict):
                continue
            parts = [
                optional_text(location.get("city")),
                optional_text(location.get("state")),
                "Switzerland",
            ]
            label = ", ".join(part for part in parts if part)
            if label and label not in labels:
                labels.append(label)
    return "; ".join(labels) or None


def extract_description(record: dict[str, Any]) -> str | None:
    sections = [
        text
        for field in ("highlight", "description", "requirements")
        if (text := html_to_text(optional_text(record.get(field))))
    ]
    return "\n\n".join(dict.fromkeys(sections)) or None


def normalize_timestamp(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, RECRUITEE_TIMESTAMP_PATTERN).replace(tzinfo=UTC)
    except ValueError:
        return None
    return parsed.date().isoformat()


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    return text if text and text.isdigit() and int(text) > 0 else None


def deduplicate_consulteer_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
