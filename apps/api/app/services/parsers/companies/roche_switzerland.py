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

ROCHE_SWITZERLAND_JOBS_BASE_URL = "https://careers.roche.com/global/en/search-results"
ROCHE_RESULTS_PER_PAGE = 10
ROCHE_SEARCH_FACETS = [
    "category",
    "subCategory",
    "country",
    "state",
    "city",
    "type",
    "jobLevel",
    "jobType",
]
ROCHE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
DDO_PATTERN = re.compile(
    r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.experimentData",
    re.DOTALL,
)
CSRF_PATTERN = re.compile(r'"csrfToken"\s*:\s*"([^"]+)"')
CANONICAL_PATTERN = re.compile(
    r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class RocheSwitzerlandParseError(DirectCompanyRequestError):
    pass


class RocheSwitzerlandJobsParser:
    """Collect Roche vacancies whose primary or additional location is Swiss."""

    parser_id = "roche_switzerland"

    def __init__(
        self,
        *,
        base_url: str = ROCHE_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        page_workers: int = 6,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.page_workers = max(1, page_workers)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def listing_endpoint(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/widgets"

    @property
    def job_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        prefix = parts.path.rsplit("/search-results", maxsplit=1)[0].rstrip("/")
        return f"{parts.scheme}://{parts.netloc}{prefix}/job"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ROCHE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                csrf_token = self.initialize_session(client)
                all_records, pages_fetched, total = self.collect_listing_records(
                    client,
                    csrf_token=csrf_token,
                )
                records = [record for record in all_records if is_swiss_vacancy(record)]
                if len(records) != total:
                    raise RocheSwitzerlandParseError(
                        f"Roche returned {len(records)} Swiss vacancies of {total} "
                        "country-filtered catalog records"
                    )
                self.enrich_records(client, records)
        except RocheSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Roche Switzerland vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Roche Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_roche_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Roche Switzerland vacancies across "
                f"{pages_fetched} Phenom page requests"
            ),
        )

    def initialize_session(self, client: httpx.Client) -> str:
        response = client.get(self.base_url)
        response.raise_for_status()
        match = CSRF_PATTERN.search(response.text)
        if not match:
            raise RocheSwitzerlandParseError("Roche careers page is missing its CSRF token")
        return match.group(1)

    def listing_payload(self, *, offset: int) -> dict[str, Any]:
        return {
            "lang": "en_global",
            "deviceType": "desktop",
            "country": "global",
            "pageName": "search-results",
            "pageId": "page11",
            "ddoKey": "refineSearch",
            "all_fields": ROCHE_SEARCH_FACETS,
            "pageType": "default",
            "from": offset,
            "size": ROCHE_RESULTS_PER_PAGE,
            "jobs": True,
            "counts": True,
            "clearAll": False,
            "jdsource": "facets",
            "isSliderEnable": False,
            "siteType": "external",
            "forceSpellCheck": True,
            "selected_fields": {"country": ["Switzerland"]},
            "keywords": "",
        }

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
        csrf_token: str,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.post(
            self.listing_endpoint,
            json=self.listing_payload(offset=offset),
            headers={
                "Accept": "application/json",
                "X-CSRF-TOKEN": csrf_token,
                "Referer": self.base_url,
            },
        )
        response.raise_for_status()
        total, records = parse_listing_payload(response.json())
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
        *,
        csrf_token: str,
    ) -> tuple[list[dict[str, Any]], int, int]:
        pages_fetched = 0
        last_total = 0
        last_unique = 0

        for catalog_pass in range(self.max_catalog_passes):
            initial_page = self.fetch_listing_page(
                client,
                offset=0,
                csrf_token=csrf_token,
            )
            pages_fetched += 1
            expected_total = initial_page[1]
            last_total = expected_total
            required_pages = max(1, ceil(expected_total / ROCHE_RESULTS_PER_PAGE))
            if required_pages > self.max_pages:
                raise RocheSwitzerlandParseError(
                    f"Roche exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            offsets = list(range(ROCHE_RESULTS_PER_PAGE, expected_total, ROCHE_RESULTS_PER_PAGE))
            page_results = [initial_page]
            if offsets:
                with ThreadPoolExecutor(
                    max_workers=min(self.page_workers, len(offsets))
                ) as executor:
                    futures = [
                        executor.submit(
                            self.fetch_listing_page,
                            client,
                            offset=offset,
                            csrf_token=csrf_token,
                        )
                        for offset in offsets
                    ]
                    page_results.extend(future.result() for future in as_completed(futures))
                pages_fetched += len(offsets)

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            pass_records = 0
            for offset, page_total, records in sorted(
                page_results,
                key=lambda result: result[0],
            ):
                if page_total != expected_total:
                    catalog_changed = True
                    break
                if offset < expected_total and not records:
                    catalog_changed = True
                    break
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

            last_unique = len(records_by_id)
            if catalog_changed or pass_records != expected_total:
                continue
            if last_unique == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total

        raise RocheSwitzerlandParseError(
            f"Roche yielded only {last_unique} unique vacancies of {last_total} "
            f"after {self.max_catalog_passes} catalog passes"
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
            expected_job_id = extract_job_id(record)
            try:
                response = client.get(detail_url, headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    expected_job_id=expected_job_id,
                )
            except (
                httpx.HTTPError,
                RocheSwitzerlandParseError,
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

    def build_job_url(self, record: dict[str, Any]) -> str:
        job_sequence = extract_job_sequence(record) or extract_job_id(record) or "unknown"
        return f"{self.job_base_url}/{job_sequence}"

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        structure_data = detail.get("structureData")
        structure_data = structure_data if isinstance(structure_data, dict) else {}
        additional_fields = detail.get("additionalFields")
        additional_fields = additional_fields if isinstance(additional_fields, dict) else {}
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
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(detail.get("companyName")) or "Roche",
            location=extract_swiss_location(detail, record) or "Switzerland",
            url=public_url,
            apply_url=(
                optional_text(detail.get("applyUrl"))
                or optional_text(record.get("applyUrl"))
                or public_url
            ),
            posted_at=(
                optional_text(structure_data.get("datePosted"))
                or optional_text(detail.get("postedDate"))
                or optional_text(record.get("postedDate"))
            ),
            employment_type=(
                optional_text(detail.get("type"))
                or optional_text(structure_data.get("employmentType"))
                or optional_text(record.get("type"))
            ),
            seniority=(
                optional_text(detail.get("jobLevel"))
                or optional_text(additional_fields.get("jobLevel"))
                or optional_text(detail.get("jobProfile"))
                or optional_text(record.get("jobLevel"))
            ),
            description=description,
            raw=raw,
        )


def parse_listing_payload(response_payload: Any) -> tuple[int, list[dict[str, Any]]]:
    payload = response_payload.get("refineSearch") if isinstance(response_payload, dict) else None
    if not isinstance(payload, dict):
        raise RocheSwitzerlandParseError("Roche page is missing its vacancy catalog")
    if payload.get("status") != 200:
        raise RocheSwitzerlandParseError("Roche vacancy catalog has an invalid status")

    total = payload.get("totalHits")
    hits = payload.get("hits")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RocheSwitzerlandParseError("Roche vacancy catalog has an invalid totalHits")
    if isinstance(hits, bool) or not isinstance(hits, int) or hits < 0:
        raise RocheSwitzerlandParseError("Roche vacancy catalog has invalid hits")

    data = payload.get("data")
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list) or hits != len(jobs):
        raise RocheSwitzerlandParseError("Roche vacancy catalog has invalid jobs")

    records: list[dict[str, Any]] = []
    for item in jobs:
        if (
            not isinstance(item, dict)
            or not extract_job_id(item)
            or not extract_job_sequence(item)
            or not optional_text(item.get("title"))
        ):
            raise RocheSwitzerlandParseError("Roche vacancy catalog contains an incomplete vacancy")
        records.append(item)
    return total, records


def parse_detail_html(
    page_html: str,
    *,
    expected_job_id: str | None,
) -> dict[str, Any]:
    ddo = parse_ddo(page_html)
    payload = ddo.get("jobDetail")
    if not isinstance(payload, dict):
        raise RocheSwitzerlandParseError("Roche detail page is missing jobDetail")
    if payload.get("status") != 200:
        raise RocheSwitzerlandParseError("Roche detail page has an invalid status")
    data = payload.get("data")
    job = data.get("job") if isinstance(data, dict) else None
    if (
        not isinstance(job, dict)
        or not extract_job_id(job)
        or extract_job_id(job) != expected_job_id
    ):
        raise RocheSwitzerlandParseError("Roche detail page contains an invalid vacancy")

    detail = dict(job)
    canonical_match = CANONICAL_PATTERN.search(page_html)
    if canonical_match:
        detail["canonical_url"] = html.unescape(canonical_match.group(1))
    return detail


def parse_ddo(page_html: str) -> dict[str, Any]:
    match = DDO_PATTERN.search(page_html)
    if not match:
        raise RocheSwitzerlandParseError("Roche page is missing phApp.ddo data")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RocheSwitzerlandParseError("Roche page contains invalid phApp.ddo JSON") from exc
    if not isinstance(payload, dict):
        raise RocheSwitzerlandParseError("Roche phApp.ddo data must be an object")
    return payload


def extract_job_id(record: dict[str, Any]) -> str | None:
    return optional_text(record.get("jobId")) or optional_text(record.get("reqId"))


def extract_job_sequence(record: dict[str, Any]) -> str | None:
    return optional_text(record.get("jobSeqNo"))


def record_locations(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "cityStateCountry",
        "location",
        "address",
        "country",
        "standardisedCountry",
    ):
        value = optional_text(record.get(key))
        if value:
            values.append(value)
    values.extend(extract_multi_locations(record))
    return list(dict.fromkeys(values))


def extract_multi_locations(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "multi_location",
        "multi_location_array",
        "additionalPostingLocations",
    ):
        locations = record.get(key)
        if not isinstance(locations, Sequence) or isinstance(locations, (str, bytes)):
            continue
        for item in locations:
            if isinstance(item, dict):
                value = (
                    optional_text(item.get("cityStateCountry"))
                    or optional_text(item.get("location"))
                    or optional_text(item.get("address"))
                    or optional_text(item.get("country"))
                )
            else:
                value = optional_text(item)
            if value:
                values.append(value)
    return list(dict.fromkeys(values))


def is_swiss_vacancy(record: dict[str, Any]) -> bool:
    return any("switzerland" in value.casefold() for value in record_locations(record))


def extract_swiss_location(
    detail: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    for record in (detail, listing):
        primary = optional_text(record.get("cityStateCountry")) or optional_text(
            record.get("location")
        )
        country = optional_text(record.get("country")) or optional_text(
            record.get("standardisedCountry")
        )
        if primary and (
            "switzerland" in primary.casefold() or (country and country.casefold() == "switzerland")
        ):
            return primary
        locations = [
            value for value in extract_multi_locations(record) if "switzerland" in value.casefold()
        ]
        if locations:
            return ", ".join(dict.fromkeys(locations))
    return None


def deduplicate_roche_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
