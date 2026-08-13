from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

CMI_JOBS_URL = "https://cmi.ch/karriere/"
CMI_DETAIL_URL = "https://cmi.ch/karriere/stellen/"
CMI_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "CM Informatik AG"
EXPECTED_SITE_NAME = "CM Informatik AG"
EXPECTED_LOCATION = "Schwerzenbach, Switzerland"
EXPECTED_LANGUAGE = "de"
EXPECTED_QUERY_ID = "12"
EXPECTED_LISTING_CONTRACT = {
    "40076": ("query", EXPECTED_QUERY_ID),
    "40306": ("rest_api_endpoint", ""),
}
ITEM_ID_PATTERN = re.compile(r"^12-(0|[1-9]\d*)$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
APPLY_PATH_PATTERN = re.compile(
    r"^/application-process/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
WORKLOAD_RANGE_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%(?!\d)")
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*%(?!\d)")


class CmiParseError(DirectCompanyRequestError):
    pass


class CmiJobsParser:
    """Collect CMI's complete server-rendered vacancy catalog."""

    parser_id = "cmi"

    def __init__(
        self,
        *,
        base_url: str = CMI_JOBS_URL,
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
                headers={**CMI_HEADERS, "Referer": self.base_url},
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
        except CmiParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("CMI vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("CMI vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_cmi_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} CMI Switzerland vacancies from the official catalog",
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
                    add_nocache(record["url"]),
                    headers={"Referer": self.base_url, "Cache-Control": "no-cache"},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_item_id=record["item_id"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, CmiParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise CmiParseError("CMI listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    catalog_grids = []
    for listing_id, (listing_source, query_id) in EXPECTED_LISTING_CONTRACT.items():
        grids = page.css(f'.jet-listing-grid__items[data-listing-id="{listing_id}"]')
        if (
            len(grids) != 1
            or grids[0].attrib.get("data-pages") != "1"
            or grids[0].attrib.get("data-listing-source") != listing_source
            or grids[0].attrib.get("data-query-id") != query_id
        ):
            raise CmiParseError("CMI listing is missing its complete vacancy catalog")
        catalog_grids.append(grids[0])
    if not any(
        grid.css('a[href*="/karriere/stellen/"][href*="JobId="]')
        for grid in catalog_grids
    ):
        raise CmiParseError("CMI listing is missing its complete vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_item_ids: set[str] = set()
    seen_job_ids: set[str] = set()
    for grid in catalog_grids:
        cards = grid.xpath(
            './/div[contains(concat(" ", normalize-space(@class), " "), '
            '" jet-listing-grid__item ")][.//a[contains(@href, "JobId=")]]'
        )
        for card in cards:
            job_boxes = card.css(":scope .job-box")
            titles = unique_selector_texts(card, ".job-box .elementor-heading-title")
            links = card.css('.job-box a[href*="/karriere/stellen/"][href*="JobId="]')
            item_id = optional_text(card.attrib.get("data-post-id"))
            if len(job_boxes) != 1 or len(titles) != 1 or len(links) != 1 or not item_id:
                raise CmiParseError("CMI listing contains an incomplete vacancy")

            detail_url = urljoin(page_url, optional_text(links[0].attrib.get("href")) or "")
            url_identity = parse_job_url(detail_url, expected_host=expected_host)
            title = normalize_title(next(iter(titles)))
            if not url_identity or url_identity[0] != item_id or not title:
                raise CmiParseError("CMI listing contains an invalid vacancy")
            _, job_id = url_identity
            if item_id in seen_item_ids or job_id in seen_job_ids:
                raise CmiParseError("CMI listing contains duplicate vacancy IDs")
            seen_item_ids.add(item_id)
            seen_job_ids.add(job_id)
            records.append(
                {
                    "id": job_id,
                    "item_id": item_id,
                    "title": title,
                    "company": EXPECTED_COMPANY,
                    "location": EXPECTED_LOCATION,
                    "url": detail_url,
                    "listing_page_url": page_url,
                }
            )
    if not records:
        raise CmiParseError("CMI listing is missing its vacancy catalog")
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_item_id: str,
    expected_job_id: str,
    expected_title: str,
) -> dict[str, Any]:
    expected_host = urlsplit(expected_url).netloc.casefold()
    actual_identity = parse_job_url(page_url, expected_host=expected_host, allow_nocache=True)
    expected_identity = parse_job_url(expected_url, expected_host=expected_host)
    if actual_identity != expected_identity or actual_identity != (
        expected_item_id,
        expected_job_id,
    ):
        raise CmiParseError("CMI detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=CMI_DETAIL_URL)
    selected = page.css(
        f'.jet-listing-grid__item[data-post-id="{expected_item_id}"] .rest-post'
    )
    if len(selected) != 1:
        raise CmiParseError("CMI detail page is missing the requested vacancy")
    vacancy = selected[0]
    titles = unique_selector_texts(vacancy, "h1.elementor-heading-title")
    title = normalize_title(next(iter(titles))) if len(titles) == 1 else None

    description_parts: list[str] = []
    for node in vacancy.css(
        ".intro-text .elementor-widget-container, "
        ".rest-import .elementor-widget-container, "
        ".rest-import-list .elementor-widget-container"
    ):
        part = html_to_text(html.unescape(node.get()))
        if part and part not in description_parts:
            description_parts.append(part)
    description = optional_multiline_text("\n\n".join(description_parts))

    apply_urls = {
        value
        for raw in vacancy.css("a.bdt-ep-button::attr(href)").getall()
        if (value := validate_apply_url(raw))
    }
    if title != expected_title or not description or len(apply_urls) != 1:
        raise CmiParseError("CMI detail page contains an incomplete vacancy")
    return {
        "id": expected_job_id,
        "item_id": expected_item_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "apply_url": apply_urls.pop(),
        "posted_at": None,
        "employment_type": normalize_workload(description),
        "description": description,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="cmi",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=EXPECTED_LOCATION,
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=None,
        employment_type=optional_text(detail.get("employment_type")),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def parse_job_url(
    value: Any,
    *,
    expected_host: str,
    allow_nocache: bool = False,
) -> tuple[str, str] | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    allowed_keys = {"item_id", "JobId"} | ({"nocache"} if allow_nocache else set())
    item_values = query.get("item_id", [])
    job_values = query.get("JobId", [])
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or parts.path.rstrip("/") != "/karriere/stellen"
        or parts.fragment
        or set(query) != ({"item_id", "JobId", "nocache"} if allow_nocache else allowed_keys)
        or len(item_values) != 1
        or len(job_values) != 1
        or (allow_nocache and query.get("nocache") != ["1"])
        or ITEM_ID_PATTERN.fullmatch(item_values[0]) is None
        or UUID_PATTERN.fullmatch(job_values[0]) is None
    ):
        return None
    return item_values[0], job_values[0]


def validate_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "cmi.jobportal.abaservices.ch"
        or APPLY_PATH_PATTERN.fullmatch(parts.path) is None
        or query != {"jp": ["ABACUS"]}
        or parts.fragment
    ):
        return None
    return text


def add_nocache(value: str) -> str:
    parts = urlsplit(value)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["nocache"] = ["1"]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
    )


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
        raise CmiParseError("CMI page has an unexpected identity")


def normalize_title(value: Any) -> str | None:
    return optional_text(value)


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


def deduplicate_cmi_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
