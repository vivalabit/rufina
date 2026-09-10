from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

EDOREX_JOBS_URL = "https://edorex.ch/jobs"
EDOREX_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/jobs/([a-z0-9]+(?:-[a-z0-9]+)*)$")
LINK_APPLY_PATH_PATTERN = re.compile(r"^/cvdropper/[0-9a-f]{32}/DE$")
ODM_APPLY_FRAGMENT_PATTERN = re.compile(r"^!/cvdropper/[0-9a-f]{32}/DE$")
DATE_PATTERN = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
EXPECTED_COMPANY = "Edorex AG"
EXPECTED_COMPANY_URL = "https://edorex.ch"
EXPECTED_COMPANY_ID = "https://edorex.ch#organization"
EXPECTED_LOCATION = "Ostermundigen"
EMPLOYMENT_TYPES = {
    "Vollzeit": "FULL_TIME",
    "Lehrstelle": "INTERN",
}


class EdorexParseError(DirectCompanyRequestError):
    pass


class EdorexJobsParser:
    """Collect Edorex AG's complete server-rendered Swiss vacancy catalog."""

    parser_id = "edorex"

    def __init__(
        self,
        *,
        base_url: str = EDOREX_JOBS_URL,
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
                headers={**EDOREX_HEADERS, "Referer": self.base_url},
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
        except EdorexParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Edorex vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Edorex vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_edorex_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Edorex Switzerland vacancies from the official catalog"),
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
                    expected_posted_at=record["posted_at"],
                    expected_employment_type=record["employment_type"],
                )
            except (httpx.HTTPError, EdorexParseError, ValueError) as exc:
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
                optional_text(detail.get("location")) or format_location(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
            ),
            employment_type=optional_text(record.get("employment_type")),
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
        raise EdorexParseError("Edorex listing returned an unexpected page")

    page = Selector(page_html)
    containers = page.css('[class~="space-y-6"]')
    cards = containers.css(":scope > a")
    if len(containers) != 1 or not cards:
        raise EdorexParseError("Edorex listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        detail_url = urljoin(page_url, optional_text(card.attrib.get("href")) or "")
        job_id = extract_job_id(detail_url)
        title = selector_text(card, "h2")
        metadata = [
            value for node in card.css("div.mt-2 > span") if (value := html_to_text(node.get()))
        ]
        summaries = unique_selector_texts(card, "p")
        if len(metadata) != 3 or len(summaries) != 1 or not title:
            raise EdorexParseError("Edorex listing contains an incomplete vacancy")
        employment_type, location, posted_label = metadata
        posted_at = parse_display_date(posted_label)
        if (
            not job_id
            or not posted_at
            or employment_type not in EMPLOYMENT_TYPES
            or location != EXPECTED_LOCATION
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise EdorexParseError("Edorex listing contains incomplete or non-Swiss vacancy data")
        if job_id in seen_ids:
            raise EdorexParseError("Edorex listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "employment_type": employment_type,
                "location": location,
                "posted_at": posted_at,
                "summary": next(iter(summaries)),
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
    expected_posted_at: str,
    expected_employment_type: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_job_id:
        raise EdorexParseError("Edorex detail page returned a different vacancy")

    page = Selector(page_html)
    canonicals = {
        urljoin(page_url, value)
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    titles = unique_selector_texts(page, "main h1")
    schemas = list(extract_json_schemas(page))
    job_schemas = [item for item in schemas if item.get("@type") == "JobPosting"]
    organization_schemas = [item for item in schemas if item.get("@type") == "Organization"]
    if len(job_schemas) != 1 or len(organization_schemas) != 1:
        raise EdorexParseError("Edorex detail page is missing its structured data")
    job_schema = job_schemas[0]
    organization = organization_schemas[0]
    organization_address = organization.get("address")
    organization_address = organization_address if isinstance(organization_address, dict) else {}
    job_location = job_schema.get("jobLocation")
    job_location = job_location if isinstance(job_location, dict) else {}
    hiring_organization = job_schema.get("hiringOrganization")
    hiring_organization = hiring_organization if isinstance(hiring_organization, dict) else {}
    apply_urls = {
        normalized
        for raw in page.css("a::attr(href)").getall()
        if (normalized := normalize_apply_url(urljoin(page_url, optional_text(raw) or "")))
    }
    description_nodes = page.css("main .prose.prose-lg")
    description = html_to_text(description_nodes[0].get()) if len(description_nodes) == 1 else None
    expected_schema_employment = EMPLOYMENT_TYPES.get(expected_employment_type)
    if (
        canonicals != {expected_url}
        or titles != {expected_title}
        or optional_text(job_schema.get("title")) != expected_title
        or normalize_iso_date(job_schema.get("datePosted")) != expected_posted_at
        or optional_text(job_schema.get("employmentType")) != expected_schema_employment
        or optional_text(hiring_organization.get("@id")) != EXPECTED_COMPANY_ID
        or optional_text(organization.get("@id")) != EXPECTED_COMPANY_ID
        or optional_text(organization.get("name")) != EXPECTED_COMPANY
        or not same_url(organization.get("url"), EXPECTED_COMPANY_URL)
        or optional_text(organization_address.get("addressCountry")) != "CH"
        or optional_text(organization_address.get("addressLocality")) != EXPECTED_LOCATION
        or optional_text(job_location.get("address")) != EXPECTED_LOCATION
        or len(apply_urls) != 1
        or not description
    ):
        raise EdorexParseError("Edorex detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": format_location(EXPECTED_LOCATION),
        "apply_url": next(iter(apply_urls)),
        "posted_at": expected_posted_at,
        "description": description,
        "structured_data": job_schema,
    }


def extract_json_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(html.unescape(str(raw)))
        except (TypeError, json.JSONDecodeError):
            continue
        yield from walk_json(payload)


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_display_date(value: Any) -> str | None:
    match = DATE_PATTERN.fullmatch(optional_text(value) or "")
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T.*)?", text or "")
    return match.group(1) if match else None


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1) if match else None


def is_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and extract_job_id(text) is not None
        and not parts.query
        and not parts.fragment
    )


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    host = parts.netloc.casefold()
    is_link = (
        host == "link.ostendis.com"
        and LINK_APPLY_PATH_PATTERN.fullmatch(parts.path)
        and not parts.fragment
    )
    is_odm = (
        host == "odm.ostendis.com"
        and parts.path == "/ojp/"
        and ODM_APPLY_FRAGMENT_PATTERN.fullmatch(parts.fragment)
    )
    tracking = parse_qs(parts.query, keep_blank_values=True)
    valid_tracking = not parts.query or (
        is_link and set(tracking) == {"src"}
        and len(tracking["src"]) == 1 and bool(tracking["src"][0])
    )
    if parts.scheme != "https" or not valid_tracking or not (is_link or is_odm):
        return None
    return text


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
        and not actual.query
        and not actual.fragment
        and not target.query
        and not target.fragment
    )


def format_location(value: Any) -> str | None:
    text = optional_text(value)
    return f"{text}, Switzerland" if text else None


def deduplicate_edorex_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_selector_texts(page: Selector, css: str) -> set[str]:
    return {value for raw in page.css(css).getall() if (value := html_to_text(str(raw)))}


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


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
