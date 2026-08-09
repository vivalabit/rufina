from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SWISSGRID_JOBS_BASE_URL = "https://www.swissgrid.ch/en/home/career/jobs.html"
SWISSGRID_JOBS_API_URL = (
    "https://www.swissgrid.ch/.rest/cloud/component-data"
    "?path=%2Fswissgrid%2Fen%2Fhome%2Fcareer%2Fjobs%2Fmain%2F"
    "joblist_transferred_11"
)
SWISSGRID_HEADERS = {
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7,it;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
INTERNAL_JOB_ID_PATTERN = re.compile(
    r'["\']internalId["\']\s*:\s*["\'](\d+)-',
    re.IGNORECASE,
)
WORKLOAD_RANGE_PATTERN = re.compile(r"\b(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%")
WORKLOAD_PERCENT_PATTERN = re.compile(r"\b(\d{1,3})\s*%")


class SwissgridParseError(DirectCompanyRequestError):
    pass


class SwissgridJobsParser:
    """Collect Swissgrid's full catalog and enrich its SuccessFactors jobs."""

    parser_id = "swissgrid"

    def __init__(
        self,
        *,
        base_url: str = SWISSGRID_JOBS_BASE_URL,
        api_url: str = SWISSGRID_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**SWISSGRID_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records = parse_listing_payload(response.json())
                self.enrich_records(client, records)
        except SwissgridParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Swissgrid vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Swissgrid vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_swissgrid_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Swissgrid vacancies from the full catalog endpoint"
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
            detail_url = optional_text(record.get("descriptionUrl"))
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
            except (httpx.HTTPError, SwissgridParseError, ValueError) as exc:
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
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        employment_type = join_unique(
            optional_text(record.get("typeOfEmployment")),
            extract_workload(title),
        )
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company=optional_text(detail.get("company")) or "Swissgrid",
            location=(
                optional_text(detail.get("location"))
                or optional_text(record.get("placeOfWork"))
            ),
            url=(
                optional_text(detail.get("public_url"))
                or optional_text(record.get("descriptionUrl"))
            ),
            apply_url=(
                optional_text(detail.get("apply_url"))
                or optional_text(record.get("applicationUrl"))
            ),
            posted_at=(
                optional_text(detail.get("posted_at"))
                or normalize_date(record.get("onlineSince"))
            ),
            employment_type=employment_type,
            seniority=optional_text(record.get("entryLevel")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise SwissgridParseError("Swissgrid jobs response must be an object")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise SwissgridParseError("Swissgrid jobs response has invalid jobs")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in jobs:
        if not isinstance(item, dict):
            raise SwissgridParseError(
                "Swissgrid jobs response contains an invalid vacancy"
            )
        job_id = optional_text(item.get("id"))
        if (
            not job_id
            or not optional_text(item.get("title"))
            or not optional_text(item.get("descriptionUrl"))
            or not optional_text(item.get("placeOfWork"))
            or not optional_text(item.get("department"))
        ):
            raise SwissgridParseError(
                "Swissgrid jobs response contains an incomplete vacancy"
            )
        if job_id in seen_ids:
            raise SwissgridParseError(
                "Swissgrid jobs response contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(dict(item))
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    if not page.css('[itemtype="http://schema.org/JobPosting"]').get():
        raise SwissgridParseError(
            "Swissgrid detail page is missing its JobPosting content"
        )

    title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    description_html = page.css(".jobdescription").get()
    description = html_to_text(description_html) if description_html else None
    apply_path = optional_text(page.css("a.dialogApplyBtn::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    internal_match = INTERNAL_JOB_ID_PATTERN.search(page_html)
    detail_job_id = internal_match.group(1) if internal_match else None
    if not title or not description or not apply_url or not detail_job_id:
        raise SwissgridParseError(
            "Swissgrid detail page contains an incomplete vacancy"
        )
    if expected_job_id and detail_job_id != expected_job_id:
        raise SwissgridParseError(
            "Swissgrid detail page returned a different vacancy"
        )

    locations = [
        location
        for value in page.css(
            'meta[itemprop="addressLocality"]::attr(content)'
        ).getall()
        if (location := optional_text(value))
    ]

    return {
        "id": detail_job_id,
        "title": title,
        "company": optional_text(
            page.css('meta[itemprop="hiringOrganization"]::attr(content)').get()
        ),
        "location": ", ".join(dict.fromkeys(locations)) or None,
        "public_url": page_url,
        "apply_url": apply_url,
        "posted_at": normalize_date(
            page.css('meta[itemprop="datePosted"]::attr(content)').get()
        ),
        "description": description,
    }


def extract_workload(title: str | None) -> str | None:
    if not title:
        return None
    range_match = WORKLOAD_RANGE_PATTERN.search(title)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}%"
    percent_match = WORKLOAD_PERCENT_PATTERN.search(title)
    return f"{percent_match.group(1)}%" if percent_match else None


def deduplicate_swissgrid_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    for date_format in (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%a %b %d %H:%M:%S UTC %Y",
    ):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def join_unique(*values: str | None) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


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
