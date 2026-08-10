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

SUVA_JOBS_BASE_URL = (
    "https://jobs.suva.ch/search/?q=&searchResultView=LIST&pageNumber=0"
    "&facetFilters=%7B%7D&sortBy=&markerViewed=&carouselIndex="
)
SUVA_JOBS_API_URL = "https://jobs.suva.ch/services/recruiting/v1/jobs"
SUVA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
CSRF_TOKEN_PATTERN = re.compile(r'var\s+CSRFToken\s*=\s*"([^"]+)"')
JOB_PATH_PATTERN = re.compile(r"/job/.+/(\d+)(?:-[^/]+)?/?$")
APPLY_PATH_PATTERN = re.compile(r"/talentcommunity/apply/(\d+)/?$")
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}\s*(?:[-\u2013]\s*\d{1,3}\s*)?%")


class SuvaParseError(DirectCompanyRequestError):
    pass


class SuvaJobsParser:
    """Collect the complete Suva catalog from its public SuccessFactors API."""

    parser_id = "suva"

    def __init__(
        self,
        *,
        base_url: str = SUVA_JOBS_BASE_URL,
        api_url: str = SUVA_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**SUVA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                csrf_token = self.bootstrap_session(client)
                records, pages_fetched, total = self.collect_listing_records(
                    client,
                    csrf_token=csrf_token,
                )
                self.enrich_records(client, records)
        except SuvaParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Suva vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Suva vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_suva_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Suva vacancies from {total} catalog records "
                f"across {pages_fetched} page {request_label}"
            ),
        )

    def bootstrap_session(self, client: httpx.Client) -> str:
        response = client.get(self.base_url)
        response.raise_for_status()
        match = CSRF_TOKEN_PATTERN.search(response.text)
        if not match:
            raise SuvaParseError("Suva search page is missing its CSRF token")
        return match.group(1)

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        csrf_token: str,
        page_number: int,
    ) -> tuple[list[dict[str, Any]], int]:
        response = client.post(
            self.api_url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf_token,
            },
            json={
                "locale": "de_DE",
                "pageNumber": page_number,
                "sortBy": "",
                "keywords": "",
                "location": "",
                "facetFilters": {},
                "brand": "",
                "skills": [],
                "categoryId": 0,
                "alertId": "",
                "rcmCandidateId": "",
            },
        )
        response.raise_for_status()
        records, total = parse_listing_payload(response.json(), base_url=self.base_url)
        for record in records:
            record["listing_page_number"] = page_number
            record["listing_api_url"] = str(response.url)
        return records, total

    def collect_listing_records(
        self,
        client: httpx.Client,
        *,
        csrf_token: str,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, total = self.fetch_listing_page(
                client,
                csrf_token=csrf_token,
                page_number=0,
            )
            pages_fetched += 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise SuvaParseError("Suva catalog changed its result count during pagination")

            if total == 0:
                return [], pages_fetched, 0
            page_size = len(first_records)
            if page_size <= 0:
                raise SuvaParseError("Suva listing is missing its page size")
            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise SuvaParseError(
                    f"Suva exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [first_records]
            for page_number in range(1, required_pages):
                records, page_total = self.fetch_listing_page(
                    client,
                    csrf_token=csrf_token,
                    page_number=page_number,
                )
                pages_fetched += 1
                if page_total != expected_total:
                    raise SuvaParseError("Suva catalog changed its result count during pagination")
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
                raise SuvaParseError("Suva catalog changed while pages were collected")

        raise SuvaParseError(
            f"Suva returned {len(records_by_id)} unique vacancies but declared "
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
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, SuvaParseError, ValueError) as exc:
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
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        workload_match = WORKLOAD_PATTERN.search(title or "")
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company="Suva",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=optional_text(record.get("url")),
            apply_url=(
                optional_text(detail.get("apply_url"))
                or build_apply_url(self.base_url, optional_text(record.get("id")))
            ),
            posted_at=normalize_date(record.get("posted_at")),
            employment_type=(optional_text(workload_match.group(0)) if workload_match else None),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_payload(
    payload: Any,
    *,
    base_url: str,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise SuvaParseError("Suva listing payload is not an object")
    items = payload.get("jobSearchResult")
    total = payload.get("totalJobs")
    if not isinstance(items, list) or not isinstance(total, int) or total < 0:
        raise SuvaParseError("Suva listing payload is missing its catalog contract")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        response = item.get("response") if isinstance(item, dict) else None
        if not isinstance(response, dict):
            raise SuvaParseError("Suva listing contains an invalid vacancy")
        job_id = optional_text(response.get("id"))
        title = optional_text(response.get("unifiedStandardTitle"))
        url_title = optional_text(response.get("unifiedUrlTitle") or response.get("urlTitle"))
        if not job_id or not title or not url_title:
            raise SuvaParseError("Suva listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise SuvaParseError("Suva listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        locations = normalize_locations(response.get("jobLocationShort"))
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": ", ".join(locations) or None,
                "locations": locations,
                "posted_at": optional_text(response.get("unifiedStandardStart")),
                "url_title": url_title,
                "url": build_detail_url(base_url, url_title=url_title, job_id=job_id),
                "listing": dict(response),
            }
        )
    if len(records) > total:
        raise SuvaParseError("Suva listing returned more vacancies than declared")
    return records, total


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    if not page.css('[itemtype="http://schema.org/JobPosting"]').get():
        raise SuvaParseError("Suva detail page is missing its JobPosting data")

    description_parts = [
        text
        for value in (
            page.css('[itemprop="description"]').get(),
            *page.css("#unifyJobFooter .joblayouttoken span.rtltextaligneligible").getall(),
        )
        if (text := html_to_text(value))
    ]
    description = "\n\n".join(dict.fromkeys(description_parts)) or None
    apply_path = optional_text(page.css("a.dialogApplyBtn::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    detail_job_id = extract_job_id(apply_url) or extract_job_id(page_url)
    title = optional_text(page.css('meta[name="keywords"]::attr(content)').get())
    if not title or not description or not apply_url or not detail_job_id:
        raise SuvaParseError("Suva detail page contains an incomplete vacancy")
    if expected_job_id and detail_job_id != expected_job_id:
        raise SuvaParseError("Suva detail page returned a different vacancy")

    location = optional_text(page.css('[itemprop="addressLocality"]::text').get())
    return {
        "id": detail_job_id,
        "title": title,
        "location": location,
        "apply_url": apply_url,
        "description": description,
    }


def build_detail_url(base_url: str, *, url_title: str, job_id: str) -> str:
    return urljoin(base_url, f"/job/{url_title}/{job_id}-de_DE/")


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id:
        return None
    return urljoin(base_url, f"/talentcommunity/apply/{job_id}/?locale=de_DE")


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    for pattern in (JOB_PATH_PATTERN, APPLY_PATH_PATTERN):
        if match := pattern.search(path):
            return match.group(1)
    return None


def normalize_locations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := optional_text(item))))


def deduplicate_suva_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    for date_format in ("%Y-%m-%d", "%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


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
