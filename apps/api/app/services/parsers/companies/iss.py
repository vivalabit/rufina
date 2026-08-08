from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ISS_JOBS_BASE_URL = "https://www.ch.issworld.com/de-ch/karriere/offene-stellen"
ISS_JOBS_API_URL = "https://live.solique.ch/ISS/de/ajax/"
ISS_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-CH,de;q=0.9,fr;q=0.8,it;q=0.7,en;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DETAIL_ID_PATTERN = re.compile(r"/details/(\d+)/?", re.IGNORECASE)


class IssParseError(DirectCompanyRequestError):
    pass


class IssJobsParser:
    """Collect the complete ISS Switzerland catalog from Solique."""

    parser_id = "iss"

    def __init__(
        self,
        *,
        base_url: str = ISS_JOBS_BASE_URL,
        api_url: str = ISS_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def job_board_origin(self) -> str:
        parts = urlsplit(self.api_url)
        return f"{parts.scheme}://{parts.netloc}"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **ISS_HEADERS,
                    "Referer": f"{self.job_board_origin}/ISS/de/",
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records = parse_listing_payload(response.json())
                self.enrich_records(client, records)
        except IssParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("ISS vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("ISS vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_iss_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} ISS vacancies from the Solique catalog",
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
            detail_url = self.build_job_url(record)
            try:
                response = client.get(detail_url, headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(response.text)
            except (httpx.HTTPError, IssParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def build_job_url(self, record: dict[str, Any]) -> str:
        path = optional_text(record.get("link"))
        return urljoin(f"{self.job_board_origin}/", path or "ISS/de/")

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        posting = detail.get("job_posting")
        posting = posting if isinstance(posting, dict) else {}
        organization = posting.get("hiringOrganization")
        organization = organization if isinstance(organization, dict) else {}
        public_url = optional_text(detail.get("canonical_url")) or self.build_job_url(record)
        description = optional_multiline_text(detail.get("description")) or optional_multiline_text(
            record.get("fullTextSearch")
        )

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=(optional_text(record.get("jobTitle")) or optional_text(posting.get("title"))),
            company=(optional_text(organization.get("name")) or "ISS Facility Services AG"),
            location=extract_location(record, posting),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=(
                optional_text(posting.get("datePosted")) or optional_text(record.get("publicDate"))
            ),
            employment_type=extract_employment_type(record, detail),
            seniority=optional_text(record.get("function")),
            description=description,
            raw=raw,
        )


def parse_listing_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise IssParseError("ISS jobs response must be an object")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise IssParseError("ISS jobs response has invalid jobs")

    records: list[dict[str, Any]] = []
    for item in jobs:
        if (
            not isinstance(item, dict)
            or not extract_job_id(item)
            or not optional_text(item.get("jobTitle"))
            or not optional_text(item.get("link"))
        ):
            raise IssParseError("ISS jobs response contains an incomplete vacancy")
        records.append(item)

    validate_catalog_count(payload, records)
    return records


def validate_catalog_count(
    payload: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    employment_types = payload.get("employmentType")
    if not isinstance(employment_types, list):
        return
    counts: list[int] = []
    for item in employment_types:
        if not isinstance(item, dict):
            return
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return
        counts.append(count)
    if counts and sum(counts) != len(records):
        raise IssParseError("ISS jobs response does not match its employment-type totals")


def parse_detail_html(page_html: str) -> dict[str, Any]:
    page = Selector(page_html)
    posting: dict[str, Any] | None = None
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            candidate = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if posting is None:
        raise IssParseError("ISS detail page is missing JobPosting JSON-LD")

    canonical_url = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    apply_url = optional_text(page.css("a.apply-btn::attr(href)").get())
    if not canonical_url or not apply_url:
        raise IssParseError("ISS detail page is missing canonical or apply URL")

    short_description = optional_multiline_text(
        "\n".join(page.css(".short-description ::text").getall())
    )
    posting_description = optional_text(posting.get("description"))
    description_parts = [
        value
        for value in (
            short_description,
            html_to_text(posting_description) if posting_description else None,
        )
        if value
    ]
    return {
        "canonical_url": canonical_url,
        "apply_url": apply_url,
        "workload": optional_text(page.css(".workload::text").get()),
        "description": "\n\n".join(dict.fromkeys(description_parts)),
        "job_posting": posting,
    }


def extract_job_id(record: dict[str, Any]) -> str | None:
    link = optional_text(record.get("link"))
    match = DETAIL_ID_PATTERN.search(link) if link else None
    return match.group(1) if match else None


def extract_location(
    record: dict[str, Any],
    posting: dict[str, Any],
) -> str | None:
    listing_location = optional_text(record.get("locationFreeText"))
    if listing_location:
        return listing_location

    job_location = posting.get("jobLocation")
    job_location = job_location if isinstance(job_location, dict) else {}
    address = job_location.get("address")
    address = address if isinstance(address, dict) else {}
    values = [
        optional_text(address.get("postalCode")),
        optional_text(address.get("addressLocality")),
        optional_text(address.get("addressRegion")),
        optional_text(address.get("addressCountry")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def extract_employment_type(
    record: dict[str, Any],
    detail: dict[str, Any],
) -> str | None:
    values = [
        optional_text(record.get("employmentType")),
        optional_text(detail.get("workload")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def deduplicate_iss_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text)) or ""


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
