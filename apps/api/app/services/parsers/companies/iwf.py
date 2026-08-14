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

IWF_JOBS_URL = "https://www.iwf.ch/web-solutions/jobs"
IWF_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "IWF AG"
EXPECTED_SITE_NAME = "IWF AG"
EXPECTED_LANGUAGE = "de"
EXPECTED_SCHEMA_LANGUAGE = "de-ch"
EXPECTED_LOCATION = "Pratteln, Switzerland"
EXPECTED_EMAIL = "jobs@web-solutions.io"
EXPECTED_LOGO_PATH = "/assets/content/logos/logo_iwf_ws.svg"
EXPECTED_ADDRESS_PARTS = (
    "IWF AG",
    "c/o Haus der Wirtschaft",
    "Hardstrasse 1",
    "CH-4133 Pratteln",
    "+41 61 927 64 76",
)
EXPECTED_LISTING_TITLE = "Arbeiten bei der IWF Web Solutions"
JOB_PATH_PATTERN = re.compile(r"^/web-solutions/jobs/([a-z0-9]+(?:-[a-z0-9]+)*)/?$")
DATE_TIME_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})T")


class IwfParseError(DirectCompanyRequestError):
    pass


class IwfJobsParser:
    """Collect IWF AG's complete server-rendered Web Solutions job catalog."""

    parser_id = "iwf"

    def __init__(
        self,
        *,
        base_url: str = IWF_JOBS_URL,
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
                headers={**IWF_HEADERS, "Referer": self.base_url},
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
        except IwfParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("IWF vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("IWF vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_iwf_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} IWF Switzerland vacancies from the official catalog"),
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
                response = client.get(
                    record["url"],
                    headers={"Referer": record["listing_page_url"]},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, IwfParseError, ValueError) as exc:
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
            employment_type=None,
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
        raise IwfParseError("IWF listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    validate_company_identity(page)
    catalog_sections = [
        section
        for section in page.css("main section#main")
        if unique_selector_texts(section, ":scope .container > .row:first-child h1")
        == {EXPECTED_LISTING_TITLE}
    ]
    if len(catalog_sections) != 1:
        raise IwfParseError("IWF listing is missing its vacancy catalog")
    cards = catalog_sections[0].css(
        ":scope .container > .row.inner-top-xs > div.col-xs-12.col-sm-12.col-md-6"
    )
    if not cards:
        raise IwfParseError("IWF listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        titles = unique_selector_texts(card, ":scope .equalheight > h3.color-ws")
        links = card.css(":scope > a.btn.bg-ws[href]")
        images = card.css(":scope > .teaser-image > img.teaser-image")
        title = next(iter(titles)) if len(titles) == 1 else None
        detail_url = urljoin(
            page_url,
            optional_text(links[0].attrib.get("href")) if len(links) == 1 else "",
        )
        job_id = extract_job_id(detail_url, expected_host=expected_host)
        if (
            not title
            or len(images) != 1
            or not job_id
            or job_id in seen_ids
            or unique_selector_texts(links[0], ":scope") != {"Zum Job Profil"}
        ):
            raise IwfParseError("IWF listing contains an invalid vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": EXPECTED_COMPANY,
                "location": EXPECTED_LOCATION,
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
) -> dict[str, Any]:
    expected_host = urlsplit(expected_url).netloc.casefold()
    if (
        not same_url(page_url, expected_url)
        or extract_job_id(page_url, expected_host=expected_host) != expected_job_id
    ):
        raise IwfParseError("IWF detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    validate_company_identity(page)
    titles = unique_selector_texts(page, "main section#hero h1")
    contents = page.css("main > div.container.inner-bottom-xs.content")
    title = next(iter(titles)) if len(titles) == 1 else None
    description = html_to_text(contents[0].get()) if len(contents) == 1 else None
    apply_urls = {
        value
        for raw in contents.css('a[href^="mailto:"]::attr(href)').getall()
        if (value := optional_text(raw)) and is_apply_url(value)
    }
    schema = parse_webpage_schema(page, expected_url=expected_url)
    if (
        not title
        or not description
        or len(apply_urls) != 1
        or schema is None
        or title_fingerprint(title) != title_fingerprint(schema.get("headline"))
    ):
        raise IwfParseError("IWF detail page contains an incomplete vacancy")
    return {
        "id": expected_job_id,
        "title": optional_text(schema.get("headline")) or title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "apply_url": next(iter(apply_urls)),
        "posted_at": schema["posted_at"],
        "description": description,
    }


def parse_webpage_schema(page: Selector, *, expected_url: str) -> dict[str, Any] | None:
    schemas: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        graph = payload.get("@graph") if isinstance(payload, dict) else None
        if not isinstance(graph, list):
            continue
        schemas.extend(item for item in graph if isinstance(item, dict))
    pages = [item for item in schemas if item.get("@type") == "WebPage"]
    breadcrumbs = [item for item in schemas if item.get("@type") == "BreadcrumbList"]
    if len(pages) != 1 or len(breadcrumbs) != 1:
        return None
    webpage = pages[0]
    breadcrumb_items = breadcrumbs[0].get("itemListElement")
    first_breadcrumb = (
        breadcrumb_items[0]
        if isinstance(breadcrumb_items, list)
        and breadcrumb_items
        and isinstance(breadcrumb_items[0], dict)
        else {}
    )
    published = optional_text(webpage.get("datePublished"))
    date_match = DATE_TIME_PATTERN.match(published or "")
    if (
        not same_url(webpage.get("url"), expected_url)
        or not same_url(webpage.get("mainEntityOfPage"), expected_url)
        or webpage.get("inLanguage") != EXPECTED_SCHEMA_LANGUAGE
        or not optional_text(webpage.get("headline"))
        or not date_match
        or not same_url(first_breadcrumb.get("item"), "https://www.iwf.ch")
        or optional_text(first_breadcrumb.get("name"))
        != "IWF AG - Full Service Agentur in Pratteln"
    ):
        return None
    return {**webpage, "posted_at": date_match.group(1)}


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    site_names = unique_attribute_values(
        page,
        'meta[property="og:site_name"]',
        "content",
    )
    languages = unique_attribute_values(page, "html", "lang")
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or len(og_urls) != 1
        or not same_url(next(iter(og_urls)), expected_url)
        or site_names != {EXPECTED_SITE_NAME}
        or languages != {EXPECTED_LANGUAGE}
    ):
        raise IwfParseError("IWF page has an unexpected identity")


def validate_company_identity(page: Selector) -> None:
    logos = unique_attribute_values(page, "header img.logo", "src")
    footers = page.css("footer#footer")
    footer_text = html_to_text(footers[0].get()) if len(footers) == 1 else None
    if (
        logos != {EXPECTED_LOGO_PATH}
        or not footer_text
        or not all(part in footer_text for part in EXPECTED_ADDRESS_PARTS)
    ):
        raise IwfParseError("IWF page is missing its Swiss company identity")


def extract_job_id(value: Any, *, expected_host: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def is_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme.casefold() == "mailto"
        and parts.path.casefold() == EXPECTED_EMAIL
        and not parts.query
        and not parts.fragment
    )


def title_fingerprint(value: Any) -> tuple[str, ...]:
    text = optional_text(value)
    tokens = re.findall(r"[^\W_]+", (text or "").casefold(), flags=re.UNICODE)
    return tuple(token for token in tokens if token != "in")


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


def deduplicate_iwf_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value for node in selector.css(css) if (value := optional_text(node.attrib.get(attribute)))
    }


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {value for node in selector.css(css) if (value := html_to_text(node.get()))}


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(
        r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|strong|section)>",
        "\n",
        text,
    )
    text = re.sub(r"<[^>]+>", "", text)
    normalized = optional_multiline_text(html.unescape(text).replace("\xa0", " "))
    return re.sub(r"(?m)(^- .*)\n\n(?=- )", r"\1\n", normalized) if normalized else None


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
