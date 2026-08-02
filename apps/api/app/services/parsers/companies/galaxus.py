from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

GALAXUS_CAREERS_URL = "https://jobs.migros.ch/de/unsere-unternehmen/galaxus"
GALAXUS_JOBS_URL = f"{GALAXUS_CAREERS_URL}/offene-stellen"
GALAXUS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class GalaxusParseError(DirectCompanyRequestError):
    pass


class GalaxusJobsParser:
    """Collect all Galaxus jobs exposed on the server-rendered Migros page."""

    parser_id = "galaxus"

    def __init__(
        self,
        *,
        base_url: str = GALAXUS_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=GALAXUS_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                )
                self.enrich_records(client, records)
        except GalaxusParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Galaxus vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Galaxus vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_galaxus_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} Galaxus vacancies from one page",
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
            detail_url = optional_text(record.get("url"))
            if not detail_url:
                return record, None
            try:
                response = client.get(detail_url, headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(response.text)
            except (httpx.HTTPError, GalaxusParseError, ValueError) as exc:
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
        url = optional_text(record.get("url"))

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(schema.get("title")) or optional_text(record.get("title")),
            company=extract_company(schema) or optional_text(record.get("company")) or "Galaxus",
            location=extract_schema_location(schema) or optional_text(record.get("location")),
            url=url,
            apply_url=optional_text(detail.get("apply_url")) or url,
            posted_at=optional_text(schema.get("datePosted")),
            employment_type=extract_employment_type(schema, record),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(schema.get("description"))
            ),
            raw=raw,
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    cards = page.css('li.search-layout-list-item a[href*="/job/galaxus/"]')
    records: list[dict[str, Any]] = []

    for card in cards:
        path = optional_text(card.attrib.get("href"))
        title = first_text(card.css("h3 span.font-bold::text").getall())
        if not path or not title:
            continue
        heading_parts = normalized_texts(card.css("h3 span::text").getall())
        workload = heading_parts[-1] if len(heading_parts) >= 2 else None
        attributes = normalized_texts(card.css("ul.dot-list li::text").getall())
        url = urljoin(page_url, path)
        records.append(
            {
                "id": path.rstrip("/").rsplit("/", 1)[-1],
                "title": title,
                "company": first_text(card.css("p::text").getall()) or "Galaxus",
                "location": attributes[0] if attributes else None,
                "employment_type": attributes[1] if len(attributes) > 1 else None,
                "workload": workload,
                "workplace_models": attributes[2:] if len(attributes) > 2 else [],
                "url": url,
                "listing_page_url": page_url,
            }
        )

    return records


def parse_detail_html(page_html: str) -> dict[str, Any]:
    page = Selector(page_html)
    schema = extract_job_posting_schema(page)
    summary = optional_text(schema.get("description"))
    tasks = normalized_texts(page.css("section#tasks p::text").getall())
    skill_headings = normalized_texts(page.css("section#skills h4::text").getall())
    skill_details = normalized_texts(page.css("section#skills p::text").getall())

    parts: list[str] = []
    if summary:
        parts.append(html_to_text(summary))
    if tasks:
        parts.append("Was du bewegst\n" + "\n".join(tasks))
    skills = [*skill_headings, *skill_details]
    if skills:
        parts.append("Was du mitbringst\n" + "\n".join(skills))

    return {
        "schema": schema,
        "description": "\n\n".join(part for part in parts if part).strip() or None,
        "tasks": tasks,
        "skills": skills,
        "apply_url": optional_text(
            page.css('a[href*="joboffer/apply"]::attr(href)').get()
        ),
    }


def extract_job_posting_schema(page: Selector) -> dict[str, Any]:
    for value in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            continue
        candidates: Sequence[Any] = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_type = candidate.get("@type")
            if candidate_type == "JobPosting" or (
                isinstance(candidate_type, list) and "JobPosting" in candidate_type
            ):
                return candidate
    raise GalaxusParseError("Galaxus JobPosting data was not found")


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
        postal_code = optional_text(address.get("postalCode"))
        value = " ".join(part for part in (postal_code, locality) if part)
        if value:
            values.append(value)
    unique = list(dict.fromkeys(values))
    return ", ".join(unique) if unique else None


def extract_employment_type(
    schema: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    workplace_models = listing.get("workplace_models")
    workplace_models = workplace_models if isinstance(workplace_models, list) else []
    values = [
        optional_text(schema.get("employmentType"))
        or optional_text(listing.get("employment_type")),
        optional_text(schema.get("workHours")) or optional_text(listing.get("workload")),
        *(optional_text(item) for item in workplace_models),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def deduplicate_galaxus_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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


def first_text(values: Iterable[Any]) -> str | None:
    return next((text for value in values if (text := optional_text(value))), None)


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None
