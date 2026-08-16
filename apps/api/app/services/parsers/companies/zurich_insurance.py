from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ZURICH_INSURANCE_JOBS_BASE_URL = (
    "https://www.careers.zurich.com/search/?createNewAlert=false&q="
    "&locationsearch=zurich&optionsFacetsDD_shifttype="
    "&optionsFacetsDD_department=&optionsFacetsDD_customfield3="
)
ZURICH_INSURANCE_COMPANY = "Zurich Insurance"
ZURICH_INSURANCE_SCHEMA_ORGANIZATION = "Zurich Insurance Company Ltd."
ZURICH_INSURANCE_HEADERS = {
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
JOB_PATH_PATTERN = re.compile(r"/job/.+/(\d+)/?$")
APPLY_PATH_PATTERN = re.compile(r"/talentcommunity/apply/(\d+)/?$")
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")


class ZurichInsuranceParseError(DirectCompanyRequestError):
    pass


class ZurichInsuranceJobsParser:
    """Collect Zurich Insurance vacancies from the Zürich SuccessFactors search."""

    parser_id = "zurich_insurance"

    def __init__(
        self,
        *,
        base_url: str = ZURICH_INSURANCE_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(20, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ZURICH_INSURANCE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total, catalog_passes = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except ZurichInsuranceParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Zurich Insurance vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Zurich Insurance vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_zurich_insurance_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Zurich Insurance vacancies from "
                f"{total} Zürich catalog records across {pages_fetched} page "
                f"{request_label} in {catalog_passes} catalog pass(es)"
            ),
        )

    def listing_url(self, *, offset: int) -> str:
        params = {"startrow": str(offset)} if offset else {}
        return str(httpx.URL(self.base_url).copy_merge_params(params))

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        response = client.get(self.listing_url(offset=offset))
        response.raise_for_status()
        records, metadata = parse_listing_html(
            response.text,
            page_url=str(response.url),
        )
        expected_start = offset + 1 if metadata["total"] else 0
        if metadata["start"] != expected_start:
            raise ZurichInsuranceParseError(
                "Zurich Insurance pagination returned an unexpected result range"
            )
        return records, metadata

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        last_unique_count = 0
        last_total = 0
        pages_fetched = 0

        # SuccessFactors offsets can shift while jobs are published. Repeat the
        # full catalog and union stable IDs until every declared row is present.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, first_metadata = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            total = first_metadata["total"]
            last_total = total
            if total == 0:
                return [], pages_fetched, 0, catalog_pass

            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if page_size <= 0:
                raise ZurichInsuranceParseError("Zurich Insurance listing is missing its page size")
            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise ZurichInsuranceParseError(
                    f"Zurich Insurance exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            page_results = [first_records]
            catalog_changed = False
            for offset in range(page_size, total, page_size):
                records, metadata = self.fetch_listing_page(client, offset=offset)
                pages_fetched += 1
                if metadata["total"] != total:
                    catalog_changed = True
                page_results.append(records)

            records_by_id: dict[str, dict[str, Any]] = {}
            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = total
                    if record["id"] in records_by_id:
                        catalog_changed = True
                    records_by_id.setdefault(record["id"], normalized)

            last_unique_count = len(records_by_id)
            if not catalog_changed and last_unique_count == total:
                return (
                    list(records_by_id.values()),
                    pages_fetched,
                    total,
                    catalog_pass,
                )

        raise ZurichInsuranceParseError(
            f"Zurich Insurance yielded {last_unique_count} unique vacancies of "
            f"{last_total} Zürich catalog records"
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
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, ZurichInsuranceParseError, ValueError) as exc:
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
        public_url = optional_text(detail.get("url")) or optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=ZURICH_INSURANCE_COMPANY,
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
            employment_type=(
                optional_text(detail.get("workload"))
                or workload_from_title(optional_text(record.get("title")))
            ),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    validate_listing_url(page_url)
    page = Selector(page_html)
    table = page.css("table#searchresults")
    if not table.get():
        empty_text = html_to_text(page.css("#noresults").get())
        if empty_text and re.search(
            r"\b0 most recent jobs\b",
            empty_text,
            re.IGNORECASE,
        ):
            return [], {"start": 0, "end": 0, "total": 0}
        raise ZurichInsuranceParseError(
            "Zurich Insurance listing page is missing its search results"
        )

    query_label = html_to_text(page.css(".securitySearchQuery").get())
    table_label = optional_text(table.css("::attr(aria-label)").get())
    if not any(
        value and re.search(r"\bzurich\b", value, re.IGNORECASE)
        for value in (query_label, table_label)
    ):
        raise ZurichInsuranceParseError("Zurich Insurance listing lost its Zürich search scope")

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
        raise ZurichInsuranceParseError("Zurich Insurance listing page is missing its result range")
    start, end, total = (int(value.replace(",", "")) for value in match.groups())

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in page.css("table#searchresults tbody tr.data-row"):
        path = optional_text(row.css("a.jobTitle-link::attr(href)").get())
        title = optional_text(row.css("a.jobTitle-link::text").get())
        location_html = row.css("td.colLocation span.jobLocation").get()
        department = optional_text(row.css("td.colDepartment span.jobDepartment::text").get())
        posted_at = optional_text(row.css("td.colDate span.jobDate::text").get())
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        location = normalize_listing_location(
            html_to_text(location_html) if location_html else None
        )
        if not job_id or not title or not location or not detail_url:
            raise ZurichInsuranceParseError(
                "Zurich Insurance listing contains an incomplete vacancy"
            )
        if not is_swiss_location(location):
            raise ZurichInsuranceParseError(
                f"Zurich Insurance Zürich search returned a non-Swiss vacancy: {location}"
            )
        if job_id in seen_ids:
            raise ZurichInsuranceParseError(
                "Zurich Insurance listing contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "department": department,
                "location": location,
                "posted_at": normalize_date(posted_at),
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    expected_count = end - start + 1
    if len(records) != expected_count:
        raise ZurichInsuranceParseError(
            f"Zurich Insurance listed {len(records)} vacancies for a range of "
            f"{expected_count} records"
        )
    return records, {"start": start, "end": end, "total": total}


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    if not page.css('[itemtype="http://schema.org/JobPosting"]').get():
        raise ZurichInsuranceParseError(
            "Zurich Insurance detail page is missing its JobPosting data"
        )

    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    canonical_id = extract_job_id(canonical)
    page_id = extract_job_id(page_url)
    title = property_text(page, "title")
    description_html = page.css('[itemprop="description"]').get()
    description = html_to_text(description_html) if description_html else None
    apply_path = optional_text(page.css("a.dialogApplyBtn::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    apply_id = extract_job_id(apply_url)
    company = property_attribute(page, "hiringOrganization", "content")
    locations = [
        location
        for value in page.css('[itemprop="streetAddress"]::attr(content)').getall()
        if (location := optional_text(value))
    ]
    swiss_locations = list(
        dict.fromkeys(location for location in locations if is_swiss_location(location))
    )
    detail_ids = {value for value in (canonical_id, page_id, apply_id) if value}
    if (
        not title
        or not description
        or not apply_url
        or not apply_id
        or not canonical
        or len(detail_ids) != 1
    ):
        raise ZurichInsuranceParseError(
            "Zurich Insurance detail page contains an incomplete vacancy"
        )
    if expected_job_id and detail_ids != {expected_job_id}:
        raise ZurichInsuranceParseError("Zurich Insurance detail page returned a different vacancy")
    if company != ZURICH_INSURANCE_SCHEMA_ORGANIZATION:
        raise ZurichInsuranceParseError(
            "Zurich Insurance detail page returned a different organization"
        )
    if not swiss_locations or not any(is_zurich_location(location) for location in swiss_locations):
        raise ZurichInsuranceParseError(
            "Zurich Insurance detail page returned no Swiss Zürich location"
        )

    return {
        "id": apply_id,
        "title": title,
        "company": company,
        "location": "; ".join(swiss_locations),
        "url": canonical,
        "apply_url": apply_url,
        "posted_at": normalize_date(property_attribute(page, "datePosted", "content")),
        "workload": workload_from_title(title),
        "description": description,
    }


def validate_listing_url(page_url: str) -> None:
    parts = urlsplit(page_url)
    params = parse_qs(parts.query, keep_blank_values=True)
    location_search = optional_text(params.get("locationsearch", [None])[0])
    if parts.path != "/search/" or not location_search:
        raise ZurichInsuranceParseError("Zurich Insurance listing returned an unexpected URL")
    if location_search.casefold() != "zurich":
        raise ZurichInsuranceParseError("Zurich Insurance listing lost its Zürich search filter")


def property_text(page: Selector, property_id: str) -> str | None:
    values = [
        text
        for value in page.css(f'[data-careersite-propertyid="{property_id}"]::text').getall()
        if (text := optional_text(value))
    ]
    return " ".join(dict.fromkeys(values)) or None


def property_attribute(page: Selector, itemprop: str, attribute: str) -> str | None:
    return optional_text(page.css(f'[itemprop="{itemprop}"]::attr({attribute})').get())


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    for pattern in (JOB_PATH_PATTERN, APPLY_PATH_PATTERN):
        if match := pattern.search(path):
            return match.group(1)
    return None


def is_swiss_location(location: str | None) -> bool:
    return bool(location and re.search(r"(?:,|\s)(?:CH|Switzerland)\s*$", location, re.IGNORECASE))


def is_zurich_location(location: str | None) -> bool:
    return bool(location and re.search(r"\bZ(?:ü|u|ue)rich\b", location, re.IGNORECASE))


def normalize_listing_location(location: str | None) -> str | None:
    text = optional_text(location)
    if not text:
        return None
    normalized = re.sub(
        r"\s*\+\d+\s+more(?:\.{3}|…)?\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return optional_text(normalized)


def workload_from_title(title: str | None) -> str | None:
    if not title or not (match := WORKLOAD_PATTERN.search(title)):
        return None
    workload = re.sub(r"\s+", "", match.group(0)).replace("–", "-")
    return workload


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id:
        return None
    return urljoin(base_url, f"/talentcommunity/apply/{job_id}/?locale=en_US")


def deduplicate_zurich_insurance_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    cleaned = re.sub(r"\s+(?:UTC|GMT)\s+", " ", text)
    for date_format in (
        "%a %b %d %H:%M:%S %Y",
        "%b %d, %Y",
        "%d %b %Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(cleaned, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


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
