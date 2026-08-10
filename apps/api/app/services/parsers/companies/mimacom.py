from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

MIMACOM_JOBS_BASE_URL = "https://www.mimacom.com/jobs"
MIMACOM_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/jobs/([a-z0-9][a-z0-9-]*)/?$")
CATALOG_COUNT_PATTERN = re.compile(r"\b(\d+)\s+jobs?\s+found\b", re.IGNORECASE)
WORKDAY_JOB_ID_PATTERN = re.compile(r"_(JR\d+)(?:/|$)", re.IGNORECASE)
EMPLOYMENT_RANGE_PATTERN = re.compile(
    r"\b(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%",
    re.IGNORECASE,
)


class MimacomParseError(DirectCompanyRequestError):
    pass


class MimacomJobsParser:
    """Collect Mimacom's complete HubSpot catalog and enrich every vacancy."""

    parser_id = "mimacom"

    def __init__(
        self,
        *,
        base_url: str = MIMACOM_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=MIMACOM_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except MimacomParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Mimacom vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Mimacom vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_mimacom_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Mimacom vacancies from the full HubSpot "
                "catalog with detail enrichment"
            ),
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
                    expected_slug=record["id"],
                    expected_title=optional_text(record.get("title")),
                )
            except (httpx.HTTPError, MimacomParseError, ValueError) as exc:
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

        raw = dict(record)
        raw["detail"] = detail
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="Mimacom",
            location=optional_text(detail.get("location")) or optional_text(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            employment_type=extract_employment_type(
                optional_text(detail.get("title")) or optional_text(record.get("title")),
                optional_text(detail.get("employment_type"))
                or optional_text(record.get("employment_type")),
            ),
            seniority=extract_seniority(
                optional_text(detail.get("title")) or optional_text(record.get("title"))
            ),
            description=optional_multiline_text(detail.get("description")),
            raw=raw,
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    page = Selector(page_html)
    catalog = page.css(".joblist_wrapper .tablist > ul")
    if not catalog.get():
        raise MimacomParseError("Mimacom listing page is missing its vacancy catalog")

    declared_total = extract_catalog_total(page)
    cards = catalog.css("li[data-location][data-category][data-employment]")
    if declared_total is None or declared_total != len(cards):
        raise MimacomParseError("Mimacom listing count does not match its rendered vacancy catalog")
    if declared_total > max_jobs:
        raise MimacomParseError(
            f"Mimacom exposes {declared_total} vacancies, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for card in cards:
        title = optional_text(" ".join(card.css(".job_title h4::text").getall()))
        href = optional_text(card.css(".inner_page_link a::attr(href)").get())
        detail_url = urljoin(page_url, href) if href else None
        slug = extract_job_slug(detail_url)
        location = normalize_location(card.attrib.get("data-location"))
        employment_type = optional_text(card.attrib.get("data-employment"))
        category = optional_text(card.attrib.get("data-category"))
        if (
            not slug
            or not title
            or not detail_url
            or not location
            or not employment_type
            or not category
        ):
            raise MimacomParseError("Mimacom listing contains an incomplete vacancy")
        if slug in seen_slugs:
            raise MimacomParseError("Mimacom listing contains duplicate vacancy IDs")
        seen_slugs.add(slug)
        records.append(
            {
                "id": slug,
                "title": title,
                "location": location,
                "employment_type": employment_type,
                "category": category,
                "url": detail_url,
                "listing_page_url": page_url,
                "total_available": declared_total,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_slug: str | None,
    expected_title: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    wrapper = page.css(".job_detail_new[data-attr]")
    if not wrapper.get():
        raise MimacomParseError("Mimacom detail page is missing its vacancy content")

    title = optional_text(" ".join(wrapper.css(".job_detail_hero h1::text").getall()))
    canonical = optional_text(page.css('meta[property="og:url"]::attr(content)').get())
    public_url = canonical_url(urljoin(page_url, canonical) if canonical else page_url)
    slug = extract_job_slug(public_url)
    apply_url = optional_text(wrapper.css(".job_detail_header_btn a::attr(href)").get())
    workday_job_id = extract_workday_job_id(apply_url)
    facts = [
        text
        for node in wrapper.css(".job_detail_hero_box li > .text")
        if (text := optional_text(" ".join(node.css("::text").getall())))
    ]
    location = facts[0] if facts else None
    employment_type = facts[1] if len(facts) > 1 else None

    if (
        not slug
        or not title
        or not apply_url
        or not workday_job_id
        or not location
        or not employment_type
    ):
        raise MimacomParseError("Mimacom detail page contains an incomplete vacancy")
    if expected_slug and slug != expected_slug:
        raise MimacomParseError("Mimacom detail page returned a different vacancy")
    if expected_title and title.casefold() != expected_title.casefold():
        raise MimacomParseError("Mimacom detail page returned a different vacancy title")

    description_sections: list[str] = []
    for card in wrapper.css(".job_detail_card_box"):
        heading = optional_text(" ".join(card.css("h3::text").getall()))
        body = html_to_text(card.css(".job_detail_description").get())
        if heading and body:
            description_sections.append(f"{heading}\n{body}")
    if not description_sections:
        raise MimacomParseError("Mimacom detail page is missing its description")

    return {
        "id": slug,
        "workday_job_id": workday_job_id,
        "title": title,
        "location": location,
        "employment_type": employment_type,
        "public_url": public_url,
        "apply_url": apply_url,
        "description": "\n\n".join(description_sections),
    }


def extract_catalog_total(page: Selector) -> int | None:
    value = optional_text(" ".join(page.css(".joblist_wrapper .search_result::text").getall()))
    if not value:
        return None
    match = CATALOG_COUNT_PATTERN.search(value)
    return int(match.group(1)) if match else None


def extract_job_slug(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1) if match else None


def extract_workday_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or not parts.netloc.endswith(".myworkdayjobs.com")
        or "/mimacom/job/" not in parts.path
    ):
        return None
    match = WORKDAY_JOB_ID_PATTERN.search(parts.path)
    return match.group(1).upper() if match else None


def canonical_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def normalize_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    values = [optional_text(item) for item in text.split(",")]
    return ", ".join(item for item in values if item) or None


def extract_employment_type(
    title: str | None,
    fallback: str | None,
) -> str | None:
    if title:
        match = EMPLOYMENT_RANGE_PATTERN.search(title)
        if match:
            return f"{match.group(1)}-{match.group(2)}%"
    return fallback


def extract_seniority(title: str | None) -> str | None:
    if not title:
        return None
    normalized = title.casefold()
    if "senior" in normalized or "expert" in normalized:
        return "Senior"
    if "junior" in normalized:
        return "Entry level"
    return None


def deduplicate_mimacom_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
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
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
