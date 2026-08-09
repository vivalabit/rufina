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

SAP_SWITZERLAND_JOBS_BASE_URL = "https://jobs.sap.com/go/SAP-Jobs-in-Switzerland/915101/"
SAP_SWITZERLAND_HEADERS = {
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


class SapSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SapSwitzerlandJobsParser:
    """Collect the complete Swiss SAP catalog from its SuccessFactors site."""

    parser_id = "sap_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SAP_SWITZERLAND_JOBS_BASE_URL,
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
                headers={**SAP_SWITZERLAND_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SapSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("SAP Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("SAP Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_sap_switzerland_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} SAP Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} page {request_label}"
            ),
        )

    def listing_url(self, *, offset: int) -> str:
        params = {
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
            raise SapSwitzerlandParseError(
                "SAP Switzerland pagination returned an unexpected result range"
            )
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
                raise SapSwitzerlandParseError(
                    "SAP Switzerland catalog changed its result count during pagination"
                )
            if page_size <= 0:
                raise SapSwitzerlandParseError("SAP Switzerland listing is missing its page size")

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise SapSwitzerlandParseError(
                    f"SAP Switzerland exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            page_results = [first_records]
            for offset in range(page_size, total, page_size):
                records, metadata = self.fetch_listing_page(client, offset=offset)
                pages_fetched += 1
                if metadata["total"] != expected_total:
                    raise SapSwitzerlandParseError(
                        "SAP Switzerland catalog changed its result count during pagination"
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
                raise SapSwitzerlandParseError(
                    "SAP Switzerland catalog changed while pages were collected"
                )

        raise SapSwitzerlandParseError(
            f"SAP Switzerland returned {len(records_by_id)} unique vacancies but "
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
            except (httpx.HTTPError, SapSwitzerlandParseError, ValueError) as exc:
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
            company=optional_text(detail.get("company")) or "SAP",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url")) or build_apply_url(self.base_url, job_id)
            ),
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=optional_text(detail.get("employment_type")),
            seniority=optional_text(detail.get("career_status")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    page = Selector(page_html)
    if not page.css("table#searchresults").get():
        raise SapSwitzerlandParseError("SAP Switzerland listing page is missing its search results")

    label_html = page.css(".paginationLabel").get()
    label = html_to_text(label_html) if label_html else None
    match = RESULT_RANGE_PATTERN.search(label or "")
    if not match:
        raise SapSwitzerlandParseError("SAP Switzerland listing page is missing its result range")
    start, end, total = (int(value.replace(",", "")) for value in match.groups())

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in page.css("table#searchresults tbody tr.data-row"):
        path = optional_text(row.css("a.jobTitle-link::attr(href)").get())
        title = optional_text(row.css("a.jobTitle-link::text").get())
        location_html = row.css("td.colLocation span.jobLocation").get()
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        if not job_id or not title or not detail_url:
            raise SapSwitzerlandParseError("SAP Switzerland listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise SapSwitzerlandParseError("SAP Switzerland listing contains duplicate vacancy IDs")
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
        raise SapSwitzerlandParseError(
            f"SAP Switzerland listed {len(records)} vacancies for a range of "
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
        raise SapSwitzerlandParseError("SAP Switzerland detail page is missing its JobPosting data")

    title = property_text(page, "title")
    description_html = page.css('[itemprop="description"]').get()
    description = html_to_text(description_html) if description_html else None
    apply_path = optional_text(page.css("a.dialogApplyBtn::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    detail_job_id = extract_job_id(apply_url)
    if not title or not description or not apply_url or not detail_job_id:
        raise SapSwitzerlandParseError("SAP Switzerland detail page contains an incomplete vacancy")
    if expected_job_id and detail_job_id != expected_job_id:
        raise SapSwitzerlandParseError("SAP Switzerland detail page returned a different vacancy")

    location = optional_text(page.css(".jobGeoLocation::text").get())
    return {
        "id": detail_job_id,
        "title": title,
        "company": property_attribute(page, "hiringOrganization", "content") or "SAP",
        "location": location or property_attribute(page, "addressLocality", "content"),
        "apply_url": apply_url,
        "posted_at": normalize_date(
            property_text(page, "date") or property_attribute(page, "datePosted", "content")
        ),
        "requisition_id": property_text(page, "facility"),
        "work_area": property_text(page, "department"),
        "career_status": property_text(page, "customfield3"),
        "employment_type": property_text(page, "shifttype"),
        "expected_travel": property_text(page, "travel"),
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


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    for pattern in (JOB_PATH_PATTERN, APPLY_PATH_PATTERN):
        if match := pattern.search(path):
            return match.group(1)
    return None


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id:
        return None
    return urljoin(base_url, f"/talentcommunity/apply/{job_id}/?locale=en_US")


def deduplicate_sap_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
