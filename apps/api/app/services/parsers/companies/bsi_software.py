from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BSI_SOFTWARE_CAREERS_URL = "https://www.bsi-software.com/en/career/jobs"
BSI_SOFTWARE_JOBS_URL = "https://www.bsi-software.com/de/karriere/jobs"
BSI_SOFTWARE_API_URL = "https://www.bsi-software.com/api/jobs"
BSI_SOFTWARE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "BSI Software"
EXPECTED_LANGUAGE = "de"
SWISS_LOCATION_TAGS = {
    "baar": "Baar",
    "baden": "Baden",
    "bern": "Bern",
    "luzern": "Luzern",
    "zürich": "Zürich",
}
DETAIL_PATH_PATTERN = re.compile(r"^/de/karriere/jobs/([A-Za-z0-9][A-Za-z0-9_-]*)$")
CATALOG_PATH_PATTERN = re.compile(r"^karriere/jobs/([A-Za-z0-9][A-Za-z0-9_-]*)$")
WORKLOAD_RANGE_PATTERN = re.compile(r"^(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%$")
WORKLOAD_PATTERN = re.compile(r"^(\d{1,3})\s*%$")


class BsiSoftwareParseError(DirectCompanyRequestError):
    pass


class BsiSoftwareJobsParser:
    """Collect BSI Software's complete catalog and keep Swiss vacancies only."""

    parser_id = "bsi_software"

    def __init__(
        self,
        *,
        base_url: str = BSI_SOFTWARE_CAREERS_URL,
        jobs_url: str = BSI_SOFTWARE_JOBS_URL,
        api_url: str = BSI_SOFTWARE_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.jobs_url = jobs_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**BSI_SOFTWARE_HEADERS, "Referer": self.jobs_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, catalog_total = self.fetch_catalog(client)
                self.enrich_records(client, records)
        except BsiSoftwareParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("BSI Software vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("BSI Software vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bsi_software_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} BSI Software Switzerland vacancies from "
                f"{catalog_total} official catalog records"
            ),
        )

    def fetch_catalog(self, client: httpx.Client) -> tuple[list[dict[str, Any]], int]:
        page_size = 100
        raw_records: list[Any] = []
        expected_total: int | None = None
        for page_number in range(self.max_pages):
            response = client.get(
                self.api_url,
                params={
                    "lang": EXPECTED_LANGUAGE,
                    "startIndex": page_number * page_size,
                    "showItems": page_size,
                    "fixed-tag": "",
                    "selected-tag": "",
                    "tags": "[]",
                },
            )
            response.raise_for_status()
            payload = response.json()
            items, total = parse_catalog_page(payload)
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise BsiSoftwareParseError("BSI Software catalog changed during pagination")
            raw_records.extend(items)
            if len(raw_records) >= total:
                break
            if not items:
                raise BsiSoftwareParseError("BSI Software catalog pagination stalled")
        if expected_total is None or len(raw_records) != expected_total:
            raise BsiSoftwareParseError("BSI Software catalog response is incomplete")
        return parse_catalog_records(raw_records, jobs_url=self.jobs_url), expected_total

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
                response = client.get(record["url"], headers={"Referer": self.jobs_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_slug=record["id"],
                    expected_title=record["title"],
                    expected_tags=record["tags"],
                )
            except (httpx.HTTPError, BsiSoftwareParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_catalog_page(payload: Any) -> tuple[list[Any], int]:
    if not isinstance(payload, dict):
        raise BsiSoftwareParseError("BSI Software catalog response must be an object")
    items = payload.get("items")
    total = payload.get("totalItemCount")
    if (
        not isinstance(items, list)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
    ):
        raise BsiSoftwareParseError("BSI Software catalog response has an invalid contract")
    if len(items) > total:
        raise BsiSoftwareParseError("BSI Software catalog response has an invalid total")
    return items, total


def parse_catalog_records(
    raw_records: list[Any],
    *,
    jobs_url: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_records:
        if not isinstance(item, dict):
            raise BsiSoftwareParseError("BSI Software catalog contains an invalid record")
        title = optional_text(item.get("title"))
        catalog_path = optional_text(item.get("url"))
        tags = item.get("tags")
        if (
            not title
            or not isinstance(tags, list)
            or not tags
            or any(not optional_text(tag) for tag in tags)
        ):
            raise BsiSoftwareParseError("BSI Software catalog contains an incomplete record")

        normalized_tags = [optional_text(tag).casefold() for tag in tags if optional_text(tag)]
        locations = [
            display_name
            for tag, display_name in SWISS_LOCATION_TAGS.items()
            if tag in normalized_tags
        ]
        if not locations:
            continue

        workload = normalize_workload(item.get("text"))
        match = CATALOG_PATH_PATTERN.fullmatch(catalog_path or "")
        if not match or not workload:
            raise BsiSoftwareParseError("BSI Software catalog contains an incomplete record")

        slug = match.group(1)
        if slug in seen_ids:
            raise BsiSoftwareParseError("BSI Software catalog contains duplicate vacancies")
        seen_ids.add(slug)
        detail_url = urljoin(jobs_url.rstrip("/") + "/", slug)
        if not is_detail_url(detail_url, expected_slug=slug):
            raise BsiSoftwareParseError("BSI Software catalog contains an invalid vacancy URL")
        records.append(
            {
                "id": slug,
                "title": title,
                "company": EXPECTED_COMPANY,
                "location": f"{' / '.join(locations)}, Switzerland",
                "locations": locations,
                "employment_type": workload,
                "tags": [optional_text(tag) for tag in tags if optional_text(tag)],
                "url": detail_url,
                "catalog_record": dict(item),
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_slug: str,
    expected_title: str,
    expected_tags: list[str],
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or not is_detail_url(
        page_url, expected_slug=expected_slug
    ):
        raise BsiSoftwareParseError("BSI Software detail returned a different vacancy")
    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    titles = unique_attribute_values(page, 'meta[property="og:title"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    page_tags = {
        tag.casefold()
        for value in unique_attribute_values(page, 'meta[name="x-tags"]', "content")
        for tag in value.split(";")
        if optional_text(tag)
    }
    expected_tag_set = {tag.casefold() for tag in expected_tags}
    apply_candidates = {
        value
        for raw in page.css('a[href*="/studio/public/e/l/jobs"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    apply_urls = {value for value in apply_candidates if is_apply_url(value)}
    if len(apply_urls) > 1:
        # Related vacancies can include their own application link on this page.
        position = expected_title.split(" (", 1)[0].casefold()
        apply_urls = {
            url for url in apply_urls
            if parse_qs(urlsplit(url).query).get("position", [""])[0].casefold() == position
        }
        if len(apply_urls) != 1:
            raise BsiSoftwareParseError("BSI Software detail has ambiguous application links")
    descriptions = [text for node in page.css(".flex-grow-1") if (text := html_to_text(node.get()))]
    description = max(descriptions, key=len) if descriptions else None
    created_values = unique_attribute_values(page, 'meta[name="x-create-date"]', "content")
    posted_at = normalize_date(next(iter(created_values))) if len(created_values) == 1 else None
    if (
        len(canonicals) != 1
        or not is_detail_canonical(
            next(iter(canonicals)), expected_url=expected_url, expected_slug=expected_slug
        )
        or titles != {expected_title}
        or languages != {EXPECTED_LANGUAGE}
        or page_tags != expected_tag_set
        or len(apply_urls) > 1
        or any(not is_official_apply_candidate(value) for value in apply_candidates)
        or not description
        or not posted_at
    ):
        raise BsiSoftwareParseError("BSI Software detail page contains an incomplete vacancy")
    return {
        "id": expected_slug,
        "title": expected_title,
        "apply_url": next(iter(apply_urls), expected_url),
        "posted_at": posted_at,
        "description": description,
        "tags": sorted(page_tags),
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="bsi_software",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=optional_text(record.get("employment_type")),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if match := WORKLOAD_RANGE_PATTERN.fullmatch(text):
        lower, upper = (int(part) for part in match.groups())
        return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None
    if match := WORKLOAD_PATTERN.fullmatch(text):
        workload = int(match.group(1))
        return f"{workload}%" if 1 <= workload <= 100 else None
    return None


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = re.fullmatch(
        r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2}):(\d{2})",
        text,
    )
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups()[:3])
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def is_detail_url(value: Any, *, expected_slug: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "www.bsi-software.com"
        and match is not None
        and match.group(1) == expected_slug
        and not parts.query
        and not parts.fragment
    )


def is_detail_canonical(value: Any, *, expected_url: str, expected_slug: str) -> bool:
    if same_url(value, expected_url):
        return True
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "www.bsi-software.com"
        and parts.path.startswith("/de/karriere/jobs/")
        and not parts.query
        and not parts.fragment
    )


def is_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "services.bsi-software.com"
        and parts.path == "/studio/public/e/l/jobs"
        and query.get("lang") == [EXPECTED_LANGUAGE]
        and len(query.get("position", [])) == 1
        and len(query.get("id", [])) == 1
        and not parts.fragment
    )


def is_official_apply_candidate(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "services.bsi-software.com"
        and parts.path == "/studio/public/e/l/jobs"
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
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and actual.query == target.query
        and not actual.fragment
    )


def deduplicate_bsi_software_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_attribute_values(page: Selector, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in page.css(f"{css}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|strong)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


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
