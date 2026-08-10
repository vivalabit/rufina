from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

from scrapling import Selector
from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

SWATCH_GROUP_JOBS_BASE_URL = (
    "https://www.swatchgroup.com/en/job-finder?jf_country=40&domain=59"
    "&position=All&contract=All&time=All"
)
SWATCH_GROUP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7,fr;q=0.6",
}
JOB_PATH_PATTERN = re.compile(r"/(?:[a-z]{2}/)?job/(\d+)/?$", re.IGNORECASE)
DESCRIPTION_SELECTORS = (
    ".f-n-field-job-company-intro",
    ".f-n-body",
    ".f-n-field-job-profile",
    ".f-n-field-job-prof-requ",
    ".f-n-field-job-languages",
    ".f-n-field-job-contact",
)

PageFetcher = Callable[[str], ScraplingResponse]


class SwatchGroupParseError(DirectCompanyRequestError):
    pass


class SwatchGroupJobsParser:
    """Collect the Swiss IT catalog published by the Swatch Group job finder."""

    parser_id = "swatch_group"

    def __init__(
        self,
        *,
        base_url: str = SWATCH_GROUP_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        detail_workers: int = 6,
        fetch_page: PageFetcher | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = min(8, max(1, detail_workers))
        self.fetch_page = fetch_page or self._fetch_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            records, pages_fetched = self.collect_listing_records()
            self.enrich_records(records)
        except SwatchGroupParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError(
                "Swatch Group vacancy request failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_swatch_group_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Swatch Group Switzerland IT vacancies "
                f"across {pages_fetched} catalog page requests"
            ),
        )

    def _fetch_with_scrapling(self, url: str) -> ScraplingResponse:
        response = Fetcher.get(
            url,
            headers={**SWATCH_GROUP_HEADERS, "Referer": self.base_url},
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        status = int(getattr(response, "status", 0) or 0)
        if status >= 400:
            raise SwatchGroupParseError(f"Swatch Group returned HTTP {status}")
        return response

    def collect_listing_records(self) -> tuple[list[dict[str, Any]], int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        visited_urls: set[str] = set()
        page_url: str | None = self.base_url
        pages_fetched = 0

        while page_url:
            if page_url in visited_urls:
                raise SwatchGroupParseError("Swatch Group pagination contains a loop")
            if pages_fetched >= self.max_pages:
                raise SwatchGroupParseError(
                    "Swatch Group catalog exceeds the configured limit of "
                    f"{self.max_pages} pages"
                )

            visited_urls.add(page_url)
            listing_page = self.fetch_page(page_url)
            pages_fetched += 1
            page_records, next_url = parse_listing_page(
                listing_page,
                page_url=page_url,
            )
            for record in page_records:
                if record["id"] in records_by_id:
                    raise SwatchGroupParseError(
                        "Swatch Group pagination returned a duplicate vacancy ID"
                    )
                normalized = dict(record)
                normalized["listing_page"] = pages_fetched
                records_by_id[record["id"]] = normalized
            page_url = next_url

        return list(records_by_id.values()), pages_fetched

    def enrich_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                detail_page = self.fetch_page(record["url"])
                return record, parse_detail_page(
                    detail_page,
                    page_url=record["url"],
                    expected_job_id=record["id"],
                )
            except Exception as exc:  # noqa: BLE001
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(
            max_workers=min(self.detail_workers, len(records))
        ) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=(
                optional_text(detail.get("title"))
                or optional_text(record.get("title"))
            ),
            company=optional_text(detail.get("company")) or "Swatch Group",
            location=optional_text(detail.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=extract_employment_type(
                optional_text(detail.get("title"))
                or optional_text(record.get("title"))
            ),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("summary"))
            ),
            raw=dict(record),
        )


def parse_listing_page(
    page: ScraplingResponse,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], str | None]:
    if not page.css("#views-exposed-form-job-finder-page-1").get():
        raise SwatchGroupParseError(
            "Swatch Group listing page is missing its job finder form"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("div.card.h-100"):
        path = optional_text(card.css("h4.card-title a::attr(href)").get())
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        title = selector_text(card, "h4.card-title")
        summary = selector_text(card, "p.card__text")
        brand_logo = optional_text(card.css("img.img--top::attr(src)").get())
        if not detail_url or not job_id or not title or not summary:
            raise SwatchGroupParseError(
                "Swatch Group listing contains an incomplete vacancy"
            )
        if job_id in seen_ids:
            raise SwatchGroupParseError(
                "Swatch Group listing page contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "summary": summary,
                "url": detail_url,
                "brand_logo": urljoin(page_url, brand_logo) if brand_logo else None,
                "listing_page_url": page_url,
            }
        )

    next_path = optional_text(
        page.css('nav.pager a[rel="next"]::attr(href)').get()
        or page.css(".pager__item--next a::attr(href)").get()
    )
    if not records and not page.css(".view-empty").get():
        raise SwatchGroupParseError(
            "Swatch Group listing page is missing its vacancy cards"
        )
    return records, urljoin(page_url, next_path) if next_path else None


def parse_detail_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    if not page.css("main h1").get():
        raise SwatchGroupParseError(
            "Swatch Group detail page is missing its vacancy content"
        )

    job_id = extract_job_id(page_url)
    title = selector_text(page, "main h1")
    apply_path = optional_text(
        page.css("aside.job-card a.btn[href]::attr(href)").get()
    )
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    location = strip_labels(
        selector_text(page, "aside.job-card #jl"),
        ("Job location", "Arbeitsort", "Lieu de travail", "Luogo di lavoro"),
    )
    schema = extract_job_posting(page)
    company = nested_text(schema, "hiringOrganization", "name")
    posted_at = optional_text(schema.get("datePosted"))

    sections: list[str] = []
    for selector in DESCRIPTION_SELECTORS:
        section_html = page.css(selector).get()
        section_text = html_to_text(section_html) if section_html else None
        if section_text and section_text not in sections:
            sections.append(section_text)
    description = "\n\n".join(sections) or html_to_text(
        optional_text(schema.get("description"))
    )

    if not job_id or not title or not apply_url or not location or not description:
        raise SwatchGroupParseError(
            "Swatch Group detail page contains an incomplete vacancy"
        )
    if expected_job_id and job_id != expected_job_id:
        raise SwatchGroupParseError(
            "Swatch Group detail page returned a different vacancy"
        )

    return {
        "id": job_id,
        "title": title,
        "company": company or "Swatch Group",
        "location": location,
        "apply_url": apply_url,
        "posted_at": posted_at,
        "description": description,
        "schema": schema,
    }


def extract_job_posting(page: ScraplingResponse) -> dict[str, Any]:
    values = page.css('script[type="application/ld+json"]::text').getall()
    for value in values:
        try:
            # The production page embeds literal newlines inside the JSON
            # description string. strict=False accepts those control characters
            # while retaining the rest of the JobPosting contract validation.
            payload = json.loads(str(value), strict=False)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
    return {}


def nested_text(value: Any, *keys: str) -> str | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return optional_text(current)


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1) if match else None


def extract_employment_type(title: str | None) -> str | None:
    if not title:
        return None
    match = re.search(r"\b(\d{1,3})\s*%", title)
    return f"{match.group(1)}%" if match else None


def deduplicate_swatch_group_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Selector | ScraplingResponse, css: str) -> str | None:
    values = selector.css(f"{css} ::text").getall()
    if not values:
        values = selector.css(f"{css}::text").getall()
    return optional_text(" ".join(str(value).strip() for value in values if value))


def strip_labels(value: str | None, labels: Iterable[str]) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    for label in labels:
        if text.casefold().startswith(label.casefold()):
            return optional_text(text[len(label) :])
    return text


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
