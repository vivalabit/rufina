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

MOBILIAR_JOBS_BASE_URL = "https://jobs.mobiliar.ch/go/Jobs/506974/"
MOBILIAR_JOBS_API_URL = "https://jobs.mobiliar.ch/services/recruiting/v1/jobs"
MOBILIAR_HEADERS = {
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,fr;q=0.7,en;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
CSRF_TOKEN_PATTERN = re.compile(r'var\s+CSRFToken\s*=\s*"([^"]+)"')
CATEGORY_PATTERN = re.compile(r'categoryId:\s*["\']?506974["\']?')
DETAIL_JOB_ID_PATTERN = re.compile(r"/(\d+)-de_DE/?$")
WORKLOAD_RANGE_PATTERN = re.compile(r"\b(\d{1,3})\s*%?\s*[-–]\s*(\d{1,3})\s*%")
WORKLOAD_PERCENT_PATTERN = re.compile(r"\b(\d{1,3})\s*%")


class MobiliarParseError(DirectCompanyRequestError):
    pass


class MobiliarJobsParser:
    """Collect Mobiliar's complete SuccessFactors catalog."""

    parser_id = "mobiliar"

    def __init__(
        self,
        *,
        base_url: str = MOBILIAR_JOBS_BASE_URL,
        api_url: str = MOBILIAR_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 5,
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
                headers={**MOBILIAR_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                landing = client.get(self.base_url)
                landing.raise_for_status()
                csrf_token = parse_landing_html(landing.text)
                records, api_requests, total = self.collect_listing_records(
                    client,
                    csrf_token=csrf_token,
                )
                self.enrich_records(client, records)
        except MobiliarParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Mobiliar vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Mobiliar vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_mobiliar_jobs(jobs)
        request_label = "request" if api_requests == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Mobiliar vacancies from {total} catalog "
                f"records across {api_requests} API {request_label}"
            ),
        )

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
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf_token,
            },
            json={
                "keywords": "",
                "locale": "de_DE",
                "location": "",
                "pageNumber": page_number,
                "sortBy": "recent",
            },
        )
        response.raise_for_status()
        return parse_listing_payload(
            response.json(),
            page_url=str(response.url),
            page_number=page_number,
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
        *,
        csrf_token: str,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        api_requests = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, total = self.fetch_listing_page(
                client,
                csrf_token=csrf_token,
                page_number=0,
            )
            api_requests += 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise MobiliarParseError(
                    "Mobiliar catalog changed its result count during pagination"
                )
            if total == 0:
                return [], api_requests, 0
            page_size = len(first_records)
            if page_size <= 0:
                raise MobiliarParseError("Mobiliar listing is missing its page size")
            required_pages = ceil(total / page_size)
            if required_pages > self.max_pages:
                raise MobiliarParseError(
                    f"Mobiliar exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [first_records]
            for page_number in range(1, required_pages):
                records, page_total = self.fetch_listing_page(
                    client,
                    csrf_token=csrf_token,
                    page_number=page_number,
                )
                api_requests += 1
                if page_total != expected_total:
                    raise MobiliarParseError(
                        "Mobiliar catalog changed its result count during pagination"
                    )
                page_results.append(records)

            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), api_requests, expected_total
            if len(records_by_id) > expected_total:
                raise MobiliarParseError("Mobiliar catalog changed while pages were collected")

        raise MobiliarParseError(
            f"Mobiliar returned {len(records_by_id)} unique vacancies but declared "
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
                    expected_title=optional_text(record.get("title")),
                )
            except (httpx.HTTPError, MobiliarParseError, ValueError) as exc:
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
        public_url = optional_text(detail.get("public_url")) or optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(record.get("company")) or "die Mobiliar",
            location=optional_text(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=normalize_date(record.get("posted_at")),
            employment_type=join_unique(
                optional_text(record.get("contract_type")),
                normalize_workload(record.get("workload")),
            ),
            seniority=optional_text(record.get("seniority")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_landing_html(page_html: str) -> str:
    page = Selector(page_html)
    if not page.css("#jobSearch_searchGridComponent").get() or not CATEGORY_PATTERN.search(
        page_html
    ):
        raise MobiliarParseError("Mobiliar listing page is missing its vacancy catalog")
    match = CSRF_TOKEN_PATTERN.search(page_html)
    if not match:
        raise MobiliarParseError("Mobiliar listing page is missing its CSRF token")
    return match.group(1)


def parse_listing_payload(
    payload: Any,
    *,
    page_url: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise MobiliarParseError("Mobiliar jobs response must be an object")
    total = payload.get("totalJobs")
    items = payload.get("jobSearchResult")
    if not isinstance(total, int) or total < 0 or not isinstance(items, list):
        raise MobiliarParseError("Mobiliar jobs response has invalid pagination")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        response = item.get("response") if isinstance(item, dict) else None
        if not isinstance(response, dict):
            raise MobiliarParseError("Mobiliar jobs response contains an invalid vacancy")
        job_id = optional_text(response.get("id"))
        title = optional_text(response.get("unifiedStandardTitle"))
        slug = optional_text(response.get("unifiedUrlTitle"))
        if not job_id or not title or not slug:
            raise MobiliarParseError("Mobiliar jobs response contains an incomplete vacancy")
        if job_id in seen_ids:
            raise MobiliarParseError("Mobiliar jobs response contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        detail_url = urljoin(page_url, f"/job/{slug}/{job_id}-de_DE/")
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": first_list_text(response.get("sfstd_marketingBrand_obj")),
                "location": first_list_text(response.get("jobLocationShort")),
                "contract_type": first_list_text(response.get("cust_contractType")),
                "workload": optional_text(response.get("cust_postingCatFTE")),
                "department": first_list_text(response.get("cust_postingDep")),
                "seniority": first_list_text(response.get("cust_experienceLevel")),
                "posted_at": optional_text(response.get("unifiedStandardStart")),
                "url": detail_url,
                "listing_page_number": page_number,
                "listing_payload": dict(response),
            }
        )
    return records, total


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
    expected_title: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    if not page.css('[itemtype="http://schema.org/JobPosting"]').get():
        raise MobiliarParseError("Mobiliar detail page is missing its JobPosting content")

    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    public_url = urljoin(page_url, canonical) if canonical else page_url
    match = DETAIL_JOB_ID_PATTERN.search(urlsplit(public_url).path)
    job_id = match.group(1) if match else None
    title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    apply_path = optional_text(page.css("a.unify-apply-now::attr(href)").get()) or optional_text(
        page.css('.joblayouttoken [itemprop="description"] a[href^="mailto:"]::attr(href)').get()
    )
    if not job_id or not title:
        raise MobiliarParseError("Mobiliar detail page contains an incomplete vacancy")
    if expected_job_id and job_id != expected_job_id:
        raise MobiliarParseError("Mobiliar detail page returned a different vacancy")
    if expected_title and title.casefold() != expected_title.casefold():
        raise MobiliarParseError("Mobiliar detail page returned a different vacancy title")

    description_parts: list[str] = []
    for node in page.css(".joblayouttoken .rtltextaligneligible"):
        if node.css("h1").get() or not node.css("h2").get():
            continue
        if optional_text(node.attrib.get("itemprop")) == "description":
            continue
        node_html = node.get()
        text = html_to_text(node_html) if node_html else None
        if text:
            description_parts.append(text)
    description_parts = list(dict.fromkeys(description_parts))
    if not description_parts:
        raise MobiliarParseError("Mobiliar detail page is missing its vacancy description")

    return {
        "id": job_id,
        "title": title,
        "public_url": public_url,
        "apply_url": urljoin(page_url, apply_path) if apply_path else public_url,
        "description": "\n\n".join(description_parts),
    }


def first_list_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if text := optional_text(item):
                return text
    return optional_text(value) if isinstance(value, str) else None


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    range_match = WORKLOAD_RANGE_PATTERN.search(text)
    if range_match:
        return f"{range_match.group(1)}%-{range_match.group(2)}%"
    percent_match = WORKLOAD_PERCENT_PATTERN.search(text)
    return f"{percent_match.group(1)}%" if percent_match else text


def deduplicate_mobiliar_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def join_unique(*values: str | None) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


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
