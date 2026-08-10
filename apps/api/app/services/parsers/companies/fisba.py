from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

FISBA_JOBS_BASE_URL = "https://www.fisba.com/en/current-vacancies"
FISBA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"/en/jobs/([^/?#]+)/?$", re.IGNORECASE)
CATALOG_SECTIONS = (
    ("[id^='block-views-block-jobs-block-1']", "vacancy"),
    ("[id^='block-views-block-jobs-lehrlinge-block-1']", "apprenticeship"),
)
DESCRIPTION_SELECTORS = (
    ".field--name-field-company-description",
    ".field--name-body",
    ".field--name-field-job-requirements",
    ".field--name-field-job-offer",
    ".field--name-field-contact",
)


class FisbaParseError(DirectCompanyRequestError):
    pass


class FisbaJobsParser:
    """Collect the complete Swiss vacancy and apprenticeship catalog from FISBA."""

    parser_id = "fisba"

    def __init__(
        self,
        *,
        base_url: str = FISBA_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**FISBA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                )
                self.enrich_records(client, records)
        except FisbaParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("FISBA vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("FISBA vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_fisba_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} FISBA Switzerland vacancies from the official catalog"),
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
                response = client.get(
                    record["url"],
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, FisbaParseError, ValueError) as exc:
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
        public_url = optional_text(record.get("url"))
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company="FISBA AG",
            location=(
                optional_text(detail.get("location"))
                or normalize_swiss_location(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=None,
            employment_type=extract_employment_type(
                title,
                optional_text(record.get("catalog_section")),
            ),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> list[dict[str, Any]]:
    page = Selector(page_html)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for section_selector, section_kind in CATALOG_SECTIONS:
        section = page.css(section_selector)
        if not section.get():
            raise FisbaParseError(f"FISBA listing is missing its {section_kind} section")
        for card in section.css(".view-content .job"):
            path = optional_text(card.css(".views-field-title a::attr(href)").get())
            title = selector_text(card, ".views-field-title h4")
            location = selector_text(
                card,
                ".views-field-field-workplace-locality .field-content",
            )
            detail_url = urljoin(page_url, path) if path else None
            job_id = extract_job_id(detail_url)
            if not job_id or not title or not detail_url or not normalize_swiss_location(location):
                raise FisbaParseError("FISBA listing contains an incomplete or non-Swiss vacancy")
            if job_id in seen_ids:
                raise FisbaParseError("FISBA listing contains duplicate vacancy IDs")
            seen_ids.add(job_id)
            records.append(
                {
                    "id": job_id,
                    "title": title,
                    "location": location,
                    "catalog_section": section_kind,
                    "url": detail_url,
                    "listing_page_url": page_url,
                }
            )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    if not page.css("main .jobs-full").get():
        raise FisbaParseError("FISBA detail page is missing its job content")

    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    page_id = extract_job_id(page_url)
    canonical_id = extract_job_id(canonical)
    if (
        not page_id
        or not canonical_id
        or page_id != canonical_id
        or (expected_job_id and page_id != expected_job_id)
    ):
        raise FisbaParseError("FISBA detail page returned a different vacancy")

    title = selector_text(page, "main .jobs-full h1")
    description_parts: list[str] = []
    for selector in DESCRIPTION_SELECTORS:
        value = page.css(f"main .jobs-full {selector}").get()
        text = html_to_text(str(value)) if value else None
        if text and text not in description_parts:
            description_parts.append(text)
    contact = selector_text(page, "main .jobs-full .field--name-field-contact")
    location = normalize_swiss_location(contact)
    apply_path = optional_text(page.css("main .jobs-full a.jobs-button::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    if not title or not description_parts or not location or not is_fisba_apply_url(apply_url):
        raise FisbaParseError("FISBA detail page contains an incomplete or non-Swiss vacancy")

    return {
        "id": page_id,
        "title": title,
        "company": "FISBA AG",
        "location": location,
        "apply_url": apply_url,
        "description": "\n\n".join(description_parts),
    }


def normalize_swiss_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    compact = re.sub(r"[^a-z]", "", text.casefold())
    if "stgallen" not in compact:
        return None
    return "St. Gallen, Switzerland"


def is_fisba_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "fisba-job.abacuscity.ch"
        and parts.path.startswith("/de/job")
    )


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1).casefold() if match else None


def extract_employment_type(
    title: str | None,
    catalog_section: str | None,
) -> str | None:
    if catalog_section == "apprenticeship":
        return "Apprenticeship"
    match = re.search(r"(?<!\d)(\d{1,3}\s*%)", title or "")
    return re.sub(r"\s+", "", match.group(1)) if match else None


def deduplicate_fisba_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = extract_job_id(job.url)
        key = job_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


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
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None
