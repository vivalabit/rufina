from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

BALOISE_JOBS_BASE_URL = "https://www.baloise.com/de/CH/jobs.html"
BALOISE_JOBS_CATALOG_URL = (
    "https://www.baloise.com/baloise-com/jobs/de/CH/main/jobSearchWidget/jobSearchWidget.json"
)
BALOISE_HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "Referer": BALOISE_JOBS_BASE_URL,
}
TOTAL_PATTERN = re.compile(r"(\d[\d'.,]*)\s+Job", re.IGNORECASE)
JOB_ID_PATTERN = re.compile(
    r"/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
APPLY_ID_PATTERN = re.compile(
    r"/redirect/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/ats/?$",
    re.IGNORECASE,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class BaloiseParseError(DirectCompanyRequestError):
    pass


class BaloiseJobsParser:
    """Collect the complete Swiss catalog exposed by Baloise's job widget."""

    parser_id = "baloise"

    def __init__(
        self,
        *,
        base_url: str = BALOISE_JOBS_BASE_URL,
        catalog_url: str = BALOISE_JOBS_CATALOG_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 1000,
        detail_workers: int = 8,
        fetch_page: Callable[[str], ScraplingResponse] | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        # Scrapling's browser-like transport remains reliable with a modest
        # pool; higher fan-out causes incomplete concurrent response bodies.
        self.detail_workers = min(8, max(1, detail_workers))
        self.fetch_page = fetch_page or self._fetch_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        catalog_request_url = self.build_catalog_url()
        try:
            payload = self.fetch_page(catalog_request_url).json()
            records, declared_total = parse_catalog_payload(
                payload,
                catalog_url=catalog_request_url,
                listing_page_url=self.base_url,
                max_jobs=self.max_jobs,
            )
            self.enrich_records(records)
        except BaloiseParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError("Baloise vacancy request failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_baloise_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Baloise vacancies from {declared_total} Swiss catalog records"
            ),
        )

    def _fetch_with_scrapling(self, url: str) -> ScraplingResponse:
        response = Fetcher.get(
            url,
            headers={**BALOISE_HEADERS, "Referer": self.base_url},
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        status = int(getattr(response, "status", 0) or 0)
        if status >= 400:
            raise BaloiseParseError(f"Baloise returned HTTP {status}")
        return response

    def build_catalog_url(self) -> str:
        parts = urlsplit(self.catalog_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(
            {
                "displayLimit": str(self.max_jobs),
                "editMode": "false",
                "query-str": "",
                "search-widget-radius-select-country": "CHE",
            }
        )
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    def enrich_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                detail_page = self.fetch_page(record["url"])
                return record, parse_detail_page(
                    detail_page,
                    page_url=record["url"],
                    expected_job_id=record["id"],
                )
            # A single external Helvetia detail page must not discard the
            # complete Baloise catalog record returned by the atomic API.
            except Exception as exc:  # noqa: BLE001
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        public_url = optional_text(record.get("url"))
        raw = dict(record)
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(detail.get("company")) or "Baloise",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=optional_text(detail.get("employment_type")),
            description=optional_multiline_text(detail.get("description")),
            raw=raw,
        )


def parse_catalog_payload(
    payload: Any,
    *,
    catalog_url: str,
    listing_page_url: str,
    max_jobs: int,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise BaloiseParseError("Baloise catalog response must be an object")
    declared_total = extract_declared_total(payload.get("text"))
    results = payload.get("results")
    if not isinstance(results, list):
        raise BaloiseParseError("Baloise catalog response is missing result pages")
    if declared_total > max_jobs:
        raise BaloiseParseError(
            f"Baloise exposes {declared_total} vacancies, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for page_index, result_page in enumerate(results, start=1):
        if not isinstance(result_page, dict) or not isinstance(result_page.get("items"), list):
            raise BaloiseParseError("Baloise catalog contains an invalid result page")
        for item in result_page["items"]:
            if not isinstance(item, dict):
                raise BaloiseParseError("Baloise catalog contains an invalid vacancy")
            title = optional_text(item.get("title"))
            location = optional_text(item.get("subTitle"))
            public_url = optional_text(item.get("href"))
            job_id = extract_job_id(public_url)
            if not title or not location or not public_url or not job_id:
                raise BaloiseParseError("Baloise catalog contains an incomplete vacancy")
            if not is_swiss_location(location):
                raise BaloiseParseError(
                    f"Baloise country filter returned a non-Swiss vacancy: {location}"
                )
            if urlsplit(public_url).hostname != "jobs.helvetia.com":
                raise BaloiseParseError("Baloise catalog returned an unexpected job host")
            if job_id in seen_ids:
                raise BaloiseParseError("Baloise catalog contains duplicate vacancy IDs")
            seen_ids.add(job_id)
            record = dict(item)
            record.update(
                {
                    "id": job_id,
                    "title": title,
                    "location": location,
                    "url": public_url,
                    "catalog_page": page_index,
                    "catalog_url": catalog_url,
                    "listing_page_url": listing_page_url,
                    "total_available": declared_total,
                }
            )
            records.append(record)

    if len(records) != declared_total:
        raise BaloiseParseError(
            f"Baloise returned {len(records)} vacancies but declared {declared_total}"
        )
    return records, declared_total


def parse_detail_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    schema = next(extract_job_posting_schemas(page), {})
    if not schema:
        raw_body = getattr(page, "body", b"")
        raw_html = (
            raw_body.decode("utf-8", "replace")
            if isinstance(raw_body, bytes)
            else str(raw_body or "")
        )
        schema = next(extract_job_posting_schemas_from_html(raw_html), {})
    apply_url = optional_text(page.css("a[href*='/redirect/'][href*='/ats/']::attr(href)").get())
    title = optional_text(schema.get("title"))
    description_html = optional_text(schema.get("description"))
    public_job_id = extract_job_id(page_url)
    apply_job_id = extract_apply_job_id(apply_url)
    if not schema or not title or not description_html or not apply_url:
        raise BaloiseParseError("Baloise detail page is missing required vacancy data")
    if expected_job_id and (public_job_id != expected_job_id or apply_job_id != expected_job_id):
        raise BaloiseParseError("Baloise detail page returned a different vacancy")

    return {
        "title": title,
        "company": extract_hiring_organization(schema),
        "location": extract_schema_location(schema),
        "apply_url": apply_url,
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "employment_type": normalize_employment_type(schema.get("employmentType")),
        "description": html_to_text(description_html),
        "industry": optional_text(schema.get("industry")),
        "schema": schema,
    }


def extract_job_posting_schemas(page: ScraplingResponse) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
            continue
        for candidate in walk_json(payload):
            job_type = candidate.get("@type")
            if job_type == "JobPosting" or (
                isinstance(job_type, list) and "JobPosting" in job_type
            ):
                yield candidate


def extract_job_posting_schemas_from_html(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        for candidate in walk_json(payload):
            job_type = candidate.get("@type")
            if job_type == "JobPosting" or (
                isinstance(job_type, list) and "JobPosting" in job_type
            ):
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_declared_total(value: Any) -> int:
    values = value if isinstance(value, list) else [value]
    for candidate in values:
        text = optional_text(candidate)
        if text and (match := TOTAL_PATTERN.search(text)):
            return int(re.sub(r"\D", "", match.group(1)))
    raise BaloiseParseError("Baloise catalog response is missing its result count")


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := JOB_ID_PATTERN.search(urlsplit(text).path)):
        return None
    return match.group(1).lower()


def extract_apply_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := APPLY_ID_PATTERN.search(urlsplit(text).path)):
        return None
    return match.group(1).lower()


def is_swiss_location(value: str | None) -> bool:
    return bool(value and re.match(r"^Schweiz(?:\s*,|$)", value, re.IGNORECASE))


def extract_hiring_organization(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    if isinstance(organization, dict):
        return optional_text(organization.get("name"))
    return optional_text(organization)


def extract_schema_location(schema: dict[str, Any]) -> str | None:
    location = schema.get("jobLocation")
    if isinstance(location, Sequence) and not isinstance(location, (str, bytes)):
        names = [name for item in location if (name := extract_place_name(item))]
        return ", ".join(dict.fromkeys(names)) or None
    return extract_place_name(location)


def extract_place_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return optional_text(value)
    address = value.get("address")
    address = address if isinstance(address, dict) else {}
    country = optional_text(address.get("addressCountry"))
    locality = optional_text(address.get("addressLocality"))
    region = optional_text(address.get("addressRegion"))
    values = [item for item in (country, locality, region) if item]
    return ", ".join(dict.fromkeys(values)) or optional_text(value.get("name"))


def normalize_employment_type(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [text for item in value if (text := normalize_employment_type(item))]
        return ", ".join(dict.fromkeys(values)) or None
    text = optional_text(value)
    if not text:
        return None
    return text.replace("_", " ").lower().capitalize()


def deduplicate_baloise_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<style(?:\s[^>]*)?>.*?</style>", "", value)
    text = re.sub(r"(?is)<script(?:\s[^>]*)?>.*?</script>", "", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = (
        str(value)
        .replace("\u200b", "")
        .replace("\u202f", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
