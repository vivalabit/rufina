from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BACHEM_JOBS_BASE_URL = (
    "https://careers.bachem.com/search/?createNewAlert=false&q="
    "&optionsFacetsDD_department=&optionsFacetsDD_shifttype="
    "&optionsFacetsDD_location=&optionsFacetsDD_country=CH"
    "&optionsFacetsDD_customfield1="
)
BACHEM_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
RESULT_RANGE_PATTERN = re.compile(
    r"Results\s+(\d[\d,]*)\s*(?:to|[–-])\s*(\d[\d,]*)\s+of\s+(\d[\d,]*)",
    re.IGNORECASE,
)
JOB_PATH_PATTERN = re.compile(r"^/job/.+/(\d+)/?$", re.IGNORECASE)
APPLY_PATH_PATTERN = re.compile(r"^/talentcommunity/apply/(\d+)/?$", re.IGNORECASE)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")
SWISS_LOCATION_PATTERN = re.compile(r"(?:^|,\s*)CH(?:,|$)", re.IGNORECASE)
EXPECTED_COMPANY = "Bachem AG"


class BachemParseError(DirectCompanyRequestError):
    pass


class BachemJobsParser:
    """Collect the complete Switzerland catalog from Bachem SuccessFactors."""

    parser_id = "bachem"

    def __init__(
        self,
        *,
        base_url: str = BACHEM_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**BACHEM_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except BachemParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Bachem vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Bachem vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bachem_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Bachem Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} page {request_label}"
            ),
        )

    def listing_url(self, *, offset: int) -> str:
        params = {
            "createNewAlert": "false",
            "q": "",
            "optionsFacetsDD_department": "",
            "optionsFacetsDD_shifttype": "",
            "optionsFacetsDD_location": "",
            "optionsFacetsDD_country": "CH",
            "optionsFacetsDD_customfield1": "",
            "locale": "en_US",
            "sortColumn": "referencedate",
            "sortDirection": "desc",
        }
        if offset:
            params["startrow"] = str(offset)
        return str(httpx.URL(self.base_url).copy_merge_params(params))

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        response = client.get(self.listing_url(offset=offset))
        response.raise_for_status()
        records, metadata = parse_listing_html(response.text, page_url=str(response.url))
        if metadata["start"] != offset + 1:
            raise BachemParseError("Bachem pagination returned an unexpected result range")
        return records, metadata

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, first_metadata = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            total = first_metadata["total"]
            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise BachemParseError("Bachem catalog changed its result count during pagination")
            if page_size <= 0:
                raise BachemParseError("Bachem listing is missing its page size")

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise BachemParseError(
                    f"Bachem exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [first_records]
            for offset in range(page_size, total, page_size):
                records, metadata = self.fetch_listing_page(client, offset=offset)
                pages_fetched += 1
                if metadata["total"] != expected_total:
                    raise BachemParseError(
                        "Bachem catalog changed its result count during pagination"
                    )
                page_results.append(records)

            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise BachemParseError("Bachem catalog changed while pages were collected")

        raise BachemParseError(
            f"Bachem returned {len(records_by_id)} unique vacancies but declared "
            f"{expected_total or 0}"
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
                    expected_location=record["location"],
                )
            except (httpx.HTTPError, BachemParseError, ValueError) as exc:
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
        job_id = optional_text(record.get("id"))
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url")) or build_apply_url(self.base_url, job_id)
            ),
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
            ),
            employment_type=format_employment_type(
                record.get("employment_type"),
                extract_workload(record.get("title")),
            ),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    page = Selector(page_html)
    table = page.css("table#searchresults")
    if not table.get():
        raise BachemParseError("Bachem listing page is missing its search results")

    range_sources = (
        page.css(".paginationLabel").get(),
        table.css("::attr(aria-label)").get(),
    )
    match = next(
        (
            range_match
            for value in range_sources
            if value and (range_match := RESULT_RANGE_PATTERN.search(html_to_text(value) or ""))
        ),
        None,
    )
    if not match:
        raise BachemParseError("Bachem listing page is missing its result range")
    start, end, total = (int(value.replace(",", "")) for value in match.groups())

    page_host = urlsplit(page_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in page.css("table#searchresults tbody tr.data-row"):
        path = optional_text(row.css("a.jobTitle-link::attr(href)").get())
        title = optional_text(row.css("a.jobTitle-link::text").get())
        category = selector_text(row, "td.colDepartment span.jobDepartment")
        employment_type = selector_text(row, "td.colShifttype span.jobShifttype")
        location = selector_text(row, "td.colLocation span.jobLocation")
        posted_at = normalize_date(selector_text(row, "td.colDate span.jobDate"))
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        if (
            not job_id
            or not title
            or not category
            or not employment_type
            or not location
            or not is_swiss_location(location)
            or not posted_at
            or not is_job_url(detail_url, expected_host=page_host)
        ):
            raise BachemParseError("Bachem listing contains an incomplete or non-Swiss vacancy")
        if job_id in seen_ids:
            raise BachemParseError("Bachem listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "category": category,
                "employment_type": employment_type,
                "location": location,
                "posted_at": posted_at,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    expected_count = end - start + 1
    if len(records) != expected_count:
        raise BachemParseError(
            f"Bachem listed {len(records)} vacancies for a range of {expected_count} records"
        )
    return records, {"start": start, "end": end, "total": total}


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_location: str,
) -> dict[str, Any]:
    if not same_job_url(page_url, expected_url):
        raise BachemParseError("Bachem detail page returned a different vacancy")

    page = Selector(page_html)
    if not page.css('[itemtype="http://schema.org/JobPosting"]').get():
        raise BachemParseError("Bachem detail page is missing its JobPosting data")

    title = property_text(page, "title") or optional_text(
        page.css('[itemprop="title"]::text').get()
    )
    company = property_attribute(page, "hiringOrganization", "content")
    description_html = page.css('[itemprop="description"]').get()
    description = html_to_text(description_html) if description_html else None
    location = extract_detail_location(page)
    listing_location = optional_text(expected_location)
    apply_urls = {
        urljoin(page_url, str(value))
        for value in page.css("a.dialogApplyBtn::attr(href)").getall()
        if is_apply_url(
            urljoin(page_url, str(value)),
            expected_host=urlsplit(page_url).netloc.casefold(),
            expected_job_id=expected_job_id,
        )
    }
    apply_url = next(iter(apply_urls)) if len(apply_urls) == 1 else None
    if (
        not title
        or company != EXPECTED_COMPANY
        or not description
        or not location
        or not listing_location
        or not same_swiss_location(location, listing_location)
        or not apply_url
    ):
        raise BachemParseError("Bachem detail page contains an incomplete or non-Swiss vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": company,
        "location": listing_location,
        "apply_url": apply_url,
        "posted_at": normalize_date(property_attribute(page, "datePosted", "content")),
        "valid_through": normalize_date(property_attribute(page, "validThrough", "content")),
        "description": description,
    }


def property_text(page: Selector, property_id: str) -> str | None:
    values = [
        text
        for value in page.css(f'[data-careersite-propertyid="{property_id}"]::text').getall()
        if (text := optional_text(value))
    ]
    return " ".join(dict.fromkeys(values)) or None


def property_attribute(page: Selector, itemprop: str, attribute: str) -> str | None:
    return optional_text(page.css(f'[itemprop="{itemprop}"]::attr({attribute})').get())


def extract_detail_location(page: Selector) -> str | None:
    country = property_attribute(page, "addressCountry", "content")
    locality = property_attribute(page, "addressLocality", "content")
    region = property_attribute(page, "addressRegion", "content")
    postal_code = property_attribute(page, "postalCode", "content")
    if country != "CH" or not locality or not postal_code:
        return None
    return ", ".join(value for value in (locality, region, country, postal_code) if value)


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    for pattern in (JOB_PATH_PATTERN, APPLY_PATH_PATTERN):
        if match := pattern.fullmatch(path):
            return match.group(1)
    return None


def is_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and JOB_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.query
        and not parts.fragment
    )


def same_job_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual_parts = urlsplit(actual_text)
    expected_parts = urlsplit(expected_text)
    return (
        actual_parts.scheme == "https"
        and actual_parts.scheme == expected_parts.scheme
        and actual_parts.netloc.casefold() == expected_parts.netloc.casefold()
        and actual_parts.path.rstrip("/") == expected_parts.path.rstrip("/")
    )


def is_apply_url(value: Any, *, expected_host: str, expected_job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and match is not None
        and match.group(1) == expected_job_id
        and not parts.fragment
    )


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id:
        return None
    return urljoin(base_url, f"/talentcommunity/apply/{job_id}/?locale=en_US")


def is_swiss_location(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and SWISS_LOCATION_PATTERN.search(text))


def same_swiss_location(value: Any, expected: Any) -> bool:
    def identity(candidate: Any) -> tuple[str, str] | None:
        text = optional_text(candidate)
        if not text or not is_swiss_location(text):
            return None
        parts = [part.strip() for part in text.split(",")]
        try:
            country_index = next(
                index for index, part in enumerate(parts) if part.casefold() == "ch"
            )
        except StopIteration:
            return None
        if country_index < 1 or country_index + 1 >= len(parts):
            return None
        locality = parts[0].casefold()
        postal_code = parts[country_index + 1].casefold()
        return locality, postal_code

    actual_identity = identity(value)
    return actual_identity is not None and actual_identity == identity(expected)


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := WORKLOAD_PATTERN.search(text)):
        return None
    return optional_text(match.group(0))


def format_employment_type(employment_type: Any, workload: Any) -> str | None:
    values: list[str] = []
    for value in (employment_type, workload):
        text = optional_text(value)
        if text and text not in values:
            values.append(text)
    return " · ".join(values) or None


def deduplicate_bachem_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or extract_job_id(job.apply_url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


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
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


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
