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

INFOGUARD_JOBS_URL = "https://www.infoguard.ch/en/career"
INFOGUARD_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
SWISS_JOB_PATH_PATTERN = re.compile(r"^/de/(?:de/)?karriere/([a-z0-9]+(?:-[a-z0-9]+)*)$")
GERMAN_JOB_PATH_PATTERN = re.compile(r"^/de/karriere/de/([a-z0-9]+(?:-[a-z0-9]+)*)$")
APPLY_PATH_PATTERN = re.compile(r"^/job/([a-z0-9]{8})$")
WORKLOAD_PATTERN = re.compile(r"^\d{1,3}(?:\s*[-–]\s*\d{1,3})?%$")
EXPECTED_COMPANY = "InfoGuard AG"
EXPECTED_LOCATION = "Baar"
EXPECTED_COUNTRIES = {"switzerland", "germany"}


class InfoGuardParseError(DirectCompanyRequestError):
    pass


class InfoGuardJobsParser:
    """Collect InfoGuard AG's complete server-rendered Swiss vacancy catalog."""

    parser_id = "infoguard"

    def __init__(
        self,
        *,
        base_url: str = INFOGUARD_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**INFOGUARD_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records, catalog_size = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                )
                self.enrich_records(client, records)
        except InfoGuardParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("InfoGuard vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("InfoGuard vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_infoguard_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} InfoGuard Switzerland vacancies from "
                f"{catalog_size} official catalog records"
            ),
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
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
                    expected_title=record["title"],
                    expected_location=record["location"],
                    expected_workload=record["workload"],
                )
            except (httpx.HTTPError, InfoGuardParseError, ValueError) as exc:
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
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=format_location(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=None,
            employment_type=optional_text(record.get("workload")),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> tuple[list[dict[str, Any]], int]:
    if not same_url(page_url, expected_url):
        raise InfoGuardParseError("InfoGuard listing returned an unexpected page")

    page = Selector(page_html)
    containers = page.css(".jobs")
    cards = containers.css('[class*="_career-section__jobs_"] > a')
    if len(containers) != 1 or not cards:
        raise InfoGuardParseError("InfoGuard listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        rows = card.css(":scope > [data-country]")
        country = optional_text(rows[0].attrib.get("data-country")) if len(rows) == 1 else None
        detail_url = urljoin(page_url, optional_text(card.attrib.get("href")) or "")
        job_id = extract_job_id(detail_url, country=country)
        title = selector_text(card, '[class*="_job-row__title_"]')
        category = selector_text(card, '[class*="_job-row__category_"]')
        tags = [
            value
            for node in card.css('[class*="_job-row__tags_"] > div:not([class*="_icon_"])')
            if (value := html_to_text(node.get()))
        ]
        if (
            country not in EXPECTED_COUNTRIES
            or not job_id
            or not title
            or not category
            or len(tags) != 2
            or not is_company_job_url(
                detail_url,
                expected_host=expected_host,
                country=country,
            )
        ):
            raise InfoGuardParseError(
                "InfoGuard listing contains incomplete or invalid vacancy data"
            )
        location, workload = tags
        if country == "germany":
            continue
        if location != EXPECTED_LOCATION or not WORKLOAD_PATTERN.fullmatch(workload):
            raise InfoGuardParseError(
                "InfoGuard listing contains incomplete or non-Swiss vacancy data"
            )
        if job_id in seen_ids:
            raise InfoGuardParseError("InfoGuard listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "category": category,
                "country": country,
                "location": location,
                "workload": normalize_workload(workload),
                "url": detail_url,
                "listing_page_url": page_url,
                "source_catalog_size": len(cards),
            }
        )
    if not records:
        raise InfoGuardParseError("InfoGuard listing is missing its Swiss vacancy catalog")
    return records, len(cards)


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_location: str,
    expected_workload: str,
) -> dict[str, Any]:
    if (
        not same_url(page_url, expected_url)
        or extract_job_id(page_url, country="switzerland") != expected_job_id
    ):
        raise InfoGuardParseError("InfoGuard detail page returned a different vacancy")

    page = Selector(page_html)
    canonicals = {
        urljoin(page_url, value)
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    titles = unique_selector_texts(page, ".job_detail_main h1")
    facts = [
        value
        for node in page.css('[class*="_hero-job__facts_"] > div .h4')
        if (value := html_to_text(node.get()))
    ]
    apply_urls = {
        normalized
        for raw in page.css(".job_detail_main a::attr(href)").getall()
        if (normalized := normalize_apply_url(raw))
    }
    description = extract_description(page)
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals), None), expected_url)
        or titles != {expected_title}
        or len(facts) != 4
        or facts[0] != expected_location
        or normalize_workload(facts[1]) != expected_workload
        or not facts[2]
        or not facts[3]
        or len(apply_urls) != 1
        or not description
    ):
        raise InfoGuardParseError("InfoGuard detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": format_location(expected_location),
        "workload": expected_workload,
        "workplace_type": facts[2],
        "start": facts[3],
        "apply_url": next(iter(apply_urls)),
        "description": description,
    }


def extract_description(page: Selector) -> str | None:
    sections: dict[str, str] = {}
    for section in page.css(".job_detail_main section"):
        heading = selector_text(section, "h2") or selector_text(section, "h3")
        if heading in {"Dein Job", "Skill Check"}:
            value = html_to_text(section.get())
            if value:
                sections[heading] = value
    if set(sections) != {"Dein Job", "Skill Check"}:
        return None
    return optional_multiline_text(f"{sections['Dein Job']}\n\n{sections['Skill Check']}")


def extract_job_id(value: Any, *, country: str | None) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    pattern = GERMAN_JOB_PATH_PATTERN if country == "germany" else SWISS_JOB_PATH_PATTERN
    match = pattern.fullmatch(urlsplit(text).path.rstrip("/"))
    return match.group(1) if match else None


def is_company_job_url(
    value: Any,
    *,
    expected_host: str,
    country: str,
) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and extract_job_id(text, country=country) is not None
        and not parts.query
        and not parts.fragment
    )


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "infoguard-ag.onlyfy.jobs"
        or not APPLY_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return text


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    return re.sub(r"\s*[-–]\s*", "–", text) if text else None


def format_location(value: Any) -> str | None:
    text = optional_text(value)
    return f"{text}, Switzerland" if text else None


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and not actual.query
        and not actual.fragment
        and not target.query
        and not target.fragment
    )


def deduplicate_infoguard_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url, country="switzerland") or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_selector_texts(page: Selector, css: str) -> set[str]:
    return {value for raw in page.css(css).getall() if (value := html_to_text(str(raw)))}


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


def html_to_text(value: Any) -> str | None:
    text = str(value or "")
    if not text:
        return None
    text = re.sub(r'(?is)<div[^>]+class="[^"]*_icon_[^"]*"[^>]*>.*?</div>\s*</div>', "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|span|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return optional_multiline_text(text)


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
