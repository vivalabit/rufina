from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

CENTRIS_JOBS_URL = "https://www.centrisag.ch/karriere/jobs"
CENTRIS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/(\d+)$")
APPLY_PATH_PATTERN = re.compile(
    r"^/Vacancies/(\d+)/Application/CheckLogin/1$",
    re.IGNORECASE,
)
LISTING_META_PATTERN = re.compile(
    r"^(\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%)\s+in\s+(.+)$",
    re.IGNORECASE,
)
POSTED_LABEL_PATTERN = re.compile(
    r"^online\s+seit:\s*(\d{2}\.\d{2}\.\d{4})$",
    re.IGNORECASE,
)
EXPECTED_COMPANY = "Centris AG"
EXPECTED_LOCATION = "Solothurn/Hybrid"


class CentrisParseError(DirectCompanyRequestError):
    pass


class CentrisJobsParser:
    """Collect Centris AG's complete server-rendered Swiss vacancy catalog."""

    parser_id = "centris"

    def __init__(
        self,
        *,
        base_url: str = CENTRIS_JOBS_URL,
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
                headers={**CENTRIS_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                )
                self.enrich_records(client, records)
        except CentrisParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Centris vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Centris vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_centris_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Centris Switzerland vacancies from the official catalog"
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
                    expected_url=record["url"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                    expected_posted_at=record["posted_at"],
                    expected_listing_meta=record["listing_meta"],
                )
            except (httpx.HTTPError, CentrisParseError, ValueError) as exc:
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
            location=(
                optional_text(detail.get("location")) or format_location(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
            ),
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
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise CentrisParseError("Centris listing returned an unexpected page")

    page = Selector(page_html)
    container = page.css(".container-dynamic-content-joblist")
    cards = container.css("ul.linklist > li")
    if len(container) != 1 or not cards:
        raise CentrisParseError("Centris listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        links = {
            optional_text(value)
            for value in card.css(":scope > a::attr(href)").getall()
            if optional_text(value)
        }
        title = selector_text(card, "h5")
        text_rows = [value for raw in card.css("p::text").getall() if (value := optional_text(raw))]
        if len(links) != 1 or len(text_rows) != 2 or not title:
            raise CentrisParseError("Centris listing contains an incomplete vacancy")
        detail_url = urljoin(page_url, next(iter(links)))
        job_id = extract_job_id(detail_url)
        posted_at = parse_posted_label(text_rows[0])
        listing_meta = text_rows[1]
        workload, location = parse_listing_meta(listing_meta)
        if (
            not job_id
            or not posted_at
            or not workload
            or location != EXPECTED_LOCATION
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise CentrisParseError("Centris listing contains incomplete or non-Swiss vacancy data")
        if job_id in seen_ids:
            raise CentrisParseError("Centris listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "posted_at": posted_at,
                "workload": workload,
                "location": location,
                "listing_meta": listing_meta,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_posted_at: str,
    expected_listing_meta: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_job_id:
        raise CentrisParseError("Centris detail page returned a different vacancy")

    page = Selector(page_html)
    titles = unique_selector_texts(page, "header.header-blog h1")
    listing_meta = selector_text(page, "header.header-blog p.lead")
    workload, location = parse_listing_meta(listing_meta)
    schemas = list(extract_json_schemas(page))
    website_schemas = [item for item in schemas if item.get("@type") == "WebSite"]
    company_schemas = [item for item in schemas if item.get("@type") == "Corporation"]
    if len(website_schemas) != 1 or len(company_schemas) != 1:
        raise CentrisParseError("Centris detail page is missing its structured data")
    website = website_schemas[0]
    company = company_schemas[0]
    posted_at = normalize_iso_date(website.get("datePublished"))
    apply_urls = {
        normalized
        for value in page.css("main a::attr(href)").getall()
        if (
            normalized := normalize_apply_url(
                urljoin(page_url, str(value)),
                expected_job_id=expected_job_id,
            )
        )
    }
    description = extract_description(page)
    if (
        titles != {optional_text(expected_title)}
        or listing_meta != optional_text(expected_listing_meta)
        or not workload
        or location != EXPECTED_LOCATION
        or optional_text(website.get("name")) != optional_text(expected_title)
        or not same_url(website.get("url"), expected_url)
        or posted_at != expected_posted_at
        or optional_text(company.get("name")) != EXPECTED_COMPANY
        or not same_url(company.get("url"), "https://www.centrisag.ch/")
        or len(apply_urls) != 1
        or not description
    ):
        raise CentrisParseError("Centris detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": format_location(location),
        "workload": workload,
        "apply_url": next(iter(apply_urls)),
        "posted_at": posted_at,
        "description": description,
        "structured_data": website,
    }


def extract_description(page: Selector) -> str | None:
    selectors = (
        "main .container-headline h2, "
        "main .container-text p, "
        "main .container-factbox h2, "
        "main .container-factbox h4, "
        "main .container-factbox .umantis"
    )
    parts: list[str] = []
    for node in page.css(selectors):
        value = html_to_text(node.get())
        if value == "Deine Benefits":
            break
        if value and value not in parts:
            parts.append(value)
    return optional_multiline_text("\n\n".join(parts))


def extract_json_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(html.unescape(str(raw)))
        except (TypeError, json.JSONDecodeError):
            continue
        yield from walk_json(payload)


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_posted_label(value: Any) -> str | None:
    text = optional_text(value)
    match = POSTED_LABEL_PATTERN.fullmatch(text or "")
    if not match:
        return None
    day, month, year = match.group(1).split(".")
    return f"{year}-{month}-{day}"


def parse_listing_meta(value: Any) -> tuple[str | None, str | None]:
    text = optional_text(value)
    match = LISTING_META_PATTERN.fullmatch(text or "")
    if not match:
        return None, None
    workload = re.sub(r"\s*[-–]\s*", "–", match.group(1))
    return workload, optional_text(match.group(2))


def format_location(value: Any) -> str | None:
    text = optional_text(value)
    return f"{text}, Switzerland" if text else None


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T.*)?", text or "")
    return match.group(1) if match else None


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1) if match else None


def is_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and extract_job_id(text) is not None
        and not parts.query
        and not parts.fragment
    )


def normalize_apply_url(value: Any, *, expected_job_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "recruitingapp-2824.umantis.com"
        or not match
        or match.group(1) != expected_job_id
        or parse_qs(parts.query, keep_blank_values=True) != {"lang": ["ger"]}
        or parts.fragment
    ):
        return None
    return text


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


def deduplicate_centris_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
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
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    normalized = optional_multiline_text(text)
    return re.sub(r"\n\n(?=- )", "\n", normalized) if normalized else None


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
