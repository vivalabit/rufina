from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

LAKE_CAREERS_URL = "https://lake.ch/ueber-uns/karriere"
LAKE_COMPANY = "LAKE Solutions AG"
LAKE_LOCATION = "Wallisellen, Switzerland"
LAKE_APPLY_EMAIL = "job@lake.ch"
LAKE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
EXPECTED_LANGUAGE = "de"
EXPECTED_LISTING_HEADING = "Offene Stellen bei LAKE"
EXPECTED_CATALOG_HEADING = "Derzeit offen"
JOB_PATH_PATTERN = re.compile(r"^/ueber-uns/karriere/([a-z0-9][a-z0-9-]*)/?$")
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")


class LakeParseError(DirectCompanyRequestError):
    pass


class LakeJobsParser:
    """Collect LAKE Solutions' complete visible careers catalog."""

    parser_id = "lake"

    def __init__(
        self,
        *,
        base_url: str = LAKE_CAREERS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=LAKE_HEADERS,
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
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except LakeParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Lake vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Lake vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_lake_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Lake vacancies from the complete visible "
                "official careers catalog"
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
                    expected_title=record["title"],
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, LakeParseError, ValueError) as exc:
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
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise LakeParseError("Lake careers catalog returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    contents = page.css("div.text-image--text-container")
    if len(contents) != 1:
        raise LakeParseError("Lake careers page is missing its main content")
    content = contents[0]
    headings = {
        selector_text(node)
        for node in content.css("h1, h2, h3, h4")
        if selector_text(node)
    }
    if not {EXPECTED_LISTING_HEADING, EXPECTED_CATALOG_HEADING}.issubset(headings):
        raise LakeParseError("Lake careers page is missing its vacancy catalog")

    links = [
        link
        for link in content.css("a[href]")
        if canonical_job_url(urljoin(page_url, link.attrib.get("href", "")))
    ]
    if len(links) > max_jobs:
        raise LakeParseError(
            f"Lake exposes {len(links)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, link in enumerate(links):
        detail_url = canonical_job_url(urljoin(page_url, link.attrib.get("href", "")))
        job_id = extract_job_id(detail_url)
        title = selector_text(link)
        workload = extract_workload(title)
        if not detail_url or not job_id or not title:
            raise LakeParseError("Lake careers catalog contains an incomplete vacancy")
        if job_id in seen_ids or detail_url in seen_urls:
            raise LakeParseError("Lake careers catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(detail_url)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": LAKE_COMPANY,
                "location": LAKE_LOCATION,
                "workload": workload,
                "url": detail_url,
                "apply_url": f"mailto:{LAKE_APPLY_EMAIL}",
                "catalog_index": index,
                "listing_page_url": canonical_careers_url(page_url),
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
    expected_job_id: str,
) -> dict[str, Any]:
    public_url = canonical_job_url(page_url)
    if public_url != canonical_job_url(expected_url) or extract_job_id(public_url) != expected_job_id:
        raise LakeParseError("Lake detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    schemas = list(extract_schemas(page, schema_type="WebSite"))
    contents = page.css("div.text-image--text-container")
    if len(schemas) != 1 or len(contents) != 1:
        raise LakeParseError("Lake detail page has an invalid identity")

    schema = schemas[0]
    schema_url = canonical_job_url(schema.get("url"))
    title = optional_text(schema.get("headline")) or optional_text(schema.get("name"))
    schema_name = optional_text(schema.get("name"))
    posted_at = optional_text(schema.get("datePublished"))
    updated_at = optional_text(schema.get("dateModified"))
    content = contents[0]
    description = html_to_text(content.get() or "")
    apply_urls = {
        normalized
        for raw in content.css('a[href^="mailto:"]::attr(href)').getall()
        if (normalized := normalize_apply_url(raw))
    }
    content_text = selector_text(content)
    if (
        schema_url != public_url
        or not title
        or schema_name != title
        or comparable_text(title) != comparable_text(expected_title)
        or not posted_at
        or not updated_at
        or apply_urls != {f"mailto:{LAKE_APPLY_EMAIL}"}
        or not content_text
        or LAKE_COMPANY not in content_text
        or "8304 Wallisellen" not in content_text
        or not description
        or len(description) < 300
    ):
        raise LakeParseError("Lake detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": LAKE_COMPANY,
        "location": LAKE_LOCATION,
        "url": public_url,
        "apply_url": apply_urls.pop(),
        "posted_at": posted_at,
        "updated_at": updated_at,
        "workload": extract_workload(title),
        "description": description,
        "schema": schema,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    title = optional_text(detail.get("title")) or optional_text(record.get("title"))
    public_url = optional_text(detail.get("url")) or optional_text(record.get("url"))
    return ParsedJob(
        source="lake",
        title=title,
        company=LAKE_COMPANY,
        location=LAKE_LOCATION,
        url=public_url,
        apply_url=(
            optional_text(detail.get("apply_url"))
            or optional_text(record.get("apply_url"))
            or public_url
        ),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("workload"))
            or optional_text(record.get("workload"))
        ),
        seniority="Senior" if "senior" in comparable_text(title).split() else None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    site_names = unique_attribute_values(page, 'meta[property="og:site_name"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or site_names != {LAKE_COMPANY}
        or languages != {EXPECTED_LANGUAGE}
    ):
        raise LakeParseError("Lake page has an invalid identity")


def extract_schemas(page: Selector, *, schema_type: str) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            if candidate.get("@type") == schema_type:
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path).rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "lake.ch"
        or path != "/ueber-uns/karriere"
        or parts.query
        or parts.fragment
    ):
        return None
    return LAKE_CAREERS_URL


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path).rstrip("/")
    match = JOB_PATH_PATTERN.fullmatch(path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "lake.ch"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "lake.ch", path, "", ""))


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(unquote(urlsplit(text).path).rstrip("/"))
    return match.group(1) if match else None


def normalize_apply_url(value: Any) -> str | None:
    text = html.unescape(optional_text(value) or "")
    parts = urlsplit(text)
    if (
        parts.scheme.casefold() != "mailto"
        or unquote(parts.path).casefold() != LAKE_APPLY_EMAIL
        or parts.query
        or parts.fragment
    ):
        return None
    return f"mailto:{LAKE_APPLY_EMAIL}"


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = WORKLOAD_PATTERN.search(text)
    return re.sub(r"\s+", "", match.group(0)) if match else None


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == "https"
        and target.scheme == "https"
        and actual.netloc.casefold().removeprefix("www.")
        == target.netloc.casefold().removeprefix("www.")
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and not actual.query
        and not target.query
        and not actual.fragment
        and not target.fragment
    )


def deduplicate_lake_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any) -> str | None:
    return optional_text(" ".join(selector.css("::text").getall()))


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f'{css}::attr("{attribute}")').getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    decoded = html.unescape(value)
    decoded = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", decoded)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", decoded)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = html.unescape(text).replace("\xa0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip() or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None
