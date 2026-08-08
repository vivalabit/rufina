from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

HUAWEI_SWITZERLAND_JOBS_BASE_URL = "https://careers.huaweirc.ch/jobs"
HUAWEI_SWITZERLAND_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"/jobs/(\d+)(?:[-/]|$)", re.IGNORECASE)
RESULT_COUNT_PATTERN = re.compile(r"\b([\d\s'.,]+)\s+jobs?\b", re.IGNORECASE)


class HuaweiSwitzerlandParseError(DirectCompanyRequestError):
    pass


class HuaweiSwitzerlandJobsParser:
    """Collect the complete Huawei Switzerland Teamtailor catalog."""

    parser_id = "huawei_switzerland"

    def __init__(
        self,
        *,
        base_url: str = HUAWEI_SWITZERLAND_JOBS_BASE_URL,
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
                headers=HUAWEI_SWITZERLAND_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(response.text, page_url=str(response.url))
                self.enrich_records(client, records)
        except HuaweiSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Huawei Switzerland vacancy request failed"
            ) from exc
        except Exception as exc:
            raise DirectCompanyRequestError(
                "Huawei Switzerland vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_huawei_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Huawei Switzerland vacancies from one page"
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
            detail_url = optional_text(record.get("url"))
            if not detail_url:
                return record, None
            try:
                response = client.get(detail_url, headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=optional_text(record.get("id")),
                )
            except (
                httpx.HTTPError,
                HuaweiSwitzerlandParseError,
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
        public_url = optional_text(detail.get("public_url")) or optional_text(
            record.get("url")
        )

        raw = dict(record)
        raw["detail"] = detail
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=extract_company(schema) or "Huawei Switzerland",
            location=(
                optional_text(detail.get("location"))
                or extract_schema_location(schema)
                or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(schema.get("datePosted")),
            employment_type=(
                optional_text(detail.get("employment_type"))
                or extract_employment_type(schema)
            ),
            seniority=optional_text(detail.get("seniority")),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("teaser"))
            ),
            raw=raw,
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    if not page.css("#jobs_list_container").get():
        raise HuaweiSwitzerlandParseError(
            "Huawei Switzerland listing page is missing its vacancy catalog"
        )

    expected_count = extract_result_count(page)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("#jobs_list_container > li"):
        path = optional_text(card.css('a[href*="/jobs/"]::attr(href)').get())
        title = optional_text(" ".join(card.css('a[href*="/jobs/"]::text').getall()))
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        if not detail_url or not title or not job_id:
            raise HuaweiSwitzerlandParseError(
                "Huawei Switzerland listing contains an incomplete vacancy"
            )
        if job_id in seen_ids:
            raise HuaweiSwitzerlandParseError(
                "Huawei Switzerland listing contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)

        metadata = normalized_texts(card.css("span.text-base span::text").getall())
        records.append(
            {
                "id": job_id,
                "title": title,
                "department": metadata[-2] if len(metadata) > 1 else None,
                "location": metadata[-1] if metadata else None,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    if len(records) != expected_count:
        raise HuaweiSwitzerlandParseError(
            f"Huawei Switzerland listed {len(records)} vacancies but declared "
            f"{expected_count} jobs"
        )
    return records


def extract_result_count(page: Selector) -> int:
    candidates = normalized_texts(
        page.css(".jobs-list-container p span::text").getall()
    )
    for candidate in candidates:
        match = RESULT_COUNT_PATTERN.search(candidate)
        if not match:
            continue
        digits = re.sub(r"\D", "", match.group(1))
        if digits:
            return int(digits)
    raise HuaweiSwitzerlandParseError(
        "Huawei Switzerland listing page is missing its result count"
    )


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    title = optional_text(schema.get("title"))
    description_html = optional_text(schema.get("description"))
    schema_job_id = extract_schema_job_id(schema)
    if not title or not description_html or not schema_job_id:
        raise HuaweiSwitzerlandParseError(
            "Huawei Switzerland detail page is missing its JobPosting data"
        )
    if expected_job_id and schema_job_id != expected_job_id:
        raise HuaweiSwitzerlandParseError(
            "Huawei Switzerland detail page returned a different vacancy"
        )

    public_url = (
        optional_text(page.css('meta[property="og:url"]::attr(content)').get())
        or page_url
    )
    apply_url = optional_text(
        page.css(
            "main[data-careersite--jobs--form-overlay-job-application-url-value]"
            "::attr(data-careersite--jobs--form-overlay-job-application-url-value)"
        ).get()
    )
    attributes = extract_detail_attributes(page)
    return {
        "id": schema_job_id,
        "title": title,
        "public_url": public_url,
        "apply_url": urljoin(page_url, apply_url) if apply_url else None,
        "department": attributes.get("department"),
        "location": attributes.get("locations"),
        "employment_type": attributes.get("employment type"),
        "seniority": attributes.get("employment level"),
        "description": html_to_text(description_html),
        "schema": schema,
    }


def extract_detail_attributes(page: Selector) -> dict[str, str]:
    terms = page.css("section dl dt")
    values = page.css("section dl dd")
    attributes: dict[str, str] = {}
    for term, value in zip(terms, values, strict=False):
        key = optional_text(" ".join(term.css("::text").getall()))
        item = optional_text(" ".join(value.css("::text").getall()))
        if key and item:
            attributes[key.casefold()] = item
    return attributes


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
            continue
        yield from (
            candidate
            for candidate in walk_json(payload)
            if candidate.get("@type") == "JobPosting"
        )


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
    return match.group(1) if match else None


def extract_schema_job_id(schema: dict[str, Any]) -> str | None:
    identifier = schema.get("identifier")
    if not isinstance(identifier, dict):
        return None
    return optional_text(identifier.get("value"))


def extract_company(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    if not isinstance(organization, dict):
        return None
    return optional_text(organization.get("name"))


def extract_schema_location(schema: dict[str, Any]) -> str | None:
    locations = schema.get("jobLocation")
    candidates = locations if isinstance(locations, list) else [locations]
    values: list[str] = []
    for location in candidates:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if not isinstance(address, dict):
            continue
        locality = optional_text(address.get("addressLocality"))
        if locality:
            values.append(locality)
    unique = list(dict.fromkeys(values))
    return ", ".join(unique) if unique else None


def extract_employment_type(schema: dict[str, Any]) -> str | None:
    raw_value = schema.get("employmentType")
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    normalized = [
        text.replace("_", " ").title()
        for value in values
        if (text := optional_text(value))
    ]
    return ", ".join(dict.fromkeys(normalized)) if normalized else None


def deduplicate_huawei_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalized_texts(values: Iterable[Any]) -> list[str]:
    return [text for value in values if (text := optional_text(value))]


def html_to_text(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text)) or ""


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
