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

LOGOBJECT_JOBS_URL = "https://logobject.com/karriere"
LOGOBJECT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/karriere/[a-z0-9][a-z0-9/-]*/?$")
JOB_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SWISS_LOCATION_PATTERN = re.compile(r"^(.+?)\s*\(Schweiz\)$", re.IGNORECASE)
FOREIGN_LOCATION_PATTERN = re.compile(
    r"^.+?\s*\((?:Deutschland|Germany|Italien|Italy)\)$",
    re.IGNORECASE,
)
WORKLOAD_RANGE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,3})\s*%\s*[-–]\s*(\d{1,3})\s*%",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*%", re.IGNORECASE)


class LogObjectParseError(DirectCompanyRequestError):
    pass


class LogObjectJobsParser:
    """Collect the complete Swiss subset of LogObject's official TYPO3 catalog."""

    parser_id = "logobject"

    def __init__(
        self,
        *,
        base_url: str = LOGOBJECT_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=LOGOBJECT_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_base_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except LogObjectParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("LogObject vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("LogObject vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_logobject_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} LogObject Switzerland vacancies from the "
                "complete official catalog"
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
                response = client.get(
                    record["url"],
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, LogObjectParseError, ValueError) as exc:
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
        title = optional_text(record.get("title")) or optional_text(detail.get("title"))
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company="LogObject AG",
            location=optional_text(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            employment_type=optional_text(detail.get("employment_type")),
            seniority=extract_seniority(title),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_base_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if canonical_url(page_url) != canonical_url(expected_base_url):
        raise LogObjectParseError("LogObject catalog redirected to an unexpected page")

    page = Selector(page_html)
    catalog = page.css("main section.section--career .career-list")
    cards = catalog.css(".career-item") if catalog.get() else []
    if not catalog.get() or not cards:
        raise LogObjectParseError("LogObject listing is missing its vacancy catalog")
    if len(cards) > max_jobs:
        raise LogObjectParseError(
            f"LogObject exposes {len(cards)} vacancies, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        title = selector_text(card, ".career-title")
        location_label = selector_text(card, ".career-subtitle")
        href = optional_text(card.css("a.absolute-link::attr(href)").get())
        detail_url = canonical_url(urljoin(page_url, href)) if href else None
        job_id = extract_job_id(detail_url, expected_base_url=expected_base_url)
        location = normalize_swiss_location(location_label)
        is_foreign = bool(location_label and FOREIGN_LOCATION_PATTERN.fullmatch(location_label))
        if (
            not title
            or not location_label
            or not detail_url
            or not job_id
            or (not location and not is_foreign)
        ):
            raise LogObjectParseError(
                "LogObject listing contains an incomplete vacancy or unknown country"
            )
        if job_id in seen_ids:
            raise LogObjectParseError("LogObject listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        if is_foreign:
            continue
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": location,
                "location_label": location_label,
                "url": detail_url,
                "listing_page_url": canonical_url(page_url),
                "total_available": len(cards),
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
) -> dict[str, Any]:
    page = Selector(page_html)
    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    public_url = canonical_url(urljoin(page_url, canonical)) if canonical else None
    if canonical_url(page_url) != canonical_url(expected_url) or public_url != canonical_url(
        expected_url
    ):
        raise LogObjectParseError("LogObject detail page returned a different vacancy")

    title = selector_text(page, "main .breadcrumb-item.current") or selector_text(
        page, "main section.section-header h1"
    )
    if not title or comparable_text(title) != comparable_text(expected_title):
        raise LogObjectParseError("LogObject detail page returned a different vacancy title")

    description_parts: list[str] = []
    for section in page.css(
        "main section.section--intro, main section.section-text, "
        "main section.section-contact"
    ):
        text = html_to_text(section.get())
        if text and text not in description_parts:
            description_parts.append(text)
    if not description_parts:
        raise LogObjectParseError("LogObject detail page is missing its description")

    apply_urls = {
        optional_text(value)
        for value in page.css('main a[href^="mailto:"]::attr(href)').getall()
        if optional_text(value) == "mailto:jobs@logobject.ch"
    }
    if len(apply_urls) != 1:
        raise LogObjectParseError("LogObject detail page is missing its official apply email")

    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    description = "\n\n".join(description_parts)
    return {
        "id": extract_job_id(public_url, expected_base_url=expected_url),
        "title": title,
        "public_url": public_url,
        "apply_url": apply_urls.pop(),
        "employment_type": extract_workload(title, og_title, description),
        "description": description,
    }


def extract_job_id(value: str | None, *, expected_base_url: str) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    expected = urlsplit(expected_base_url)
    if (
        parts.scheme != "https"
        or parts.netloc != expected.netloc
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.path.rstrip("/") == "/karriere"
    ):
        return None
    job_id = parts.path.removeprefix("/karriere/").strip("/").replace("/", "-")
    return job_id if JOB_ID_PATTERN.fullmatch(job_id) else None


def normalize_swiss_location(value: str | None) -> str | None:
    if not value:
        return None
    match = SWISS_LOCATION_PATTERN.fullmatch(value)
    city = optional_text(match.group(1)) if match else None
    return f"{city}, Switzerland" if city else None


def extract_workload(*values: str | None) -> str | None:
    text = " ".join(value for value in values if value)
    range_match = WORKLOAD_RANGE_PATTERN.search(text)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}%"
    match = WORKLOAD_PATTERN.search(text)
    return f"{match.group(1)}%" if match else None


def extract_seniority(title: str | None) -> str | None:
    value = (title or "").casefold()
    if "senior" in value:
        return "Senior"
    if "junior" in value:
        return "Junior"
    if "praktik" in value or "intern" in value:
        return "Internship"
    return None


def deduplicate_logobject_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def comparable_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").replace("\u00ad", "").casefold())


def selector_text(node: Any, selector: str) -> str | None:
    return optional_text(" ".join(str(value) for value in node.css(f"{selector} ::text").getall()))


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"(?is)<(script|style|picture|figure)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = (
        str(value)
        .replace("\u00ad", "")
        .replace("\u200b", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u00ad\u200b]+", " ", str(value)).strip()
    return normalized or None
