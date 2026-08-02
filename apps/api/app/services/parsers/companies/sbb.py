from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

SBB_JOBS_BASE_URL = "https://company.sbb.ch/de/jobs-karriere/jobs/offene-stellen.html"
SBB_RESULTS_PER_PAGE = 10

# Attribute IDs are part of the JSON contract consumed by SBB's own jobfilter module.
SBB_ATTRIBUTE_LOCATION = "100"
SBB_ATTRIBUTE_REGION = "110"
SBB_ATTRIBUTE_TOPICS = "20"
SBB_ATTRIBUTE_EMPLOYMENT_TYPE = "50"
SBB_ATTRIBUTE_SENIORITY = "60"
SBB_ATTRIBUTE_COUNTRY = "65"
SBB_ATTRIBUTE_PERCENTAGE = "160"
SBB_ATTRIBUTE_WORK_SMART = "130"


PageFetcher = Callable[[str], ScraplingResponse]


class SbbParseError(DirectCompanyRequestError):
    pass


class SbbJobsParser:
    """Collect all jobs from SBB's official career-page data source with Scrapling."""

    parser_id = "sbb"

    def __init__(
        self,
        *,
        base_url: str = SBB_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        fetch_page: PageFetcher | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.fetch_page = fetch_page or self._fetch_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        search_url = self.build_page_url(1)
        try:
            landing_page = self.fetch_page(search_url)
            api_url = self.extract_api_url(landing_page)
            payload = self.fetch_page(api_url).json()
            records = self.parse_records(payload)
        except SbbParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError("SBB vacancy request failed") from exc

        total = len(records)
        starts = page_start_items(total)
        jobs: list[ParsedJob] = []
        # SBB renders every startItem window from this same JSON payload. Fetch it
        # once, then retain the public 1, 11, 21... page URL for each ten-job slice.
        for start_item in starts:
            page_url = self.build_page_url(start_item)
            page_records = records[start_item - 1 : start_item - 1 + SBB_RESULTS_PER_PAGE]
            jobs.extend(
                self.normalize_job(
                    record,
                    listing_page_url=page_url,
                    total_available=total,
                )
                for record in page_records
            )

        if request.deduplicate:
            jobs = deduplicate_sbb_jobs(jobs)

        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=search_url,
            jobs=jobs,
            message=(
                f"Scanned {total} SBB vacancies across {len(starts)} logical pages"
            ),
        )

    def _fetch_with_scrapling(self, url: str) -> ScraplingResponse:
        return Fetcher.get(
            url,
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )

    def build_page_url(self, start_item: int) -> str:
        if start_item < 1 or (start_item - 1) % SBB_RESULTS_PER_PAGE:
            raise ValueError("SBB startItem must be 1 and then increase by 10")
        parts = urlsplit(self.base_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["startItem"] = str(start_item)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    def extract_api_url(self, page: ScraplingResponse) -> str:
        api_path = page.css('[data-init="jobfilter"]::attr(data-jobfilter-api)').get()
        if not api_path:
            api_path = page.css(".mod_jobfilter::attr(data-jobfilter-api)").get()
        if not api_path:
            raise SbbParseError("SBB jobfilter API URL was not found")
        return urljoin(self.base_url, str(api_path).strip())

    @staticmethod
    def parse_records(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise SbbParseError("SBB jobfilter response must be a list")
        return [record for record in payload if isinstance(record, dict)]

    def normalize_job(
        self,
        record: dict[str, Any],
        *,
        listing_page_url: str,
        total_available: int,
    ) -> ParsedJob:
        attributes = record.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        links = record.get("links")
        links = links if isinstance(links, dict) else {}
        url = optional_text(links.get("directlink"))

        raw = dict(record)
        raw["listing_page_url"] = listing_page_url
        raw["total_available"] = total_available

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company="SBB CFF FFS",
            location=first_attribute(attributes, SBB_ATTRIBUTE_LOCATION),
            url=url,
            apply_url=url,
            posted_at=optional_text(record.get("start_date")),
            employment_type=joined_attribute(
                attributes,
                SBB_ATTRIBUTE_EMPLOYMENT_TYPE,
            ),
            seniority=joined_attribute(attributes, SBB_ATTRIBUTE_SENIORITY),
            description=build_compact_description(attributes),
            raw=raw,
        )


def page_start_items(total: int) -> list[int]:
    """Return 1, 11, ... through the page containing the final vacancy."""

    if total <= 0:
        return []
    return list(range(1, total + 1, SBB_RESULTS_PER_PAGE))


def attribute_values(attributes: dict[str, Any], key: str) -> list[str]:
    value = attributes.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [text for item in value if (text := optional_text(item))]


def first_attribute(attributes: dict[str, Any], key: str) -> str | None:
    values = attribute_values(attributes, key)
    return values[0] if values else None


def joined_attribute(attributes: dict[str, Any], key: str) -> str | None:
    values = attribute_values(attributes, key)
    return ", ".join(values) if values else None


def build_compact_description(attributes: dict[str, Any]) -> str | None:
    fields = (
        ("Tätigkeitsgebiet", joined_attribute(attributes, SBB_ATTRIBUTE_TOPICS)),
        ("Region", joined_attribute(attributes, SBB_ATTRIBUTE_REGION)),
        ("Pensum", first_attribute(attributes, SBB_ATTRIBUTE_PERCENTAGE)),
        ("Land", first_attribute(attributes, SBB_ATTRIBUTE_COUNTRY)),
        (
            "Work Smart",
            "Ja" if first_attribute(attributes, SBB_ATTRIBUTE_WORK_SMART) == "true" else None,
        ),
    )
    values = [f"{label}: {value}" for label, value in fields if value]
    return ". ".join(values) if values else None


def deduplicate_sbb_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("viewkey")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
