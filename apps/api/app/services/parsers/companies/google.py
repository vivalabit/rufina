from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

GOOGLE_JOBS_BASE_URL = (
    "https://www.google.com/about/careers/applications/jobs/results/"
    "?location=Zurich%2C%20Switzerland"
)
GOOGLE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
RESULT_RANGE_PATTERN = re.compile(
    r"Showing\s+(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+rows",
    re.IGNORECASE,
)
ZERO_RESULTS_PATTERN = re.compile(r"\b0\s+jobs?\s+matched\b", re.IGNORECASE)
JOB_ID_PATTERN = re.compile(r"/jobs/results/(\d+)(?:-|/|$)", re.IGNORECASE)


class GoogleParseError(DirectCompanyRequestError):
    pass


class GoogleJobsParser:
    """Collect the complete Google Careers catalog filtered to Zürich."""

    parser_id = "google"

    def __init__(
        self,
        *,
        base_url: str = GOOGLE_JOBS_BASE_URL,
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
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**GOOGLE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except GoogleParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Google vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Google vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_google_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Google Zürich vacancies from {total} "
                f"catalog records across {pages_fetched} page requests"
            ),
        )

    def listing_url(self, *, page: int) -> str:
        params = {"page": str(page)} if page > 1 else {}
        return str(httpx.URL(self.base_url).copy_merge_params(params))

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        page_number: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        response = client.get(self.listing_url(page=page_number))
        response.raise_for_status()
        return parse_listing_html(response.text, page_url=str(response.url))

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(self.max_catalog_passes):
            first_records, first_metadata = self.fetch_listing_page(
                client,
                page_number=1,
            )
            pages_fetched += 1
            total = first_metadata["total"]
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise GoogleParseError("Google catalog changed its result count during pagination")
            if total == 0:
                return [], pages_fetched, 0

            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if page_size <= 0:
                raise GoogleParseError("Google listing is missing its page size")
            required_pages = ceil(total / page_size)
            if required_pages > self.max_pages:
                raise GoogleParseError(
                    f"Google exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [(1, first_records)]
            for page_number in range(2, required_pages + 1):
                page_records, metadata = self.fetch_listing_page(
                    client,
                    page_number=page_number,
                )
                pages_fetched += 1
                expected_start = ((page_number - 1) * page_size) + 1
                expected_end = min(page_number * page_size, total)
                if (
                    metadata["total"] != expected_total
                    or metadata["start"] != expected_start
                    or metadata["end"] != expected_end
                ):
                    raise GoogleParseError("Google pagination returned an unexpected result range")
                page_results.append((page_number, page_records))

            for page_number, page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_page"] = page_number
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise GoogleParseError("Google catalog changed while pages were collected")

        raise GoogleParseError(
            f"Google returned {len(records_by_id)} unique vacancies but declared "
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
            except (httpx.HTTPError, GoogleParseError, ValueError) as exc:
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
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(detail.get("company"))
            or optional_text(record.get("company"))
            or "Google",
            location=optional_text(detail.get("location")) or optional_text(record.get("location")),
            url=optional_text(record.get("url")),
            apply_url=optional_text(detail.get("apply_url")) or optional_text(record.get("url")),
            posted_at=None,
            employment_type=None,
            seniority=optional_text(detail.get("seniority"))
            or optional_text(record.get("seniority")),
            description=optional_multiline_text(detail.get("description"))
            or optional_multiline_text(record.get("minimum_qualifications")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    page = Selector(page_html)
    page_text = selector_text(page, "body")
    match = RESULT_RANGE_PATTERN.search(page_text or "")
    if match:
        start, end, total = (int(value) for value in match.groups())
    elif ZERO_RESULTS_PATTERN.search(page_text or ""):
        start = end = total = 0
    else:
        raise GoogleParseError("Google listing page is missing its result range")

    document_base = optional_text(page.css("base::attr(href)").get()) or page_url
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("div.sMn82b"):
        path = optional_text(card.css('a[aria-label^="Learn more about"]::attr(href)').get())
        detail_url = urljoin(document_base, path) if path else None
        job_id = extract_job_id(detail_url)
        title = selector_text(card, "h3.QJPWVe")
        company = selector_text(card, ".RP7SMd span")
        locations = normalized_unique_texts(card.css(".r0wTof::text").getall())
        location = "; ".join(locations) if locations else None
        seniority = selector_text(card, ".wVSTAb")
        minimum_html = card.css(".Xsxa1e").get()
        minimum_qualifications = html_to_text(minimum_html) if minimum_html else None
        if not detail_url or not job_id or not title or not location:
            raise GoogleParseError("Google listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise GoogleParseError("Google listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": company or "Google",
                "location": location,
                "seniority": seniority,
                "minimum_qualifications": minimum_qualifications,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    expected_count = max(0, end - start + 1) if total else 0
    if len(records) != expected_count:
        raise GoogleParseError(
            f"Google listed {len(records)} vacancies for a range of {expected_count} records"
        )
    return records, {"start": start, "end": end, "total": total}


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    detail_roots = page.css(".DkhPwc[data-id]")
    if len(detail_roots) != 1:
        raise GoogleParseError("Google detail page is missing its vacancy content")
    root = detail_roots[0]
    job_id = optional_text(root.attrib.get("data-id"))
    title = selector_text(root, "h2.p1N2lc")
    company = selector_text(root, ".op1BBf .RP7SMd span")
    visible_locations = normalized_unique_texts(root.css(".op1BBf .r0wTof::text").getall())
    preferred_locations: list[str] = []
    for value in root.css(".KwJkGe b::text").getall():
        text = optional_text(value)
        if text and "switzerland" in text.casefold():
            preferred_locations.extend(text.split(";"))
    locations = normalized_unique_texts(preferred_locations) or visible_locations
    location = "; ".join(locations) if locations else None
    seniority = selector_text(root, ".op1BBf .wVSTAb")
    document_base = optional_text(page.css("base::attr(href)").get()) or page_url
    apply_path = optional_text(root.css("#apply-action-button::attr(href)").get())
    apply_url = urljoin(document_base, apply_path) if apply_path else None
    description_sections: list[str] = []
    for selector in (".KwJkGe", ".aG5W3", ".BDNOWe"):
        section_html = root.css(selector).get()
        section_text = html_to_text(section_html) if section_html else None
        if section_text:
            description_sections.append(section_text)
    description = "\n\n".join(description_sections) or None

    if (
        not job_id
        or not title
        or not location
        or "switzerland" not in location.casefold()
        or not apply_url
        or not description
    ):
        raise GoogleParseError("Google detail page contains an incomplete or non-Swiss vacancy")
    if expected_job_id and job_id != expected_job_id:
        raise GoogleParseError("Google detail page returned a different vacancy")

    return {
        "id": job_id,
        "title": title,
        "company": company or "Google",
        "location": location,
        "apply_url": apply_url,
        "seniority": seniority,
        "description": description,
    }


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_ID_PATTERN.search(urlsplit(text).path)
    return match.group(1) if match else None


def deduplicate_google_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalized_unique_texts(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = optional_text(value)
        text = text.lstrip("; ") if text else None
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def selector_text(selector: Selector, css: str) -> str | None:
    values = selector.css(f"{css} ::text").getall()
    if not values:
        values = selector.css(f"{css}::text").getall()
    return optional_text(" ".join(str(value).strip() for value in values if value))


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


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", normalized).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
