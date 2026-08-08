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

ZUERCHER_KANTONALBANK_JOBS_BASE_URL = "https://apply.refline.ch/792841/search.html"
ZUERCHER_KANTONALBANK_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"/\d+/(\d+)/pub/(\d+)/?$", re.IGNORECASE)


class ZuercherKantonalbankParseError(DirectCompanyRequestError):
    pass


class ZuercherKantonalbankJobsParser:
    """Collect the complete ZKB catalog from its Refline careers page."""

    parser_id = "zuercher_kantonalbank"

    def __init__(
        self,
        *,
        base_url: str = ZUERCHER_KANTONALBANK_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=ZUERCHER_KANTONALBANK_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(response.text, page_url=str(response.url))
                self.enrich_records(client, records)
        except ZuercherKantonalbankParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Zürcher Kantonalbank vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Zürcher Kantonalbank vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_zuercher_kantonalbank_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Zürcher Kantonalbank vacancies from one page"),
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
            detail_url = optional_text(record.get("url"))
            if not detail_url:
                return record, None
            try:
                response = client.get(detail_url, headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                )
            except (
                httpx.HTTPError,
                ZuercherKantonalbankParseError,
                ValueError,
            ) as exc:
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
            company="Zürcher Kantonalbank",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=optional_text(record.get("workload"))
            or extract_employment_type(schema),
            seniority=optional_text(record.get("target_group")),
            description=optional_multiline_text(detail.get("description")),
            raw=raw,
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    table = page.css("table.searchResult")
    if not table:
        raise ZuercherKantonalbankParseError(
            "Zürcher Kantonalbank listing page is missing its vacancy table"
        )

    required_headers = {
        "position",
        "operationArea",
        "workplace",
        "workload",
        "segment",
        "locale",
    }
    header_classes = {
        class_name
        for header in page.css("table.searchResult thead th")
        for class_name in str(header.attrib.get("class", "")).split()
    }
    if not required_headers.issubset(header_classes):
        raise ZuercherKantonalbankParseError(
            "Zürcher Kantonalbank vacancy table has an invalid header"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in page.css("table.searchResult tbody tr"):
        detail_path = optional_text(row.css("td.position a::attr(href)").get())
        title = selector_text(row, "td.position a")
        detail_url = urljoin(page_url, detail_path) if detail_path else None
        job_id = extract_job_id(detail_url)
        publication_id = extract_publication_id(detail_url)
        if not detail_url or not title or not job_id or not publication_id:
            raise ZuercherKantonalbankParseError(
                "Zürcher Kantonalbank listing contains an incomplete vacancy"
            )
        if job_id in seen_ids:
            raise ZuercherKantonalbankParseError(
                "Zürcher Kantonalbank listing contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)

        records.append(
            {
                "id": job_id,
                "publication_id": publication_id,
                "title": title,
                "operation_area": selector_text(row, "td.operationArea"),
                "location": selector_text(row, "td.workplace"),
                "workload": selector_text(row, "td.workload"),
                "target_group": selector_text(row, "td.segment"),
                "language": selector_text(row, "td.locale"),
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(page_html: str, *, page_url: str) -> dict[str, Any]:
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    title = optional_text(schema.get("title"))
    description_html = optional_text(schema.get("description"))
    apply_path = optional_text(page.css("a.applyLink::attr(href)").get())
    if not title or not description_html or not apply_path:
        raise ZuercherKantonalbankParseError(
            "Zürcher Kantonalbank detail page is missing required vacancy data"
        )

    return {
        "title": title,
        "public_url": page_url,
        "apply_url": urljoin(page_url, apply_path),
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "location": extract_schema_location(schema),
        "description": html_to_text(strip_description_header(description_html)),
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


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_job_id(value: Any) -> str | None:
    match = job_path_match(value)
    return match.group(1) if match else None


def extract_publication_id(value: Any) -> str | None:
    match = job_path_match(value)
    return match.group(2) if match else None


def job_path_match(value: Any) -> re.Match[str] | None:
    text = optional_text(value)
    return JOB_PATH_PATTERN.search(urlsplit(text).path) if text else None


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


def deduplicate_zuercher_kantonalbank_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def strip_description_header(value: str) -> str:
    without_title = re.sub(
        r"^\s*<h1(?:\s[^>]*)?>.*?</h1>\s*",
        "",
        value,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(
        r"^\s*<h2(?:\s[^>]*)?>.*?</h2>\s*",
        "",
        without_title,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
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
    normalized = str(value).strip()
    return normalized or None
