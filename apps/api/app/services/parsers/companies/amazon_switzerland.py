from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from math import ceil
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AMAZON_SWITZERLAND_JOBS_BASE_URL = "https://www.amazon.jobs/content/en/locations/switzerland/zurich"
AMAZON_JOBS_API_URL = "https://www.amazon.jobs/en/search.json"
AMAZON_RESULTS_PER_PAGE = 100
AMAZON_SWITZERLAND_COUNTRY_CODE = "CHE"
AMAZON_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/en/jobs/(\d+)(?:/|$)", re.IGNORECASE)


class AmazonSwitzerlandParseError(DirectCompanyRequestError):
    pass


class AmazonSwitzerlandJobsParser:
    """Collect Amazon vacancies whose official country facet is Switzerland."""

    parser_id = "amazon_switzerland"

    def __init__(
        self,
        *,
        base_url: str = AMAZON_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = AMAZON_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**AMAZON_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
        except AmazonSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Amazon Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Amazon Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_amazon_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Amazon Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} API page requests"
            ),
        )

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.get(
            self.api_url,
            params={
                "country": AMAZON_SWITZERLAND_COUNTRY_CODE,
                "offset": offset,
                "result_limit": AMAZON_RESULTS_PER_PAGE,
                "sort": "relevant",
            },
        )
        response.raise_for_status()
        total, records = parse_listing_payload(response.json())
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        pages_fetched = 0
        last_total = 0
        last_unique = 0

        for catalog_pass in range(self.max_catalog_passes):
            initial_page = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            expected_total = initial_page[1]
            last_total = expected_total
            required_pages = max(1, ceil(expected_total / AMAZON_RESULTS_PER_PAGE))
            if required_pages > self.max_pages:
                raise AmazonSwitzerlandParseError(
                    f"Amazon Switzerland exposes {required_pages} pages, above "
                    f"the configured limit of {self.max_pages}"
                )

            page_results = [initial_page]
            for offset in range(
                AMAZON_RESULTS_PER_PAGE,
                expected_total,
                AMAZON_RESULTS_PER_PAGE,
            ):
                page_results.append(self.fetch_listing_page(client, offset=offset))
                pages_fetched += 1

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            pass_records = 0
            for offset, page_total, records in page_results:
                expected_count = min(
                    AMAZON_RESULTS_PER_PAGE,
                    max(0, expected_total - offset),
                )
                if page_total != expected_total or len(records) != expected_count:
                    catalog_changed = True
                    break
                pass_records += len(records)
                for record in records:
                    job_id = extract_job_id(record)
                    if not job_id:
                        catalog_changed = True
                        break
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)
                if catalog_changed:
                    break

            last_unique = len(records_by_id)
            if catalog_changed or pass_records != expected_total:
                continue
            if last_unique == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total

        raise AmazonSwitzerlandParseError(
            f"Amazon Switzerland yielded only {last_unique} unique vacancies of "
            f"{last_total} after {self.max_catalog_passes} catalog passes"
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        job_id = extract_job_id(record)
        job_path = optional_text(record.get("job_path"))
        public_url = urljoin("https://www.amazon.jobs", job_path or "") or None
        sections = (
            ("Description", record.get("description")),
            ("Basic qualifications", record.get("basic_qualifications")),
            ("Preferred qualifications", record.get("preferred_qualifications")),
        )
        description = "\n\n".join(
            f"{heading}\n{text}"
            for heading, value in sections
            if (text := html_to_text(optional_text(value) or ""))
        )

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=optional_text(record.get("company_name")) or "Amazon",
            location=format_swiss_locations(record.get("swiss_locations")),
            url=public_url,
            apply_url=optional_text(record.get("url_next_step")) or public_url,
            posted_at=optional_text(record.get("posted_date")),
            employment_type=optional_text(record.get("job_schedule_type")),
            seniority=None,
            description=description or None,
            raw={**record, "normalized_job_id": job_id},
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise AmazonSwitzerlandParseError("Amazon jobs response must be an object")
    if payload.get("error") not in (None, ""):
        raise AmazonSwitzerlandParseError("Amazon jobs response contains an error")

    total = payload.get("hits")
    records = payload.get("jobs")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise AmazonSwitzerlandParseError("Amazon jobs response has an invalid total")
    if not isinstance(records, list) or len(records) > AMAZON_RESULTS_PER_PAGE:
        raise AmazonSwitzerlandParseError("Amazon jobs response has invalid vacancies")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            raise AmazonSwitzerlandParseError("Amazon jobs response contains an invalid vacancy")
        job_id = extract_job_id(item)
        swiss_locations = parse_swiss_locations(item.get("locations"))
        if (
            not job_id
            or job_id in seen_ids
            or not optional_text(item.get("title"))
            or not optional_text(item.get("description"))
            or optional_text(item.get("country_code")) != AMAZON_SWITZERLAND_COUNTRY_CODE
            or not swiss_locations
        ):
            raise AmazonSwitzerlandParseError(
                "Amazon jobs response contains an incomplete or non-Swiss vacancy"
            )
        seen_ids.add(job_id)
        normalized_item = dict(item)
        normalized_item["swiss_locations"] = swiss_locations
        normalized.append(normalized_item)
    return total, normalized


def parse_swiss_locations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AmazonSwitzerlandParseError("Amazon vacancy has invalid locations")
    locations: list[dict[str, Any]] = []
    for item in value:
        try:
            location = json.loads(item) if isinstance(item, str) else item
        except json.JSONDecodeError as exc:
            raise AmazonSwitzerlandParseError("Amazon vacancy has an invalid location") from exc
        if not isinstance(location, dict):
            raise AmazonSwitzerlandParseError("Amazon vacancy has an invalid location")
        if optional_text(location.get("normalizedCountryCode")) == (
            AMAZON_SWITZERLAND_COUNTRY_CODE
        ):
            locations.append(location)
    return locations


def format_swiss_locations(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    labels: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        parts: list[str] = []
        for part in (
            item.get("normalizedCityName") or item.get("city"),
            item.get("region") or item.get("normalizedStateName"),
            item.get("normalizedCountryName") or "Switzerland",
        ):
            text = optional_text(part)
            if text and text not in parts:
                parts.append(text)
        label = ", ".join(parts)
        if label and label not in labels:
            labels.append(label)
    return "; ".join(labels) or None


def extract_job_id(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    item_id = optional_text(record.get("id_icims"))
    job_path = optional_text(record.get("job_path"))
    path_match = JOB_PATH_PATTERN.match(urlsplit(job_path or "").path)
    path_id = path_match.group(1) if path_match else None
    if item_id and path_id and item_id == path_id and item_id.isdigit():
        return item_id
    return None


def deduplicate_amazon_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        match = JOB_PATH_PATTERN.match(urlsplit(job.url or "").path)
        key = match.group(1) if match else job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
