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

SWISS_RE_JOBS_BASE_URL = "https://www.swissre.com/careers/switzerland-careers.html"
SWISS_RE_JOBS_SEARCH_URL = "https://careers.swissre.com/search/"
SWISS_RE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7,fr;q=0.6",
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
SALARY_RANGE_PATTERN = re.compile(
    r"base salary range.{0,180}?CHF\s*([\d,'’. ]+)\s+"
    r"(?:and|to|[-–])\s+(?:CHF\s*)?([\d,'’. ]+)",
    re.IGNORECASE | re.DOTALL,
)


class SwissReParseError(DirectCompanyRequestError):
    pass


class SwissReJobsParser:
    """Collect Swiss Re vacancies filtered to Switzerland in SuccessFactors."""

    parser_id = "swiss_re"

    def __init__(
        self,
        *,
        base_url: str = SWISS_RE_JOBS_BASE_URL,
        search_url: str = SWISS_RE_JOBS_SEARCH_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.search_url = search_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**SWISS_RE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SwissReParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Swiss Re vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Swiss Re vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_swiss_re_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Swiss Re vacancies from {total} Swiss "
                f"catalog records across {pages_fetched} page {request_label}"
            ),
        )

    def listing_url(self, *, offset: int) -> str:
        params = {
            "q": "",
            "locationsearch": "Switzerland",
            "locale": "en_GB",
            "sortColumn": "referencedate",
            "sortDirection": "desc",
        }
        if offset:
            params["startrow"] = str(offset)
        return str(httpx.URL(self.search_url).copy_merge_params(params))

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
        if metadata["start"] != offset + 1:
            raise SwissReParseError("Swiss Re pagination returned an unexpected result range")
        return records, metadata

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # Offset pages can shift while a vacancy is published. Repeat and union
        # stable SuccessFactors IDs until every declared record is present.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, first_metadata = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            total = first_metadata["total"]
            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise SwissReParseError(
                    "Swiss Re catalog changed its result count during pagination"
                )
            if page_size <= 0:
                raise SwissReParseError("Swiss Re listing is missing its page size")

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise SwissReParseError(
                    f"Swiss Re exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [first_records]
            for offset in range(page_size, total, page_size):
                records, metadata = self.fetch_listing_page(client, offset=offset)
                pages_fetched += 1
                if metadata["total"] != expected_total:
                    raise SwissReParseError(
                        "Swiss Re catalog changed its result count during pagination"
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
                raise SwissReParseError("Swiss Re catalog changed while pages were collected")

        raise SwissReParseError(
            f"Swiss Re returned {len(records_by_id)} unique vacancies but declared "
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
                response = client.get(record["url"], headers={"Referer": self.search_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, SwissReParseError, ValueError) as exc:
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
            company=optional_text(detail.get("company")) or "Swiss Re",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url")) or build_apply_url(self.search_url, job_id)
            ),
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
            ),
            employment_type=optional_text(detail.get("workload")),
            description=optional_multiline_text(detail.get("description")),
            salary=optional_text(detail.get("salary")),
            salary_min=optional_integer(detail.get("salary_min")),
            salary_max=optional_integer(detail.get("salary_max")),
            salary_currency=(
                "CHF"
                if detail.get("salary_min") is not None or detail.get("salary_max") is not None
                else None
            ),
            salary_unit=(
                "year"
                if detail.get("salary_min") is not None or detail.get("salary_max") is not None
                else None
            ),
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
        raise SwissReParseError("Swiss Re listing page is missing its search results")

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
        raise SwissReParseError("Swiss Re listing page is missing its result range")
    start, end, total = (int(value.replace(",", "")) for value in match.groups())

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in page.css("table#searchresults tbody tr.data-row"):
        path = optional_text(row.css("a.jobTitle-link::attr(href)").get())
        title = optional_text(row.css("a.jobTitle-link::text").get())
        location_html = row.css("td.colLocation span.jobLocation").get()
        posted_at = optional_text(row.css("td.colDate span.jobDate::text").get())
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        location = html_to_text(location_html) if location_html else None
        if not job_id or not title or not location or not detail_url:
            raise SwissReParseError("Swiss Re listing contains an incomplete vacancy")
        if not is_swiss_location(location):
            raise SwissReParseError(
                f"Swiss Re location filter returned a non-Swiss vacancy: {location}"
            )
        if job_id in seen_ids:
            raise SwissReParseError("Swiss Re listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": location,
                "posted_at": normalize_date(posted_at),
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    expected_count = end - start + 1
    if len(records) != expected_count:
        raise SwissReParseError(
            f"Swiss Re listed {len(records)} vacancies for a range of {expected_count} records"
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
        raise SwissReParseError("Swiss Re detail page is missing its JobPosting data")

    title = property_text(page, "title")
    description_html = page.css('[itemprop="description"]').get()
    description = html_to_text(description_html) if description_html else None
    apply_path = optional_text(page.css("a.dialogApplyBtn::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    detail_job_id = extract_job_id(apply_url)
    if not title or not description or not apply_url or not detail_job_id:
        raise SwissReParseError("Swiss Re detail page contains an incomplete vacancy")
    if expected_job_id and detail_job_id != expected_job_id:
        raise SwissReParseError("Swiss Re detail page returned a different vacancy")

    salary_min, salary_max = extract_salary_range(description)
    workload_match = WORKLOAD_PATTERN.search(title)
    return {
        "id": detail_job_id,
        "title": title,
        "company": property_attribute(page, "hiringOrganization", "content") or "Swiss Re",
        "location": (
            optional_text(page.css(".jobGeoLocation::text").get())
            or property_attribute(page, "addressLocality", "content")
        ),
        "apply_url": apply_url,
        "posted_at": normalize_date(property_attribute(page, "datePosted", "content")),
        "workload": (optional_text(workload_match.group(0)) if workload_match else None),
        "job_segment": optional_text(page.css('[itemprop="industry"]::text').get()),
        "description": description,
        "salary": (
            f"CHF {salary_min:,}–{salary_max:,} per year"
            if salary_min is not None and salary_max is not None
            else None
        ),
        "salary_min": salary_min,
        "salary_max": salary_max,
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


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    for pattern in (JOB_PATH_PATTERN, APPLY_PATH_PATTERN):
        if match := pattern.search(path):
            return match.group(1)
    return None


def extract_salary_range(description: str | None) -> tuple[int | None, int | None]:
    if not description or not (match := SALARY_RANGE_PATTERN.search(description)):
        return None, None
    values = [int(re.sub(r"\D", "", item)) for item in match.groups()]
    return values[0], values[1]


def is_swiss_location(location: str | None) -> bool:
    return bool(location and re.search(r"(?:,|\s)CH\s*$", location, re.IGNORECASE))


def build_apply_url(search_url: str, job_id: str | None) -> str | None:
    if not job_id:
        return None
    return urljoin(search_url, f"/talentcommunity/apply/{job_id}/?locale=en_GB")


def deduplicate_swiss_re_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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


def optional_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = optional_text(value)
    return int(text) if text and text.isdigit() else None


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
