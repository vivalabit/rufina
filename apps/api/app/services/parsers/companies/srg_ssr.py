from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

SRG_SSR_JOBS_BASE_URL = "https://www.srgssr.ch/en/jobs-career/jobs"
SRG_SSR_CATALOG_URL = (
    "https://ohws.prospective.ch/public/v1/careercenter/1000936/"
    "?sub=1&srg=1&filter_10=1124107&lang=en"
)
SRG_SSR_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(
    r"/srg/job-vacancies/[^/]+/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
INVISIBLE_CHARACTERS_PATTERN = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class SrgSsrParseError(DirectCompanyRequestError):
    pass


class SrgSsrJobsParser:
    """Collect the complete SRG SSR catalog exposed by its Prospective page."""

    parser_id = "srg_ssr"

    def __init__(
        self,
        *,
        base_url: str = SRG_SSR_JOBS_BASE_URL,
        catalog_url: str = SRG_SSR_CATALOG_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(2, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with CareerHttpClient(
                headers={**SRG_SSR_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.catalog_url)
                response.raise_for_status()
                records = parse_listing_html(response.text, page_url=str(response.url))
                self.enrich_records(client, records)
        except SrgSsrParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(f"SRG SSR vacancy request failed: {exc}") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("SRG SSR vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_srg_ssr_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} SRG SSR vacancies from the Prospective catalog"),
        )

    def enrich_records(
        self,
        client: CareerHttpClient,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            detail_url = optional_text(record.get("url"))
            if not detail_url:
                return record, None
            try:
                response = client.get(detail_url, headers={"Referer": self.catalog_url})
                response.raise_for_status()
                detail = parse_detail_html(response.text, page_url=str(response.url))
                if extract_job_id(detail.get("public_url")) != record.get("id"):
                    raise SrgSsrParseError("SRG SSR detail page changed its vacancy ID")
                return record, detail
            except (httpx.HTTPError, SrgSsrParseError, ValueError) as exc:
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
        schema = detail.get("schema")
        schema = schema if isinstance(schema, dict) else {}
        public_url = optional_text(detail.get("public_url")) or optional_text(record.get("url"))

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="SRG SSR",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(
                optional_text(record.get("workload")) or extract_employment_type(schema)
            ),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_text(record.get("summary"))
            ),
            raw=raw,
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    if not page.css("form#oh-form") or not page.css("section#jobResults"):
        raise SrgSsrParseError("SRG SSR listing page is missing its catalog contract")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("section#jobResults .countJobRecords"):
        detail_path = optional_text(card.css("a[href*='/srg/job-vacancies/']::attr(href)").get())
        detail_url = urljoin(page_url, detail_path) if detail_path else None
        job_id = extract_job_id(detail_url)
        title = selector_text(card, "h1")
        summary = selector_text(card, "small")
        workload, location = split_listing_summary(summary)
        if not detail_url or not job_id or not title:
            raise SrgSsrParseError("SRG SSR listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise SrgSsrParseError("SRG SSR listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "workload": workload,
                "location": location,
                "summary": selector_text(card, "p"),
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(page_html: str, *, page_url: str) -> dict[str, Any]:
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    # Prospective currently emits JobPosting after the closing </html> tag.
    # lxml correctly drops that invalid trailing node, so retain a raw-HTML
    # fallback while also supporting conventional in-document JSON-LD.
    if not schema:
        schema = next(extract_job_posting_schemas_from_html(page_html), {})
    title = optional_text(schema.get("title"))
    description_html = optional_text(schema.get("description"))
    apply_path = optional_text(page.css("a#apply-button::attr(href)").get())
    if not title or not description_html or not apply_path:
        raise SrgSsrParseError("SRG SSR detail page is missing required vacancy data")

    return {
        "title": title,
        "public_url": page_url,
        "apply_url": urljoin(page_url, apply_path),
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "location": extract_schema_location(schema),
        "description": html_to_text(description_html),
        "schema": schema,
    }


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
            continue
        for candidate in walk_json(payload):
            job_type = candidate.get("@type")
            if job_type == "JobPosting" or (
                isinstance(job_type, list) and "JobPosting" in job_type
            ):
                yield candidate


def extract_job_posting_schemas_from_html(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        for candidate in walk_json(payload):
            job_type = candidate.get("@type")
            if job_type == "JobPosting" or (
                isinstance(job_type, list) and "JobPosting" in job_type
            ):
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1).lower() if match else None


def split_listing_summary(value: Any) -> tuple[str | None, str | None]:
    summary = optional_text(value)
    if not summary:
        return None, None
    parts = re.split(r"\s+(?:in)\s+|\s*,\s*", summary, maxsplit=1)
    if len(parts) == 1:
        return parts[0], None
    return optional_text(parts[0]), optional_text(parts[1])


def extract_schema_location(schema: dict[str, Any]) -> str | None:
    location = schema.get("jobLocation")
    if isinstance(location, Sequence) and not isinstance(location, (str, bytes)):
        values = [extract_place_name(item) for item in location]
        names = [name for name in values if name]
        return ", ".join(dict.fromkeys(names)) or None
    return extract_place_name(location)


def extract_place_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return optional_text(value)
    address = value.get("address")
    if isinstance(address, dict):
        return optional_text(address.get("addressLocality")) or optional_text(
            address.get("addressRegion")
        )
    return optional_text(value.get("name"))


def extract_employment_type(schema: dict[str, Any]) -> str | None:
    value = schema.get("employmentType")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [text for item in value if (text := optional_text(item))]
        return ", ".join(values) or None
    return optional_text(value)


def deduplicate_srg_ssr_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = INVISIBLE_CHARACTERS_PATTERN.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def selector_text(node: Any, selector: str) -> str | None:
    selected_html = node.css(selector).get()
    return optional_text(html_to_text(selected_html)) if selected_html else None


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = INVISIBLE_CHARACTERS_PATTERN.sub("", str(value)).strip()
    return normalized or None
