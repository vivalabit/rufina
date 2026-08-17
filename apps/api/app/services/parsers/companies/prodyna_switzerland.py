from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

PRODYNA_JOBS_URL = "https://www.prodyna.com/jobs?location=Zurich"
PRODYNA_RSS_URL = "https://www.prodyna.com/jobs/rss.xml"
PRODYNA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_DIVISION = "PRODYNA - Switzerland"
EXPECTED_LOCATION = "Zurich"
EXPECTED_COMPANY = "PRODYNA (Schweiz) AG"
DETAIL_PATH_PATTERN = re.compile(r"^/jobs/([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)$")
APPLY_PATH_PATTERN = re.compile(
    r"^/Vacancies/(\d+)/Application/CheckLogin/2$",
    re.IGNORECASE,
)


class ProdynaSwitzerlandParseError(DirectCompanyRequestError):
    pass


class ProdynaSwitzerlandJobsParser:
    """Collect PRODYNA's complete Zurich, Switzerland vacancy catalog."""

    parser_id = "prodyna_switzerland"

    def __init__(
        self,
        *,
        base_url: str = PRODYNA_JOBS_URL,
        rss_url: str = PRODYNA_RSS_URL,
        timeout_seconds: float = 30.0,
        max_catalog_records: int = 500,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url_from(base_url)
        self.rss_url = rss_url
        self.timeout_seconds = timeout_seconds
        self.max_catalog_records = max(1, max_catalog_records)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**PRODYNA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                listing_response = client.get(self.catalog_url)
                listing_response.raise_for_status()
                records = parse_listing_html(
                    listing_response.text,
                    page_url=str(listing_response.url),
                    expected_url=self.catalog_url,
                    max_catalog_records=self.max_catalog_records,
                )

                rss_response = client.get(self.rss_url)
                rss_response.raise_for_status()
                rss_records = parse_rss_xml(
                    rss_response.text,
                    page_url=str(rss_response.url),
                    expected_url=self.rss_url,
                    max_catalog_records=self.max_catalog_records,
                )
                reconcile_catalog(records, rss_records)
                for record in records:
                    record["rss"] = rss_records[record["url"]]

                global_total = len(records)
                records = select_zurich_records(records)
                self.enrich_records(client, records)
        except ProdynaSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("PRODYNA vacancy request failed") from exc
        except (ET.ParseError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("PRODYNA vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_prodyna_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} PRODYNA Zurich vacancies from "
                f"{global_total} reconciled global catalog records"
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
                    expected_slug=record["id"],
                    expected_title=record["title"],
                    expected_division=record["division"],
                    expected_location=record["location"],
                )
            except (httpx.HTTPError, ProdynaSwitzerlandParseError, ValueError) as exc:
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
        rss = record.get("rss")
        rss = rss if isinstance(rss, dict) else {}
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
            posted_at=optional_text(rss.get("posted_at")),
            employment_type=optional_text(detail.get("workload")),
            seniority=optional_text(detail.get("seniority")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_catalog_records: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise ProdynaSwitzerlandParseError("PRODYNA listing returned an unexpected page")
    page = Selector(page_html)
    canonicals = {
        optional_text(value)
        for value in page.css('link[rel="canonical"]::attr(href)').getall()
        if optional_text(value)
    }
    cards = page.css(".open-position-link")
    if canonicals != {expected_url} or not cards:
        raise ProdynaSwitzerlandParseError("PRODYNA listing is missing its vacancy catalog")
    if len(cards) > max_catalog_records:
        raise ProdynaSwitzerlandParseError(
            f"PRODYNA catalog exceeds the configured limit of {max_catalog_records} vacancies"
        )

    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for card in cards:
        title = selector_text(card, '[fs-cmsfilter-field="name"]')
        division = selector_text(card, '[fs-cmsfilter-field="division"]')
        category = selector_text(card, '[fs-cmsfilter-field="category"]')
        location = selector_text(card, '[fs-cmsfilter-field="location"]')
        links = {
            normalize_detail_url(urljoin(page_url, str(value)))
            for value in card.css("a.open-position-absolute-link::attr(href)").getall()
        }
        links.discard(None)
        if not title or not division or not category or not location or len(links) != 1:
            raise ProdynaSwitzerlandParseError("PRODYNA listing contains an incomplete vacancy")
        detail_url = next(iter(links))
        slug = extract_slug(detail_url)
        if not slug or detail_url in seen_urls:
            raise ProdynaSwitzerlandParseError(
                "PRODYNA listing contains duplicate or invalid vacancy URLs"
            )
        seen_urls.add(detail_url)
        records.append(
            {
                "id": slug,
                "title": title,
                "division": division,
                "category": category,
                "location": location,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_rss_xml(
    page_xml: str,
    *,
    page_url: str,
    expected_url: str,
    max_catalog_records: int,
) -> dict[str, dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise ProdynaSwitzerlandParseError("PRODYNA RSS returned an unexpected page")
    root = ET.fromstring(page_xml)
    channel = root.find("channel") if root.tag == "rss" else None
    if (
        root.attrib.get("version") != "2.0"
        or channel is None
        or optional_text(channel.findtext("title")) != "PRODYNA Careers"
        or not same_url(channel.findtext("link"), site_origin(expected_url))
    ):
        raise ProdynaSwitzerlandParseError("PRODYNA RSS has an unexpected identity")
    items = channel.findall("item")
    if not items:
        raise ProdynaSwitzerlandParseError("PRODYNA RSS is missing its vacancy catalog")
    if len(items) > max_catalog_records:
        raise ProdynaSwitzerlandParseError(
            f"PRODYNA RSS exceeds the configured limit of {max_catalog_records} vacancies"
        )

    records: dict[str, dict[str, Any]] = {}
    for item in items:
        rss_title = optional_text(item.findtext("title"))
        title = strip_rss_title(rss_title)
        link = normalize_detail_url(item.findtext("link"))
        guid = normalize_detail_url(item.findtext("guid"))
        posted_at = normalize_rss_date(item.findtext("pubDate"))
        if not title or not link or guid != link or not posted_at or link in records:
            raise ProdynaSwitzerlandParseError(
                "PRODYNA RSS contains an incomplete or duplicate vacancy"
            )
        records[link] = {
            "title": title,
            "url": link,
            "posted_at": posted_at,
            "pub_date": optional_text(item.findtext("pubDate")),
        }
    return records


def reconcile_catalog(
    records: list[dict[str, Any]],
    rss_records: dict[str, dict[str, Any]],
) -> None:
    listing_by_url = {record["url"]: record for record in records}
    if set(listing_by_url) != set(rss_records):
        raise ProdynaSwitzerlandParseError(
            "PRODYNA HTML and RSS catalogs contain different vacancies"
        )
    for url, record in listing_by_url.items():
        if record["title"] != rss_records[url]["title"]:
            raise ProdynaSwitzerlandParseError(
                "PRODYNA HTML and RSS catalogs contain different vacancy titles"
            )


def select_zurich_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        location = optional_text(record.get("location"))
        division = optional_text(record.get("division"))
        if location == EXPECTED_LOCATION:
            if division != EXPECTED_DIVISION:
                raise ProdynaSwitzerlandParseError(
                    "PRODYNA Zurich vacancy belongs to an unexpected division"
                )
            selected.append(record)
    return selected


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_slug: str,
    expected_title: str,
    expected_division: str,
    expected_location: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_slug(page_url) != expected_slug:
        raise ProdynaSwitzerlandParseError("PRODYNA detail page returned a different vacancy")
    page = Selector(page_html)
    canonicals = {
        optional_text(value)
        for value in page.css('link[rel="canonical"]::attr(href)').getall()
        if optional_text(value)
    }
    titles = unique_selector_texts(page, "h1")
    og_titles = {
        optional_text(value)
        for value in page.css('meta[property="og:title"]::attr(content)').getall()
        if optional_text(value)
    }
    metadata = extract_detail_metadata(page)
    description_nodes = page.css(".job-description")
    description_parts = [value for node in description_nodes if (value := html_to_text(node.get()))]
    description = optional_multiline_text("\n\n".join(description_parts))
    apply_urls = {
        normalized
        for value in page.css("a[href]::attr(href)").getall()
        if (normalized := normalize_apply_url(value))
    }
    division = metadata.get("Division")
    location = metadata.get("Location")
    workload = metadata.get("Workload")
    category = metadata.get("Category")
    seniority = metadata.get("Seniority Level")
    language = metadata.get("Language")
    if (
        canonicals != {expected_url}
        or titles != {expected_title}
        or og_titles != {f"{expected_title} | PRODYNA"}
        or division != expected_division
        or location != expected_location
        or not workload
        or not category
        or not seniority
        or not language
        or not description
        or len(apply_urls) != 1
    ):
        raise ProdynaSwitzerlandParseError("PRODYNA detail page contains an incomplete vacancy")
    return {
        "id": expected_slug,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "division": division,
        "location": format_location(location),
        "workload": workload,
        "category": category,
        "seniority": seniority,
        "language": language,
        "apply_url": next(iter(apply_urls)),
        "description": description,
    }


def extract_detail_metadata(page: Selector) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in page.css(".meta-item"):
        children = item.css(":scope > div")
        if len(children) != 2:
            continue
        label = html_to_text(children[0].get())
        values = [
            value
            for node in children[1].css(".jobs-meta-collection-item")
            if (value := html_to_text(node.get()))
        ]
        value = ", ".join(values) if values else html_to_text(children[1].get())
        if label and value:
            if label in metadata:
                raise ProdynaSwitzerlandParseError(
                    "PRODYNA detail page contains duplicate metadata"
                )
            metadata[label] = value
    return metadata


def normalize_detail_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.prodyna.com"
        or not DETAIL_PATH_PATTERN.fullmatch(parts.path.rstrip("/"))
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.prodyna.com", parts.path.rstrip("/"), "", ""))


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.prodyna.com"
        or not APPLY_PATH_PATTERN.fullmatch(parts.path)
        or parse_qs(parts.query, keep_blank_values=True) != {"lang": ["eng"]}
        or parts.fragment
    ):
        return None
    return text


def extract_slug(value: Any) -> str | None:
    normalized = normalize_detail_url(value)
    if not normalized:
        return None
    match = DETAIL_PATH_PATTERN.fullmatch(urlsplit(normalized).path)
    return match.group(1) if match else None


def strip_rss_title(value: Any) -> str | None:
    text = optional_text(value)
    suffix = " | PRODYNA"
    return optional_text(text[: -len(suffix)]) if text and text.endswith(suffix) else None


def normalize_rss_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).date().isoformat()


def catalog_url_from(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def site_origin(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


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
        and parse_qs(actual.query, keep_blank_values=True)
        == parse_qs(target.query, keep_blank_values=True)
        and not actual.fragment
        and not target.fragment
    )


def deduplicate_prodyna_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_slug(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def format_location(value: Any) -> str | None:
    text = optional_text(value)
    return f"{text}, Switzerland" if text else None


def unique_selector_texts(page: Selector, css: str) -> set[str]:
    return {value for raw in page.css(css).getall() if (value := html_to_text(raw))}


def selector_text(selector: Any, css: str) -> str | None:
    nodes = selector.css(css)
    return html_to_text(nodes[0].get()) if len(nodes) == 1 else None


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
