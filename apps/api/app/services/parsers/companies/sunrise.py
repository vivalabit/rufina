from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SUNRISE_JOBS_BASE_URL = "https://careers.sunrise.ch/gb/en/search-results"
SUNRISE_RESULTS_PER_PAGE = 10
SUNRISE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-GB;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DDO_PATTERN = re.compile(
    r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.experimentData",
    re.DOTALL,
)
CANONICAL_PATTERN = re.compile(
    r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class SunriseParseError(DirectCompanyRequestError):
    pass


class SunriseJobsParser:
    """Collect Sunrise vacancies from its server-rendered Phenom catalog."""

    parser_id = "sunrise"

    def __init__(
        self,
        *,
        base_url: str = SUNRISE_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def job_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        prefix = parts.path.rsplit("/search-results", maxsplit=1)[0].rstrip("/")
        return f"{parts.scheme}://{parts.netloc}{prefix}/job"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **SUNRISE_HEADERS,
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, _total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SunriseParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Sunrise vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Sunrise vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_sunrise_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Sunrise vacancies across {pages_fetched} catalog pages"),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # Offset pages can shift while Workday requisitions are being published.
        # Repeat the walk and union stable Phenom sequence numbers when necessary.
        for catalog_pass in range(self.max_catalog_passes):
            offsets = (
                list(range(0, expected_total, SUNRISE_RESULTS_PER_PAGE)) if expected_total else [0]
            )
            pass_records = 0

            for offset in offsets:
                response = client.get(
                    self.base_url,
                    params={"from": offset, "s": 1},
                )
                pages_fetched += 1
                response.raise_for_status()
                page_total, records = parse_listing_html(response.text)

                if expected_total is None:
                    expected_total = page_total
                    required_pages = max(
                        1,
                        ceil(expected_total / SUNRISE_RESULTS_PER_PAGE),
                    )
                    if required_pages > self.max_pages:
                        raise SunriseParseError(
                            f"Sunrise exposes {required_pages} pages, above the "
                            f"configured limit of {self.max_pages}"
                        )
                    offsets.extend(
                        range(
                            SUNRISE_RESULTS_PER_PAGE,
                            expected_total,
                            SUNRISE_RESULTS_PER_PAGE,
                        )
                    )
                elif page_total != expected_total:
                    raise SunriseParseError("Sunrise changed its vacancy total during pagination")

                if offset < (expected_total or 0) and not records:
                    raise SunriseParseError(
                        f"Sunrise page at offset {offset} was unexpectedly empty"
                    )

                pass_records += len(records)
                for record in records:
                    job_id = extract_job_id(record)
                    if not job_id:
                        continue
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)

            if pass_records > (expected_total or 0):
                raise SunriseParseError("Sunrise returned more vacancies than its declared total")
            if len(records_by_id) == (expected_total or 0):
                return list(records_by_id.values()), pages_fetched, expected_total or 0
            if len(records_by_id) > (expected_total or 0):
                raise SunriseParseError(
                    "Sunrise returned more unique vacancies than its declared total"
                )

        raise SunriseParseError(
            f"Sunrise yielded only {len(records_by_id)} unique vacancies of "
            f"{expected_total or 0} after {self.max_catalog_passes} catalog passes"
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
            except (httpx.HTTPError, SunriseParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def build_job_url(self, record: dict[str, Any]) -> str:
        job_id = extract_job_id(record) or "unknown"
        return f"{self.job_base_url}/{job_id}"

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        structure_data = detail.get("structureData")
        structure_data = structure_data if isinstance(structure_data, dict) else {}
        public_url = optional_text(detail.get("canonical_url")) or self.build_job_url(record)
        description_html = optional_text(detail.get("description")) or optional_text(
            structure_data.get("description")
        )
        description = (
            html_to_text(description_html)
            if description_html
            else optional_text(record.get("descriptionTeaser"))
        )

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=(optional_text(detail.get("title")) or optional_text(record.get("title"))),
            company=(
                optional_text(detail.get("companyName"))
                or optional_text(detail.get("company"))
                or "Sunrise Communications AG"
            ),
            location=extract_location(detail, record),
            url=public_url,
            apply_url=(
                optional_text(detail.get("applyUrl"))
                or optional_text(record.get("applyUrl"))
                or public_url
            ),
            posted_at=(
                optional_text(detail.get("postedDate"))
                or optional_text(structure_data.get("datePosted"))
                or optional_text(record.get("postedDate"))
            ),
            employment_type=(
                optional_text(detail.get("timeType"))
                or optional_text(detail.get("type"))
                or optional_text(record.get("type"))
            ),
            seniority=(
                optional_text(detail.get("jobProfile")) or optional_text(detail.get("jobProfiles"))
            ),
            description=description,
            raw=raw,
        )


def parse_listing_html(page_html: str) -> tuple[int, list[dict[str, Any]]]:
    ddo = parse_ddo(page_html)
    payload = ddo.get("eagerLoadRefineSearch")
    if not isinstance(payload, dict):
        raise SunriseParseError("Sunrise page is missing its vacancy catalog")

    status = payload.get("status")
    if status != 200:
        raise SunriseParseError("Sunrise vacancy catalog has an invalid status")
    total = payload.get("totalHits")
    hits = payload.get("hits")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise SunriseParseError("Sunrise vacancy catalog has an invalid totalHits")
    if isinstance(hits, bool) or not isinstance(hits, int) or hits < 0:
        raise SunriseParseError("Sunrise vacancy catalog has invalid hits")

    data = payload.get("data")
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list) or hits != len(jobs):
        raise SunriseParseError("Sunrise vacancy catalog has invalid jobs")

    records: list[dict[str, Any]] = []
    for item in jobs:
        if (
            not isinstance(item, dict)
            or not extract_job_id(item)
            or not optional_text(item.get("title"))
        ):
            raise SunriseParseError("Sunrise vacancy catalog contains an incomplete vacancy")
        records.append(item)
    return total, records


def parse_detail_html(page_html: str) -> dict[str, Any]:
    ddo = parse_ddo(page_html)
    payload = ddo.get("jobDetail")
    if not isinstance(payload, dict):
        raise SunriseParseError("Sunrise detail page is missing jobDetail")
    if payload.get("status") != 200:
        raise SunriseParseError("Sunrise detail page has an invalid status")
    data = payload.get("data")
    job = data.get("job") if isinstance(data, dict) else None
    if not isinstance(job, dict) or not extract_job_id(job):
        raise SunriseParseError("Sunrise detail page contains an invalid vacancy")

    detail = dict(job)
    canonical_match = CANONICAL_PATTERN.search(page_html)
    if canonical_match:
        detail["canonical_url"] = html.unescape(canonical_match.group(1))
    return detail


def parse_ddo(page_html: str) -> dict[str, Any]:
    match = DDO_PATTERN.search(page_html)
    if not match:
        raise SunriseParseError("Sunrise page is missing phApp.ddo data")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SunriseParseError("Sunrise page contains invalid phApp.ddo JSON") from exc
    if not isinstance(payload, dict):
        raise SunriseParseError("Sunrise phApp.ddo data must be an object")
    return payload


def extract_job_id(record: dict[str, Any]) -> str | None:
    return (
        optional_text(record.get("jobSeqNo"))
        or optional_text(record.get("jobId"))
        or optional_text(record.get("reqId"))
    )


def extract_location(
    detail: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    for record in (detail, listing):
        location = optional_text(record.get("cityStateCountry"))
        if location:
            return location

    multi_locations = detail.get("multi_location") or listing.get("multi_location")
    values: list[str] = []
    if isinstance(multi_locations, Sequence) and not isinstance(
        multi_locations,
        (str, bytes),
    ):
        for item in multi_locations:
            if isinstance(item, dict):
                value = optional_text(item.get("cityStateCountry")) or optional_text(
                    item.get("location")
                )
            else:
                value = optional_text(item)
            if value:
                values.append(value)
    if values:
        return ", ".join(dict.fromkeys(values))

    return optional_text(detail.get("address")) or optional_text(listing.get("address"))


def deduplicate_sunrise_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
