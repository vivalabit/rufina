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

EY_SWITZERLAND_JOBS_BASE_URL = (
    "https://careers.ey.com/ey/search/?createNewAlert=false&q=&locationsearch="
    "&optionsFacetsDD_country=CH&optionsFacetsDD_customfield1="
)
EY_SWITZERLAND_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7,fr;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
RESULT_RANGE_PATTERN = re.compile(
    r"Results\s+(\d[\d,]*)\s*[–-]\s*(\d[\d,]*)\s+of\s+(\d[\d,]*)",
    re.IGNORECASE,
)
JOB_PATH_PATTERN = re.compile(r"/job/.+/(\d+)/?$")
APPLY_PATH_PATTERN = re.compile(r"/talentcommunity/apply/(\d+)/?$")
EMPLOYMENT_RANGE_PATTERN = re.compile(r"\b(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%")
EMPLOYMENT_PERCENT_PATTERN = re.compile(r"\b(\d{1,3})\s*%")


class EySwitzerlandParseError(DirectCompanyRequestError):
    pass


class EySwitzerlandJobsParser:
    """Collect the complete Swiss EY catalog from its SuccessFactors site."""

    parser_id = "ey_switzerland"

    def __init__(
        self,
        *,
        base_url: str = EY_SWITZERLAND_JOBS_BASE_URL,
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
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**EY_SWITZERLAND_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except EySwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("EY Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("EY Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ey_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} EY Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} page requests"
            ),
        )

    def listing_url(self, *, offset: int) -> str:
        params = {
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
        records, metadata = parse_listing_html(
            response.text,
            page_url=str(response.url),
        )
        if metadata["start"] != offset + 1:
            raise EySwitzerlandParseError(
                "EY Switzerland pagination returned an unexpected result range"
            )
        return records, metadata

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for _ in range(self.max_catalog_passes):
            first_records, first_metadata = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            total = first_metadata["total"]
            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise EySwitzerlandParseError(
                    "EY Switzerland catalog changed its result count during pagination"
                )
            if page_size <= 0:
                raise EySwitzerlandParseError("EY Switzerland listing is missing its page size")

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise EySwitzerlandParseError(
                    f"EY Switzerland exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            page_results = [first_records]
            for offset in range(page_size, total, page_size):
                records, metadata = self.fetch_listing_page(client, offset=offset)
                pages_fetched += 1
                if metadata["total"] != expected_total:
                    raise EySwitzerlandParseError(
                        "EY Switzerland catalog changed its result count during pagination"
                    )
                page_results.append(records)

            for page_records in page_results:
                for record in page_records:
                    records_by_id[record["id"]] = record

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise EySwitzerlandParseError(
                    "EY Switzerland catalog changed while pages were collected"
                )

        raise EySwitzerlandParseError(
            f"EY Switzerland returned {len(records_by_id)} unique vacancies but "
            f"declared {expected_total or 0}"
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
            except (httpx.HTTPError, EySwitzerlandParseError, ValueError) as exc:
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
        raw = dict(record)
        job_id = optional_text(record.get("id"))
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company=optional_text(detail.get("company")) or "EY",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url")) or build_apply_url(self.base_url, job_id)
            ),
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=extract_employment_type(title),
            description=optional_multiline_text(detail.get("description")),
            salary=optional_text(detail.get("salary")),
            raw=raw,
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    page = Selector(page_html)
    if not page.css("table#searchresults").get():
        raise EySwitzerlandParseError("EY Switzerland listing page is missing its search results")

    label_html = page.css(".paginationLabel").get()
    label = html_to_text(label_html) if label_html else None
    match = RESULT_RANGE_PATTERN.search(label or "")
    if not match:
        raise EySwitzerlandParseError("EY Switzerland listing page is missing its result range")
    start, end, total = (int(value.replace(",", "")) for value in match.groups())

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in page.css("table#searchresults tbody tr.data-row"):
        path = optional_text(row.css("a.jobTitle-link::attr(href)").get())
        title = optional_text(row.css("a.jobTitle-link::text").get())
        location_html = row.css("span.jobLocation").get()
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        if not job_id or not title or not detail_url:
            raise EySwitzerlandParseError("EY Switzerland listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise EySwitzerlandParseError("EY Switzerland listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": html_to_text(location_html) if location_html else None,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    expected_count = end - start + 1
    if len(records) != expected_count:
        raise EySwitzerlandParseError(
            f"EY Switzerland listed {len(records)} vacancies for a range of "
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
        raise EySwitzerlandParseError("EY Switzerland detail page is missing its JobPosting data")

    title = property_text(page, "title")
    description_html = page.css('[itemprop="description"]').get()
    description = html_to_text(description_html) if description_html else None
    apply_path = optional_text(page.css("a.dialogApplyBtn::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    detail_job_id = extract_job_id(apply_url)
    if not title or not description or not apply_url or not detail_job_id:
        raise EySwitzerlandParseError("EY Switzerland detail page contains an incomplete vacancy")
    if expected_job_id and detail_job_id != expected_job_id:
        raise EySwitzerlandParseError("EY Switzerland detail page returned a different vacancy")

    city = property_text(page, "city")
    other_locations = property_text(page, "customfield3")
    if other_locations and other_locations.casefold() == "primary location only":
        other_locations = None
    location = "; ".join(value for value in (city, other_locations) if value) or property_attribute(
        page, "streetAddress", "content"
    )
    posted_at = normalize_date(
        property_text(page, "date") or property_attribute(page, "datePosted", "content")
    )
    company = property_attribute(page, "hiringOrganization", "content")
    return {
        "id": detail_job_id,
        "title": title,
        "company": company,
        "location": location,
        "apply_url": apply_url,
        "posted_at": posted_at,
        "requisition_id": property_text(page, "customfield5"),
        "description": description,
    }


def property_text(page: Selector, property_id: str) -> str | None:
    values = page.css(f'[data-careersite-propertyid="{property_id}"]::text').getall()
    return optional_text(" ".join(str(value) for value in values))


def property_attribute(page: Selector, itemprop: str, attribute: str) -> str | None:
    return optional_text(page.css(f'[itemprop="{itemprop}"]::attr({attribute})').get())


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    for pattern in (JOB_PATH_PATTERN, APPLY_PATH_PATTERN):
        match = pattern.search(path)
        if match:
            return match.group(1)
    return None


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id:
        return None
    return urljoin(base_url, f"/talentcommunity/apply/{job_id}/?locale=en_US")


def extract_employment_type(title: str | None) -> str | None:
    if not title:
        return None
    range_match = EMPLOYMENT_RANGE_PATTERN.search(title)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}%"
    percent_match = EMPLOYMENT_PERCENT_PATTERN.search(title)
    return f"{percent_match.group(1)}%" if percent_match else None


def deduplicate_ey_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    for date_format in (
        "%Y-%m-%d",
        "%b %d, %Y",
        "%a %b %d %H:%M:%S UTC %Y",
    ):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


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
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
