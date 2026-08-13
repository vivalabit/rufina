from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AMETIQ_JOBS_URL = "https://ametiq.ch/jobs/"
AMETIQ_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "amétiq ag"
EXPECTED_SITE_NAME = "amétiq medical"
EXPECTED_LOCATION = "Pfäffikon SZ, Switzerland"
EXPECTED_LANGUAGE = "de-CH"
EXPECTED_APPLY_URLS = {
    "mailto:bewerbungen@ametiq.ch",
    "mailto:lehrstellen@ametiq.ch",
}
EXPECTED_ADDRESS_PARTS = ("amétiq ag", "bahnhofstrasse 1", "8808 pfäffikon sz")
JOB_PATH_PATTERN = re.compile(r"^/job/([a-z0-9]+(?:-[a-z0-9]+)*)/?$")
POST_ID_PATTERN = re.compile(r"^uael-post-(\d+)$")
WORKLOAD_RANGE_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%(?!\d)")
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*%(?!\d)")


class AmetiqParseError(DirectCompanyRequestError):
    pass


class AmetiqJobsParser:
    """Collect amétiq's complete server-rendered Swiss vacancy catalog."""

    parser_id = "ametiq"

    def __init__(
        self,
        *,
        base_url: str = AMETIQ_JOBS_URL,
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
                headers={**AMETIQ_HEADERS, "Referer": self.base_url},
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
        except AmetiqParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("amétiq vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("amétiq vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ametiq_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} amétiq Switzerland vacancies from the official catalog"),
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
                )
            except (httpx.HTTPError, AmetiqParseError, ValueError) as exc:
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
            location=EXPECTED_LOCATION,
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=optional_text(record.get("employment_type")),
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
        raise AmetiqParseError("amétiq listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    headings = unique_selector_texts(page, "#open-jobs h2")
    catalogs = page.css("#open-jobs + .elementor-widget-uael-posts .uael-post-grid__inner")
    cards = catalogs[0].css(":scope > .uael-post-wrapper") if len(catalogs) == 1 else []
    if headings != {"Unsere Stellenangebote"} or not cards:
        raise AmetiqParseError("amétiq listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        titles = unique_selector_texts(card, ".uael-post__title")
        links = card.css("a.uael-post__read-more")
        if len(titles) != 1 or len(links) != 1:
            raise AmetiqParseError("amétiq listing contains an incomplete vacancy")

        link = links[0]
        aria_id = optional_text(link.attrib.get("aria-labelledby"))
        button_ids = {
            value
            for node in card.css(".elementor-button-text")
            if (value := optional_text(node.attrib.get("id")))
        }
        match = POST_ID_PATTERN.fullmatch(aria_id or "")
        detail_url = urljoin(page_url, optional_text(link.attrib.get("href")) or "")
        if (
            not match
            or button_ids != {aria_id}
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise AmetiqParseError("amétiq listing contains an invalid vacancy link")

        job_id = match.group(1)
        title = normalize_title(next(iter(titles)))
        if not title:
            raise AmetiqParseError("amétiq listing contains an invalid vacancy title")
        if job_id in seen_ids:
            raise AmetiqParseError("amétiq listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "slug": extract_job_slug(detail_url),
                "title": title,
                "company": EXPECTED_COMPANY,
                "location": EXPECTED_LOCATION,
                "employment_type": normalize_workload(title),
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
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or not extract_job_slug(page_url):
        raise AmetiqParseError("amétiq detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    body_classes = set((optional_text(page.css("body::attr(class)").get()) or "").split())
    expected_post_class = f"postid-{expected_job_id}"
    titles = unique_selector_texts(page, ".elementor-widget-theme-post-title h1")
    title = normalize_title(next(iter(titles))) if len(titles) == 1 else None
    description_nodes = page.css(
        ".elementor-widget-theme-post-content > .elementor-widget-container"
    )
    description = html_to_text(description_nodes[0].get()) if len(description_nodes) == 1 else None
    mailto_urls = {
        optional_text(value)
        for value in (
            description_nodes[0].css('a[href^="mailto:"]::attr(href)').getall()
            if len(description_nodes) == 1
            else []
        )
        if optional_text(value)
    }
    schema = parse_webpage_schema(page, expected_url=expected_url)
    address_text = comparable_text(description)
    if (
        expected_post_class not in body_classes
        or title != expected_title
        or not description
        or len(mailto_urls) != 1
        or not mailto_urls.issubset(EXPECTED_APPLY_URLS)
        or not all(value in address_text for value in EXPECTED_ADDRESS_PARTS)
        or schema is None
    ):
        raise AmetiqParseError("amétiq detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "apply_url": mailto_urls.pop(),
        "posted_at": schema["datePublished"],
        "description": description,
    }


def parse_webpage_schema(page: Selector, *, expected_url: str) -> dict[str, Any] | None:
    raw_values = page.css("script.yoast-schema-graph::text").getall()
    if len(raw_values) != 1:
        return None
    try:
        payload = json.loads(raw_values[0])
    except (json.JSONDecodeError, TypeError):
        return None
    graph = payload.get("@graph") if isinstance(payload, dict) else None
    if not isinstance(graph, list):
        return None
    pages = [item for item in graph if isinstance(item, dict) and item.get("@type") == "WebPage"]
    organizations = [
        item for item in graph if isinstance(item, dict) and item.get("@type") == "Organization"
    ]
    if len(pages) != 1 or len(organizations) != 1:
        return None
    webpage = pages[0]
    if (
        not same_url(webpage.get("url"), expected_url)
        or webpage.get("inLanguage") != EXPECTED_LANGUAGE
        or optional_text(webpage.get("datePublished")) is None
        or comparable_text(organizations[0].get("name")) != comparable_text(EXPECTED_COMPANY)
    ):
        return None
    return webpage


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    canonicals = {
        value
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    site_names = {
        value
        for raw in page.css('meta[property="og:site_name"]::attr(content)').getall()
        if (value := optional_text(raw))
    }
    languages = {
        value for raw in page.css("html::attr(lang)").getall() if (value := optional_text(raw))
    }
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or site_names != {EXPECTED_SITE_NAME}
        or languages != {EXPECTED_LANGUAGE}
    ):
        raise AmetiqParseError("amétiq page has an unexpected identity")


def normalize_title(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    return optional_text(re.sub(r"^amétiq medical\s*[-–]\s*", "", text, flags=re.IGNORECASE))


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if match := WORKLOAD_RANGE_PATTERN.search(text):
        lower, upper = (int(item) for item in match.groups())
        return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None
    if match := WORKLOAD_PATTERN.search(text):
        workload = int(match.group(1))
        return f"{workload}%" if 1 <= workload <= 100 else None
    return None


def extract_job_slug(value: Any) -> str | None:
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
        and JOB_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.query
        and not parts.fragment
    )


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == "https"
        and actual.scheme == target.scheme
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and actual.query == target.query
        and not actual.fragment
    )


def deduplicate_ametiq_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or extract_job_slug(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {value for node in selector.css(css) if (value := html_to_text(node.get()))}


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|strong)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = optional_multiline_text(html.unescape(text).replace("\xa0", " "))
    return re.sub(r"(?m)(^- .*)\n\n(?=- )", r"\1\n", normalized) if normalized else None


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


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
