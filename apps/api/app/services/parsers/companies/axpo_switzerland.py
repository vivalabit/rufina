from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AXPO_SWITZERLAND_JOBS_BASE_URL = (
    "https://careers.axpo.com/jobs?split_view=true&query=&country=Switzerland"
)
AXPO_SWITZERLAND_JOBS_FEED_URL = "https://careers.axpo.com/jobs.json"
AXPO_SWITZERLAND_COUNTRY = "Switzerland"
AXPO_SWITZERLAND_COUNTRY_CODE = "CH"
AXPO_TEAMTAILOR_PAGE_SIZE = 20
AXPO_HEADERS = {
    "Accept": "application/feed+json, application/json;q=0.9",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JSON_FEED_VERSION_PREFIX = "https://jsonfeed.org/version/"
JOB_PATH_PATTERN = re.compile(r"/jobs/(\d+)(?:[-/]|$)", re.IGNORECASE)


class AxpoSwitzerlandParseError(DirectCompanyRequestError):
    pass


class AxpoSwitzerlandJobsParser:
    """Collect only Swiss Axpo vacancies from its public Teamtailor JSON Feed."""

    parser_id = "axpo_switzerland"

    def __init__(
        self,
        *,
        base_url: str = AXPO_SWITZERLAND_JOBS_BASE_URL,
        feed_url: str = AXPO_SWITZERLAND_JOBS_FEED_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_jobs: int = 1000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.feed_url = feed_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_jobs = max(1, max_jobs)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            records, pages_scanned, filtered_total = self.fetch_catalog()
        except AxpoSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Axpo Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Axpo Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_axpo_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} strictly Swiss Axpo vacancies from "
                f"{filtered_total} country-filtered Teamtailor postings "
                f"across {pages_scanned} JSON Feed pages"
            ),
        )

    def fetch_catalog(self) -> tuple[list[dict[str, Any]], int, int]:
        expected_host = urlsplit(self.feed_url).hostname
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        pages_scanned = 0
        filtered_total = 0

        with httpx.Client(
            headers={**AXPO_HEADERS, "Referer": self.base_url},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            for page_number in range(1, self.max_pages + 1):
                response = client.get(
                    self.feed_url,
                    params={
                        "country": AXPO_SWITZERLAND_COUNTRY,
                        "page": page_number,
                    },
                )
                response.raise_for_status()
                page_records, page_item_count = parse_feed_payload(
                    response.json(),
                    page_number=page_number,
                    expected_host=expected_host,
                )
                pages_scanned = page_number
                filtered_total += page_item_count

                for record in page_records:
                    job_id = record["id"]
                    if job_id in seen_ids:
                        raise AxpoSwitzerlandParseError(
                            "Axpo Teamtailor feed contains duplicate vacancy IDs"
                        )
                    seen_ids.add(job_id)
                    records.append(record)

                if filtered_total > self.max_jobs:
                    raise AxpoSwitzerlandParseError(
                        f"Axpo exposes more than the configured limit of "
                        f"{self.max_jobs} Swiss vacancies"
                    )
                if page_item_count < AXPO_TEAMTAILOR_PAGE_SIZE:
                    break
            else:
                raise AxpoSwitzerlandParseError(
                    "Axpo Teamtailor feed did not end within the configured "
                    f"limit of {self.max_pages} pages"
                )

        return records, pages_scanned, filtered_total

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        public_url = optional_text(record.get("url"))
        raw = dict(record)
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=optional_text(record.get("company")) or "Axpo Group",
            location=optional_text(record.get("location")),
            url=public_url,
            apply_url=(f"{public_url.rstrip('/')}/applications/new" if public_url else None),
            posted_at=optional_text(record.get("posted_at")),
            employment_type=optional_text(record.get("employment_type")),
            description=optional_multiline_text(record.get("description")),
            raw=raw,
        )


def parse_feed_payload(
    payload: Any,
    *,
    page_number: int,
    expected_host: str | None,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise AxpoSwitzerlandParseError("Axpo Teamtailor response is not a JSON Feed object")
    version = optional_text(payload.get("version"))
    items = payload.get("items")
    if (
        not version
        or not version.startswith(JSON_FEED_VERSION_PREFIX)
        or not isinstance(items, list)
    ):
        raise AxpoSwitzerlandParseError("Axpo Teamtailor response is missing its JSON Feed catalog")

    records: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise AxpoSwitzerlandParseError("Axpo Teamtailor feed contains an invalid vacancy")
        schema = item.get("_jobposting")
        if not isinstance(schema, dict) or schema.get("@type") != "JobPosting":
            raise AxpoSwitzerlandParseError(
                "Axpo Teamtailor vacancy is missing its JobPosting data"
            )

        identifier = schema.get("identifier")
        organization = schema.get("hiringOrganization")
        job_id = optional_text(identifier.get("value")) if isinstance(identifier, dict) else None
        company = (
            optional_text(organization.get("name")) if isinstance(organization, dict) else None
        )
        title = optional_text(item.get("title"))
        schema_title = optional_text(schema.get("title"))
        public_url = optional_text(item.get("url"))
        url_job_id = extract_job_id(public_url, expected_host=expected_host)
        posted_at = optional_text(item.get("date_published")) or optional_text(
            schema.get("datePosted")
        )
        description_html = optional_text(item.get("content_html")) or optional_text(
            schema.get("description")
        )
        if (
            not optional_text(item.get("id"))
            or not job_id
            or not company
            or not title
            or not schema_title
            or title != schema_title
            or url_job_id != job_id
            or not posted_at
            or not description_html
        ):
            raise AxpoSwitzerlandParseError("Axpo Teamtailor feed contains an incomplete vacancy")

        location = extract_swiss_locations(schema)
        if location is None:
            continue

        records.append(
            {
                "id": job_id,
                "feed_id": optional_text(item.get("id")),
                "title": title,
                "company": company,
                "location": location,
                "url": public_url,
                "posted_at": posted_at,
                "employment_type": extract_employment_type(schema),
                "description": html_to_text(description_html),
                "page_number": page_number,
                "schema": schema,
            }
        )
    return records, len(items)


def extract_job_id(value: Any, *, expected_host: str | None) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname != expected_host:
        return None
    match = JOB_PATH_PATTERN.search(parsed.path)
    return match.group(1) if match else None


def extract_swiss_locations(schema: dict[str, Any]) -> str | None:
    raw_locations = schema.get("jobLocation")
    if raw_locations is None:
        return None
    locations = raw_locations if isinstance(raw_locations, list) else [raw_locations]
    if not locations:
        return None
    values: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            return None
        address = location.get("address")
        if not isinstance(address, dict):
            return None
        country_code = optional_text(address.get("addressCountry"))
        locality = optional_text(address.get("addressLocality"))
        if not country_code:
            return None
        if country_code != AXPO_SWITZERLAND_COUNTRY_CODE:
            raise AxpoSwitzerlandParseError(
                "Axpo Teamtailor vacancy is not exclusively located in Switzerland"
            )
        values.append(locality or AXPO_SWITZERLAND_COUNTRY)

    unique = list(dict.fromkeys(values))
    return ", ".join(unique) if unique else None


def extract_employment_type(schema: dict[str, Any]) -> str | None:
    raw_value = schema.get("employmentType")
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    normalized = [
        text.replace("_", " ").title() for value in values if (text := optional_text(value))
    ]
    return ", ".join(dict.fromkeys(normalized)) if normalized else None


def deduplicate_axpo_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text)) or ""


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
