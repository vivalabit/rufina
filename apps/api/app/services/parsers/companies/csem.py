from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

CSEM_JOBS_BASE_URL = "https://www.csem.ch/en/jobs/"
CSEM_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,fr-CH;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"/jobs/(\d+)/?$", re.IGNORECASE)
RESULT_COUNT_PATTERN = re.compile(r"\b(\d+)\s+results?\b", re.IGNORECASE)


class CsemParseError(DirectCompanyRequestError):
    pass


class CsemJobsParser:
    """Collect the complete CSEM catalog from its server-rendered careers page."""

    parser_id = "csem"

    def __init__(
        self,
        *,
        base_url: str = CSEM_JOBS_BASE_URL,
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
                headers=CSEM_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(response.text, page_url=str(response.url))
                self.enrich_records(client, records)
        except CsemParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("CSEM vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("CSEM vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_csem_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} CSEM vacancies from one page",
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
                return record, parse_detail_html(response.text)
            except (httpx.HTTPError, CsemParseError, ValueError) as exc:
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
        schema = record.get("schema")
        schema = schema if isinstance(schema, dict) else {}
        public_url = optional_text(detail.get("canonical_url")) or optional_text(record.get("url"))

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=(
                optional_text(detail.get("title"))
                or optional_text(schema.get("title"))
                or optional_text(record.get("title"))
            ),
            company=extract_company(schema) or "CSEM",
            location=(
                optional_text(detail.get("location"))
                or extract_schema_location(schema)
                or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(schema.get("datePosted")),
            employment_type=extract_employment_type(record, detail),
            description=(
                optional_multiline_text(detail.get("description"))
                or schema_description(schema)
                or optional_multiline_text(record.get("teaser"))
            ),
            raw=raw,
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    result_count_text = optional_text(page.css("p.result-count::text").get())
    result_count_match = (
        RESULT_COUNT_PATTERN.search(result_count_text) if result_count_text else None
    )
    if result_count_match is None:
        raise CsemParseError("CSEM listing page is missing its result count")
    expected_count = int(result_count_match.group(1))

    schemas_by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for schema in extract_job_posting_schemas(page):
        title_key = normalized_title(schema.get("title"))
        if title_key:
            schemas_by_title[title_key].append(schema)

    records: list[dict[str, Any]] = []
    cards = page.css('a.job-teaser[href*="/jobs/"]')
    for card in cards:
        path = optional_text(card.attrib.get("href"))
        title = optional_text(card.css("h3::text").get())
        job_id = extract_job_id(path)
        if not path or not title or not job_id:
            raise CsemParseError("CSEM listing contains an incomplete vacancy")

        tags = normalized_texts(card.css(".tags-wrapper .tag::text").getall())
        title_schemas = schemas_by_title.get(normalized_title(title), [])
        schema = title_schemas.pop(0) if title_schemas else {}
        records.append(
            {
                "id": job_id,
                "title": title,
                "category": optional_text(card.css("p.tax::text").get()),
                "teaser": optional_multiline_text(
                    "\n".join(card.css(".intro-text ::text").getall())
                ),
                "schedule": tags[0] if tags else None,
                "contract_type": tags[1] if len(tags) > 1 else None,
                "location": tags[2] if len(tags) > 2 else None,
                "tags": tags,
                "url": urljoin(page_url, path),
                "listing_page_url": page_url,
                "schema": schema,
            }
        )

    if len(records) != expected_count:
        raise CsemParseError(
            f"CSEM listed {len(records)} vacancies but declared {expected_count} results"
        )
    return records


def parse_detail_html(page_html: str) -> dict[str, Any]:
    page = Selector(page_html)
    title = optional_text(page.css(".job-page .wrapper h1::text").get())
    canonical_url = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    apply_url = optional_text(
        page.css('a[href*="apps.csem.ch/jobs/register.aspx"]::attr(href)').get()
    )
    description = optional_multiline_text("\n".join(page.css(".job-content ::text").getall()))
    if not title or not canonical_url or not apply_url or not description:
        raise CsemParseError("CSEM detail page is missing required vacancy data")

    info = normalized_texts(page.css(".info-group .info-item ::text").getall())
    return {
        "title": title,
        "canonical_url": canonical_url,
        "apply_url": apply_url,
        "category": optional_text(page.css(".title-label::text").get()),
        "workload": info[0] if info else None,
        "contract_type": info[1] if len(info) > 1 else None,
        "location": info[2] if len(info) > 2 else None,
        "info": info,
        "description": description,
    }


def extract_job_posting_schemas(page: Selector) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
            continue
        postings.extend(
            candidate for candidate in walk_json(payload) if candidate.get("@type") == "JobPosting"
        )
    return postings


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


def extract_employment_type(
    record: dict[str, Any],
    detail: dict[str, Any],
) -> str | None:
    values = [
        optional_text(record.get("schedule")),
        optional_text(detail.get("contract_type")) or optional_text(record.get("contract_type")),
        optional_text(detail.get("workload")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def schema_description(schema: dict[str, Any]) -> str | None:
    value = optional_text(schema.get("description"))
    return html_to_text(value) if value else None


def deduplicate_csem_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalized_title(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def normalized_texts(values: Iterable[Any]) -> list[str]:
    return [text for value in values if (text := optional_text(value))]


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
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
