from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

INFOSOFT_JOBS_URL = "https://infosoft.swiss/karriere/"
INFOSOFT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Infosoft Systems AG"
EXPECTED_SITE_NAME = "Infosoft Systems AG"
EXPECTED_LANGUAGE = "de-DE"
EXPECTED_SCHEMA_LANGUAGE = "de"
EXPECTED_CITY = "Luzern"
EXPECTED_LOCATION = "Luzern, Switzerland"
EXPECTED_EMAIL = "bewerbung@infosoft.swiss"
EXPECTED_ADDRESS_PARTS = ("Winkelriedstrasse 35", "CH-6003 Luzern")
EXPECTED_DETAIL_SECTIONS = {
    "Das sind deine Aufgaben",
    "Das bringst du mit",
    "Wir bieten dir",
}
JOB_PATH_PATTERN = re.compile(r"^/karriere/([a-z0-9]+(?:-[a-z0-9]+)*)/?$")
LISTING_TITLE_PATTERN = re.compile(
    r"^(?P<title>.+?)\s+[–-]\s+(?P<lower>\d{1,3})\s*%\s+bis\s+"
    r"(?P<upper>\d{1,3})\s*%\s+in\s+(?P<city>.+)$",
    re.IGNORECASE,
)
DETAIL_META_PATTERN = re.compile(
    r"^(?P<lower>\d{1,3})\s*[–-]\s*(?P<upper>\d{1,3})\s*%\s*\|\s*"
    r"(?P<city>.+)$"
)


class InfosoftParseError(DirectCompanyRequestError):
    pass


class InfosoftJobsParser:
    """Collect Infosoft Systems AG's complete server-rendered vacancy catalog."""

    parser_id = "infosoft"

    def __init__(
        self,
        *,
        base_url: str = INFOSOFT_JOBS_URL,
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
                headers={**INFOSOFT_HEADERS, "Referer": self.base_url},
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
        except InfosoftParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Infosoft vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Infosoft vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_infosoft_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Infosoft Switzerland vacancies from the "
                "official catalog"
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
                    expected_workload=record["employment_type"],
                    expected_location=record["location"],
                )
            except (httpx.HTTPError, InfosoftParseError, ValueError) as exc:
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
                optional_text(detail.get("location"))
                or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(
                optional_text(detail.get("employment_type"))
                or optional_text(record.get("employment_type"))
            ),
            seniority=None,
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("summary"))
            ),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise InfosoftParseError("Infosoft listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    validate_company_address(page)
    catalog_sections = [
        section
        for section in page.css("main section")
        if unique_selector_texts(section, ":scope > h2") == {"offene Stellen"}
    ]
    if len(catalog_sections) != 1:
        raise InfosoftParseError("Infosoft listing is missing its vacancy catalog")
    cards = catalog_sections[0].css(":scope > div > .grid-card-box-shadow")
    if not cards:
        raise InfosoftParseError("Infosoft listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        paragraphs = card.css(":scope > p")
        links = card.css(":scope > a.link-with-arrow")
        if len(paragraphs) != 2 or len(links) != 1:
            raise InfosoftParseError("Infosoft listing contains an incomplete vacancy")
        listing_title = html_to_text(paragraphs[0].get())
        summary = html_to_text(paragraphs[1].get())
        metadata = parse_listing_title(listing_title)
        detail_url = urljoin(
            page_url,
            optional_text(links[0].attrib.get("href")) or "",
        )
        job_id = extract_job_id(detail_url, expected_host=expected_host)
        if (
            metadata is None
            or not summary
            or not job_id
            or job_id in seen_ids
        ):
            raise InfosoftParseError("Infosoft listing contains an invalid vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": metadata["title"],
                "listing_title": listing_title,
                "company": EXPECTED_COMPANY,
                "location": metadata["location"],
                "employment_type": metadata["employment_type"],
                "summary": summary,
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
    expected_workload: str,
    expected_location: str,
) -> dict[str, Any]:
    expected_host = urlsplit(expected_url).netloc.casefold()
    if (
        not same_url(page_url, expected_url)
        or extract_job_id(page_url, expected_host=expected_host) != expected_job_id
    ):
        raise InfosoftParseError("Infosoft detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    validate_company_address(page)
    hero_articles = page.css("main .reversed-photo-article article")
    descriptions = page.css("main > article")
    if len(hero_articles) != 1 or len(descriptions) != 1:
        raise InfosoftParseError("Infosoft detail page contains an incomplete vacancy")

    hero = hero_articles[0]
    titles = unique_selector_texts(hero, ":scope > h3")
    metadata_values = unique_selector_texts(hero, ":scope > h4")
    summaries = unique_selector_texts(hero, ":scope > p")
    title = next(iter(titles)) if len(titles) == 1 else None
    metadata = (
        parse_detail_metadata(next(iter(metadata_values)))
        if len(metadata_values) == 1
        else None
    )
    summary = next(iter(summaries)) if len(summaries) == 1 else None

    description_headings = unique_selector_texts(descriptions[0], ":scope > div > h5")
    description_parts = [
        value
        for node in descriptions[0].css(":scope > div > h5, :scope > div > p")
        if (value := html_to_text(node.get()))
    ]
    description = optional_multiline_text(
        "\n\n".join(value for value in [summary, *description_parts] if value)
    )
    apply_urls = {
        value
        for raw in page.css('main a[href^="mailto:"]::attr(href)').getall()
        if (value := optional_text(raw)) and is_apply_url(value)
    }
    schema = parse_webpage_schema(page, expected_url=expected_url)
    if (
        not title
        or title_fingerprint(title) != title_fingerprint(expected_title)
        or metadata is None
        or metadata["employment_type"] != expected_workload
        or metadata["location"] != expected_location
        or description_headings != EXPECTED_DETAIL_SECTIONS
        or not description
        or len(apply_urls) != 1
        or schema is None
    ):
        raise InfosoftParseError("Infosoft detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": metadata["location"],
        "apply_url": apply_urls.pop(),
        "posted_at": schema["datePublished"],
        "employment_type": metadata["employment_type"],
        "description": description,
    }


def parse_listing_title(value: Any) -> dict[str, str] | None:
    text = optional_text(value)
    match = LISTING_TITLE_PATTERN.fullmatch(text or "")
    if not match:
        return None
    workload = normalize_workload(match.group("lower"), match.group("upper"))
    location = normalize_location(match.group("city"))
    title = optional_text(match.group("title"))
    if not workload or not location or not title:
        return None
    return {
        "title": title,
        "employment_type": workload,
        "location": location,
    }


def parse_detail_metadata(value: Any) -> dict[str, str] | None:
    text = optional_text(value)
    match = DETAIL_META_PATTERN.fullmatch(text or "")
    if not match:
        return None
    workload = normalize_workload(match.group("lower"), match.group("upper"))
    location = normalize_location(match.group("city"))
    if not workload or not location:
        return None
    return {"employment_type": workload, "location": location}


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
    organization_name = comparable_text(organizations[0].get("name"))
    if (
        not same_url(webpage.get("url"), expected_url)
        or webpage.get("inLanguage") != EXPECTED_SCHEMA_LANGUAGE
        or optional_text(webpage.get("datePublished")) is None
        or organization_name not in {"infosoft", comparable_text(EXPECTED_COMPANY)}
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
        raise InfosoftParseError("Infosoft page has an unexpected identity")


def validate_company_address(page: Selector) -> None:
    footers = page.css("footer")
    footer_text = html_to_text(footers[0].get()) if len(footers) == 1 else None
    if not footer_text or not all(part in footer_text for part in EXPECTED_ADDRESS_PARTS):
        raise InfosoftParseError("Infosoft page is missing its Swiss company identity")


def normalize_workload(lower_value: Any, upper_value: Any) -> str | None:
    try:
        lower, upper = int(str(lower_value)), int(str(upper_value))
    except (TypeError, ValueError):
        return None
    return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None


def normalize_location(value: Any) -> str | None:
    city = optional_text(value)
    return EXPECTED_LOCATION if comparable_text(city) == comparable_text(EXPECTED_CITY) else None


def is_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    subjects = query.get("subject", [])
    return (
        parts.scheme.casefold() == "mailto"
        and parts.path.casefold() == EXPECTED_EMAIL
        and set(query) == {"subject"}
        and len(subjects) == 1
        and comparable_text(subjects[0]).startswith("bewerbung als ")
        and not parts.fragment
    )


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


def deduplicate_infosoft_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
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
