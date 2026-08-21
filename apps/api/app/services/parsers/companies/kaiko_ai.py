from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

KAIKO_AI_JOBS_URL = "https://jobs.kaiko.ai/jobs?location=Z%C3%BCrich"
KAIKO_AI_FEED_URL = "https://jobs.kaiko.ai/jobs.json?location=Z%C3%BCrich"
KAIKO_AI_HEADERS = {
    "Accept": "application/feed+json,application/json;q=0.9,text/html;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "kaiko.ai"
EXPECTED_LOCATION = "Zürich, Switzerland"
JSON_FEED_VERSION = "https://jsonfeed.org/version/1.1"
JOBS_HOME_URL = "https://jobs.kaiko.ai/jobs"
JOBS_FEED_DISCOVERY_URL = "https://jobs.kaiko.ai/jobs.json"
JOB_PATH_PATTERN = re.compile(r"^/jobs/(\d+)-([a-z0-9]+(?:-[a-z0-9]+)*)/?$")
APPLICATION_PATH_PATTERN = re.compile(
    r"^/jobs/(\d+)-([a-z0-9]+(?:-[a-z0-9]+)*)/applications/new/?$"
)
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class KaikoAiParseError(DirectCompanyRequestError):
    pass


class KaikoAiJobsParser:
    """Collect kaiko.ai's complete Teamtailor Zürich vacancy feed."""

    parser_id = "kaiko_ai"

    def __init__(
        self,
        *,
        base_url: str = KAIKO_AI_JOBS_URL,
        feed_url: str = KAIKO_AI_FEED_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.feed_url = feed_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**KAIKO_AI_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.feed_url)
                response.raise_for_status()
                records = parse_feed_payload(
                    response.json(),
                    page_url=str(response.url),
                    expected_url=self.feed_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except KaikoAiParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("kaiko.ai vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("kaiko.ai vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_kaiko_ai_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} kaiko.ai Zürich vacancies from the complete "
                "official Teamtailor JSON Feed"
            ),
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, KaikoAiParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_feed_payload(
    payload: Any,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url) or not is_kaiko_zurich_feed_url(expected_url):
        raise KaikoAiParseError("kaiko.ai feed returned unexpected content")
    if not isinstance(payload, dict):
        raise KaikoAiParseError("kaiko.ai feed payload is invalid")

    items = payload.get("items")
    if (
        payload.get("version") != JSON_FEED_VERSION
        or payload.get("title") != EXPECTED_COMPANY
        or payload.get("home_page_url") != JOBS_HOME_URL
        or payload.get("feed_url") != JOBS_FEED_DISCOVERY_URL
        or not isinstance(items, list)
    ):
        raise KaikoAiParseError("kaiko.ai feed has an invalid identity")
    if len(items) > max_jobs:
        raise KaikoAiParseError(
            f"kaiko.ai exposes {len(items)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_feed_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise KaikoAiParseError("kaiko.ai feed contains an invalid vacancy")
        feed_id = optional_text(item.get("id"))
        title = optional_text(item.get("title"))
        public_url = canonical_job_url(item.get("url"))
        job_id = extract_job_id(public_url)
        schema = item.get("_jobposting")
        schema = schema if isinstance(schema, dict) else {}
        schema_job_id = extract_schema_job_id(schema)
        company = extract_company(schema)
        locations = extract_schema_locations(schema)
        description = html_to_text(optional_text(schema.get("description")) or "")
        posted_at = optional_text(schema.get("datePosted"))
        date_published = optional_text(item.get("date_published"))
        if (
            not feed_id
            or not UUID_PATTERN.fullmatch(feed_id)
            or not job_id
            or schema_job_id != job_id
            or not title
            or optional_text(schema.get("title")) != title
            or company != EXPECTED_COMPANY
            or not has_zurich_location(locations)
            or not description
            or not posted_at
            or date_published != posted_at
            or optional_text(item.get("content_html")) != optional_text(schema.get("description"))
        ):
            raise KaikoAiParseError("kaiko.ai feed contains an incomplete or non-Zürich vacancy")
        if job_id in seen_ids or feed_id in seen_feed_ids:
            raise KaikoAiParseError("kaiko.ai feed contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        seen_feed_ids.add(feed_id)
        records.append(
            {
                "id": job_id,
                "feed_id": feed_id,
                "title": title,
                "company": EXPECTED_COMPANY,
                "location": EXPECTED_LOCATION,
                "all_locations": locations,
                "url": public_url,
                "posted_at": posted_at,
                "employment_type": normalize_employment_type(
                    schema.get("employmentType"),
                    title=title,
                ),
                "description": description,
                "schema": schema,
                "feed_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
) -> dict[str, Any]:
    if (
        not same_url(page_url, expected_url)
        or extract_job_id(page_url) != expected_job_id
        or canonical_job_url(expected_url) is None
    ):
        raise KaikoAiParseError("kaiko.ai detail page returned a different vacancy")

    page = Selector(page_html)
    public_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    schemas = list(extract_job_posting_schemas(page))
    if (
        public_urls != {expected_url}
        or len(schemas) != 1
        or extract_schema_job_id(schemas[0]) != expected_job_id
    ):
        raise KaikoAiParseError("kaiko.ai detail page has an invalid identity")

    schema = schemas[0]
    attributes = extract_detail_attributes(page)
    apply_urls = unique_attribute_values(
        page,
        "main[data-careersite--jobs--form-overlay-job-application-url-value]",
        "data-careersite--jobs--form-overlay-job-application-url-value",
    )
    apply_url = next(iter(apply_urls), None)
    locations = extract_schema_locations(schema)
    detail_locations = split_locations(attributes.get("locations"))
    if (
        optional_text(schema.get("title")) != expected_title
        or extract_company(schema) != EXPECTED_COMPANY
        or not has_zurich_location(locations)
        or "zürich" not in {value.casefold() for value in detail_locations}
        or not optional_text(attributes.get("remote status"))
        or len(apply_urls) != 1
        or not is_matching_application_url(
            apply_url,
            expected_url=expected_url,
            expected_job_id=expected_job_id,
        )
    ):
        raise KaikoAiParseError("kaiko.ai detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "apply_url": apply_url,
        "department": optional_text(attributes.get("department")),
        "remote_status": optional_text(attributes.get("remote status")),
        "employment_type": normalize_employment_type(
            schema.get("employmentType"),
            title=expected_title,
        ),
        "schema": schema,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    title = optional_text(record.get("title"))
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="kaiko_ai",
        title=title,
        company=EXPECTED_COMPANY,
        location=EXPECTED_LOCATION,
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(record.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority="Senior" if comparable_text(title).startswith("senior ") else None,
        description=optional_multiline_text(record.get("description")),
        raw=dict(record),
    )


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            if candidate.get("@type") == "JobPosting":
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.kaiko.ai"
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return text.rstrip("/")


def extract_job_id(value: Any) -> str | None:
    url = canonical_job_url(value)
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def extract_schema_job_id(schema: dict[str, Any]) -> str | None:
    identifier = schema.get("identifier")
    if not isinstance(identifier, dict) or identifier.get("name") != EXPECTED_COMPANY:
        return None
    return optional_text(identifier.get("value"))


def extract_company(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    return optional_text(organization.get("name")) if isinstance(organization, dict) else None


def extract_schema_locations(schema: dict[str, Any]) -> list[dict[str, str | None]]:
    value = schema.get("jobLocation")
    candidates = value if isinstance(value, list) else [value]
    locations: list[dict[str, str | None]] = []
    for candidate in candidates:
        address = candidate.get("address") if isinstance(candidate, dict) else None
        if not isinstance(address, dict):
            continue
        locations.append(
            {
                "locality": optional_text(address.get("addressLocality")),
                "country": optional_text(address.get("addressCountry")),
                "postal_code": optional_text(address.get("postalCode")),
            }
        )
    return locations


def has_zurich_location(locations: list[dict[str, str | None]]) -> bool:
    return any(
        comparable_text(location.get("country")) in {"ch", "che", "switzerland"}
        and comparable_text(location.get("locality")) in {"zürich", "zurich"}
        for location in locations
    )


def extract_detail_attributes(page: Selector) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for term, value in zip(page.css("section dl dt"), page.css("section dl dd"), strict=False):
        key = selector_text(term)
        item = selector_text(value)
        if key and item:
            attributes[key.casefold()] = item
    return attributes


def split_locations(value: Any) -> list[str]:
    text = optional_text(value)
    return [item.strip() for item in text.split(",") if item.strip()] if text else []


def is_matching_application_url(
    value: Any,
    *,
    expected_url: str,
    expected_job_id: str,
) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = APPLICATION_PATH_PATTERN.fullmatch(parts.path)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.kaiko.ai"
        and match is not None
        and match.group(1) == expected_job_id
        and text.rstrip("/").removesuffix("/applications/new") == expected_url.rstrip("/")
        and not parts.query
        and not parts.fragment
    )


def is_kaiko_zurich_feed_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.kaiko.ai"
        and parts.path == "/jobs.json"
        and parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
        == {"location": ["Zürich"]}
        and not parts.fragment
    )


def normalize_employment_type(value: Any, *, title: Any = None) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "INTERN": "Internship",
        "TEMPORARY": "Temporary",
    }
    normalized: list[str] = []
    for item in values:
        text = optional_text(item)
        if text:
            label = labels.get(text.upper(), text.replace("_", " ").title())
            if label not in normalized:
                normalized.append(label)
    if normalized:
        return ", ".join(normalized)
    return "Freelance" if "freelance" in comparable_text(title) else None


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == "https"
        and actual.scheme == target.scheme
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and parse_qs(actual.query, keep_blank_values=True)
        == parse_qs(target.query, keep_blank_values=True)
        and not actual.fragment
    )


def deduplicate_kaiko_ai_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any) -> str | None:
    return optional_text(" ".join(selector.css("::text").getall()))


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f'{css}::attr("{attribute}")').getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    decoded = html.unescape(value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", decoded)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = html.unescape(text).replace("\xa0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip() or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None
