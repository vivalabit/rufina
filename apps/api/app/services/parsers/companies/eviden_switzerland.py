from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

EVIDEN_SWITZERLAND_JOBS_BASE_URL = "https://eviden.com/careers/?country=CH"
EVIDEN_CAREERS_HOST = "eviden.com"
EVIDEN_JOBS_HOST = "jobs.atos.net"
EVIDEN_COUNTRY_CODE = "CH"
EVIDEN_BRAND_NAME = "Eviden"
EVIDEN_DETAIL_ORGANIZATION = "Atos"
EVIDEN_HEADERS = {
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
CATALOG_SCRIPT_PATTERN = re.compile(
    r"window\[['\"](?P<key>atosjobs_[^'\"]+)['\"]\]\s*=\s*"
    r"(?P<payload>\{.*?\});\s*</script>",
    re.DOTALL,
)
HTML_ATTRIBUTE_PATTERN = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(['\"])(?P<value>.*?)\2",
    re.DOTALL,
)
JOB_PATH_PATTERN = re.compile(r"^/job/[^/]+/(?P<id>\d+)/?$", re.IGNORECASE)
APPLY_PATH_PATTERN = re.compile(r"^/talentcommunity/apply/(?P<id>\d+)/?$", re.IGNORECASE)


class EvidenSwitzerlandParseError(DirectCompanyRequestError):
    pass


class EvidenSwitzerlandJobsParser:
    """Collect the complete Eviden catalog snapshot and retain Swiss vacancies."""

    parser_id = "eviden_switzerland"

    def __init__(
        self,
        *,
        base_url: str = EVIDEN_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_catalog_records: int = 2_000,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_catalog_records = max(1, max_catalog_records)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            validate_base_url(self.base_url)
            with httpx.Client(
                headers={**EVIDEN_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url, headers={"Accept": "text/html"})
                response.raise_for_status()
                records, total = parse_catalog_html(
                    response.text,
                    max_catalog_records=self.max_catalog_records,
                )
                swiss_records = swiss_catalog_records(records)
                self.enrich_records(client, swiss_records)
        except EvidenSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Eviden Switzerland vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Eviden Switzerland vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in swiss_records]
        if request.deduplicate:
            jobs = deduplicate_eviden_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Eviden Switzerland vacancies "
                f"from {total} global Eviden records in one catalog snapshot "
                f"with {len(swiss_records)} detail requests"
            ),
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            response = client.get(record["listing_url"], headers={"Accept": "text/html"})
            response.raise_for_status()
            detail = parse_detail_html(
                response.text,
                page_url=str(response.url),
                expected_posting_id=record["posting_id"],
                expected_title=record["title"],
                expected_date=record["posted_at"],
            )
            return record, detail

        with ThreadPoolExecutor(max_workers=self.detail_workers) as executor:
            futures = [executor.submit(fetch, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                record["detail"] = detail


def validate_base_url(value: str) -> None:
    parts = urlsplit(value)
    query = parse_qs(parts.query)
    if (
        parts.scheme != "https"
        or parts.hostname != EVIDEN_CAREERS_HOST
        or parts.path.rstrip("/") != "/careers"
        or query.get("country") != [EVIDEN_COUNTRY_CODE]
    ):
        raise EvidenSwitzerlandParseError(
            "Eviden Switzerland base URL must target the official CH careers filter"
        )


def parse_catalog_html(
    page_html: str,
    *,
    max_catalog_records: int,
) -> tuple[list[dict[str, Any]], int]:
    containers: list[dict[str, str]] = []
    for match in re.finditer(r"<div\b(?P<attrs>[^>]*)>", page_html, re.IGNORECASE):
        attributes = {
            item.group("name"): html.unescape(item.group("value"))
            for item in HTML_ATTRIBUTE_PATTERN.finditer(match.group("attrs"))
        }
        if "atosjobs" in attributes.get("class", "").split():
            containers.append(attributes)
    scripts = list(CATALOG_SCRIPT_PATTERN.finditer(page_html))
    if len(containers) != 1 or len(scripts) != 1:
        raise EvidenSwitzerlandParseError(
            "Eviden careers page must expose exactly one atomic jobs catalog"
        )

    container = containers[0]
    script = scripts[0]
    if container.get("id") != script.group("key"):
        raise EvidenSwitzerlandParseError(
            "Eviden careers catalog container and payload do not match"
        )
    payload = json.loads(script.group("payload"))
    if not isinstance(payload, Mapping):
        raise EvidenSwitzerlandParseError("Eviden careers catalog is not an object")

    page = required_integer(payload, "page")
    limit = required_integer(payload, "limit")
    total = required_integer(payload, "total")
    pages = required_integer(payload, "pages")
    if min(page, limit, total, pages) < 0 or limit == 0 or page != 1:
        raise EvidenSwitzerlandParseError("Eviden careers catalog metadata is invalid")
    expected_pages = ceil(total / limit) if total else 0
    if pages != expected_pages:
        raise EvidenSwitzerlandParseError(
            "Eviden careers catalog page count does not match its declared total"
        )
    try:
        container_page = int(container["data-page"])
        container_pages = int(container["data-pages"])
    except (KeyError, ValueError) as exc:
        raise EvidenSwitzerlandParseError(
            "Eviden careers catalog container metadata is invalid"
        ) from exc
    if container_page != page or container_pages != pages:
        raise EvidenSwitzerlandParseError(
            "Eviden careers catalog container metadata is inconsistent"
        )
    if total > max_catalog_records:
        raise EvidenSwitzerlandParseError(
            f"Eviden exposes {total} catalog records, above the configured limit "
            f"of {max_catalog_records}"
        )

    raw_results = payload.get("results")
    support = payload.get("support")
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes)):
        raise EvidenSwitzerlandParseError("Eviden careers catalog results are invalid")
    if len(raw_results) != total:
        raise EvidenSwitzerlandParseError("Eviden careers catalog snapshot is incomplete")
    if not isinstance(support, Mapping):
        raise EvidenSwitzerlandParseError("Eviden careers support data is missing")

    cities = required_mapping(support, "city")
    locations = required_mapping(support, "locations")
    experiences = required_mapping(support, "exp")
    brands = required_mapping(support, "brand")
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_result in raw_results:
        if not isinstance(raw_result, Mapping):
            raise EvidenSwitzerlandParseError("Eviden careers catalog contains an invalid vacancy")
        job_id = required_text(raw_result, "id")
        title = required_text(raw_result, "title")
        posted_at = normalize_date(required_text(raw_result, "date"))
        listing_url = required_text(raw_result, "url")
        posting_id = extract_job_id(listing_url, expected_host=EVIDEN_JOBS_HOST)
        brand_id = required_text(raw_result, "brand")
        experience_id = required_text(raw_result, "exp")
        if job_id in seen_ids:
            raise EvidenSwitzerlandParseError(
                "Eviden careers catalog contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        if not posted_at or not posting_id:
            raise EvidenSwitzerlandParseError(
                "Eviden careers catalog contains an invalid vacancy URL or date"
            )

        brand = brands.get(brand_id)
        experience = experiences.get(experience_id)
        city_ids = locations.get(job_id)
        if (
            not isinstance(brand, Mapping)
            or required_text(brand, "name") != EVIDEN_BRAND_NAME
            or not isinstance(experience, Mapping)
            or not isinstance(city_ids, Sequence)
            or isinstance(city_ids, (str, bytes))
            or not city_ids
        ):
            raise EvidenSwitzerlandParseError("Eviden careers catalog support data is inconsistent")
        resolved_cities: list[dict[str, Any]] = []
        for city_id_value in city_ids:
            city_id = optional_text(city_id_value)
            city = cities.get(city_id or "")
            if not city_id or not isinstance(city, Mapping):
                raise EvidenSwitzerlandParseError(
                    "Eviden careers catalog references an unknown location"
                )
            if required_text(city, "city_id") != city_id:
                raise EvidenSwitzerlandParseError(
                    "Eviden careers catalog location identifiers do not match"
                )
            required_text(city, "city")
            required_text(city, "country_id")
            required_text(city, "country")
            resolved_cities.append(dict(city))

        records.append(
            {
                "id": job_id,
                "title": title,
                "posted_at": posted_at,
                "listing_url": listing_url,
                "posting_id": posting_id,
                "brand": EVIDEN_BRAND_NAME,
                "seniority": required_text(experience, "name"),
                "locations": resolved_cities,
                "raw_listing": dict(raw_result),
            }
        )
    return records, total


def swiss_catalog_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    swiss: list[dict[str, Any]] = []
    for record in records:
        swiss_locations = [
            location
            for location in record["locations"]
            if required_text(location, "country_id") == EVIDEN_COUNTRY_CODE
        ]
        if swiss_locations:
            normalized = dict(record)
            normalized["locations"] = swiss_locations
            normalized["location"] = format_locations(swiss_locations)
            swiss.append(normalized)
    return swiss


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_posting_id: str,
    expected_title: str,
    expected_date: str,
) -> dict[str, Any]:
    page = Selector(page_html)
    if not page.css('[itemtype="http://schema.org/JobPosting"]').get():
        raise EvidenSwitzerlandParseError("Eviden detail page is missing its JobPosting data")

    canonical_value = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    canonical_url = urljoin(page_url, canonical_value) if canonical_value else None
    canonical_id = extract_job_id(canonical_url, expected_host=EVIDEN_JOBS_HOST)
    title = property_text(page, "title")
    posted_at = normalize_date(property_attribute(page, "datePosted", "content"))
    organization = property_attribute(page, "hiringOrganization", "content")
    description_html = page.css(".jobdescription").get()
    description = html_to_text(description_html)
    apply_values = [
        urljoin(page_url, value)
        for value in page.css("a.dialogApplyBtn::attr(href)").getall()
        if optional_text(value)
    ]
    apply_urls = list(dict.fromkeys(apply_values))
    apply_url = apply_urls[0] if len(apply_urls) == 1 else None
    apply_id = extract_apply_id(apply_url, expected_host=EVIDEN_JOBS_HOST)
    addresses = [
        value
        for value in (
            property_attribute(page, "streetAddress", "content"),
            optional_text(page.css(".jobGeoLocation::text").get()),
        )
        if value
    ]
    if (
        not canonical_url
        or canonical_id != expected_posting_id
        or not apply_url
        or apply_id != expected_posting_id
        or title != expected_title
        or not posted_at
        or posted_at < expected_date
        or organization != EVIDEN_DETAIL_ORGANIZATION
        or not description
        or not any(is_swiss_address(value) for value in addresses)
    ):
        raise EvidenSwitzerlandParseError(
            "Eviden detail page does not match its Swiss catalog vacancy"
        )
    return {
        "canonical_url": canonical_url,
        "apply_url": apply_url,
        "title": title,
        "posted_at": posted_at,
        "organization": organization,
        "description": description,
        "detail_location": addresses[-1] if addresses else None,
    }


def normalize_job(record: Mapping[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    if not isinstance(detail, Mapping):
        raise EvidenSwitzerlandParseError("Eviden vacancy detail is missing")
    return ParsedJob(
        source="eviden_switzerland",
        title=required_text(record, "title"),
        company=EVIDEN_BRAND_NAME,
        location=required_text(record, "location"),
        url=required_text(detail, "canonical_url"),
        apply_url=required_text(detail, "apply_url"),
        posted_at=required_text(detail, "posted_at"),
        seniority=required_text(record, "seniority"),
        description=required_text(detail, "description"),
        raw=dict(record),
    )


def format_locations(locations: Sequence[Mapping[str, Any]]) -> str:
    values: list[str] = []
    for location in locations:
        parts = [required_text(location, "city")]
        if region := optional_text(location.get("region")):
            parts.append(region)
        parts.append(required_text(location, "country"))
        value = ", ".join(parts)
        if value not in values:
            values.append(value)
    return " / ".join(values)


def extract_job_id(value: Any, *, expected_host: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme != "https" or parts.hostname != expected_host:
        return None
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    return match.group("id") if match else None


def extract_apply_id(value: Any, *, expected_host: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme != "https" or parts.hostname != expected_host:
        return None
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    return match.group("id") if match else None


def deduplicate_eviden_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = extract_job_id(job.url, expected_host=EVIDEN_JOBS_HOST)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job)
    return unique


def is_swiss_address(value: str) -> bool:
    normalized = optional_text(value) or ""
    return bool(re.search(r"(?:,|\s)CH(?:\s|$)", normalized, re.IGNORECASE)) or (
        "switzerland" in normalized.casefold()
    )


def property_text(page: Selector, itemprop: str) -> str | None:
    values = [
        value
        for raw in page.css(f'[itemprop="{itemprop}"]::text').getall()
        if (value := optional_text(raw))
    ]
    return " ".join(dict.fromkeys(values)) or None


def property_attribute(page: Selector, itemprop: str, attribute: str) -> str | None:
    return optional_text(page.css(f'[itemprop="{itemprop}"]::attr({attribute})').get())


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    for date_format in ("%Y-%m-%d", "%b %d, %Y", "%a %b %d %H:%M:%S UTC %Y"):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
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
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None


def required_text(value: Mapping[str, Any], key: str) -> str:
    text = optional_text(value.get(key))
    if not text:
        raise EvidenSwitzerlandParseError(f"Eviden careers data is missing required field {key}")
    return text


def required_integer(value: Mapping[str, Any], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise EvidenSwitzerlandParseError(f"Eviden careers data has invalid integer field {key}")
    return result


def required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise EvidenSwitzerlandParseError(f"Eviden careers data is missing mapping field {key}")
    return result
