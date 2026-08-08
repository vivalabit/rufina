from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from math import ceil
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AXA_SCHWEIZ_JOBS_BASE_URL = (
    "https://careers.axa.com/careers-home/jobs?country=Switzerland&page=1"
)
AXA_SCHWEIZ_JOBS_API_URL = "https://careers.axa.com/api/jobs"
AXA_SCHWEIZ_RESULTS_PER_PAGE = 100
AXA_SCHWEIZ_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,fr;q=0.8,it;q=0.7,en;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class AxaSchweizParseError(DirectCompanyRequestError):
    pass


class AxaSchweizJobsParser:
    """Collect the complete Swiss AXA catalog from its public iCIMS API."""

    parser_id = "axa_schweiz"

    def __init__(
        self,
        *,
        base_url: str = AXA_SCHWEIZ_JOBS_BASE_URL,
        api_url: str = AXA_SCHWEIZ_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **AXA_SCHWEIZ_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, _total = self.collect_listing_records(client)
        except AxaSchweizParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("AXA Schweiz vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("AXA Schweiz vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_axa_schweiz_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} AXA Schweiz vacancies across "
                f"{pages_fetched} API pages"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # Repeat offset-sensitive page walks and union stable requisition IDs.
        for catalog_pass in range(self.max_catalog_passes):
            page_numbers = (
                list(
                    range(
                        1,
                        ceil(expected_total / AXA_SCHWEIZ_RESULTS_PER_PAGE) + 1,
                    )
                )
                if expected_total
                else [1]
            )
            pass_records = 0

            for page_number in page_numbers:
                response = client.get(
                    self.api_url,
                    params={
                        "country": "Switzerland",
                        "page": page_number,
                        "limit": AXA_SCHWEIZ_RESULTS_PER_PAGE,
                    },
                )
                pages_fetched += 1
                response.raise_for_status()
                page_total, records = parse_listing_payload(response.json())

                if expected_total is None:
                    expected_total = page_total
                    required_pages = max(
                        1,
                        ceil(expected_total / AXA_SCHWEIZ_RESULTS_PER_PAGE),
                    )
                    if required_pages > self.max_pages:
                        raise AxaSchweizParseError(
                            f"AXA Schweiz exposes {required_pages} pages, above the "
                            f"configured limit of {self.max_pages}"
                        )
                    page_numbers.extend(range(2, required_pages + 1))
                elif page_total != expected_total:
                    raise AxaSchweizParseError(
                        "AXA Schweiz changed its vacancy total during pagination"
                    )

                if page_number <= ceil(
                    (expected_total or 0) / AXA_SCHWEIZ_RESULTS_PER_PAGE
                ) and not records:
                    raise AxaSchweizParseError(
                        f"AXA Schweiz page {page_number} was unexpectedly empty"
                    )

                pass_records += len(records)
                for record in records:
                    job_id = extract_job_id(record)
                    if not job_id:
                        continue
                    normalized = dict(record)
                    normalized["listing_page"] = page_number
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)

            if pass_records > (expected_total or 0):
                raise AxaSchweizParseError(
                    "AXA Schweiz returned more vacancies than its declared total"
                )
            if len(records_by_id) == (expected_total or 0):
                return list(records_by_id.values()), pages_fetched, expected_total or 0
            if len(records_by_id) > (expected_total or 0):
                raise AxaSchweizParseError(
                    "AXA Schweiz returned more unique vacancies than its declared total"
                )

        raise AxaSchweizParseError(
            f"AXA Schweiz yielded only {len(records_by_id)} unique vacancies of "
            f"{expected_total or 0} after {self.max_catalog_passes} catalog passes"
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        meta_data = record.get("meta_data")
        meta_data = meta_data if isinstance(meta_data, dict) else {}
        job_id = extract_job_id(record)
        language = optional_text(record.get("language"))
        public_url = optional_text(meta_data.get("canonical_url"))
        if not public_url and job_id:
            public_url = f"{origin(self.base_url)}/jobs/{job_id}"
            if language:
                public_url += f"?lang={language}"

        seniority = first_text(record.get("tags5"))
        if seniority and seniority.casefold() == "no level":
            seniority = None

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=(
                first_text(record.get("tags3"))
                or optional_text(record.get("hiring_organization"))
                or "AXA Schweiz"
            ),
            location=extract_location(record),
            url=public_url,
            apply_url=optional_text(record.get("apply_url")) or public_url,
            posted_at=optional_text(record.get("posted_date")),
            employment_type=extract_employment_type(record),
            seniority=seniority,
            description=optional_text(record.get("description")),
            raw=dict(record),
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise AxaSchweizParseError("AXA Schweiz jobs response must be an object")
    total = payload.get("totalCount")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise AxaSchweizParseError("AXA Schweiz jobs response has an invalid total")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise AxaSchweizParseError("AXA Schweiz jobs response has invalid jobs")

    records: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
            raise AxaSchweizParseError(
                "AXA Schweiz jobs response contains an invalid vacancy"
            )
        record = item["data"]
        if not extract_job_id(record) or not optional_text(record.get("title")):
            raise AxaSchweizParseError(
                "AXA Schweiz jobs response contains an incomplete vacancy"
            )
        records.append(record)
    return total, records


def extract_job_id(record: dict[str, Any]) -> str | None:
    return optional_text(record.get("req_id")) or optional_text(record.get("slug"))


def extract_location(record: dict[str, Any]) -> str | None:
    listed = optional_text(record.get("full_location"))
    if listed:
        return listed
    return ", ".join(
        value
        for value in (
            optional_text(record.get("postal_code")),
            optional_text(record.get("city")),
            optional_text(record.get("country")),
        )
        if value
    ) or None


def extract_employment_type(record: dict[str, Any]) -> str | None:
    values = [
        first_text(record.get("tags1")),
        first_text(record.get("tags2")),
    ]
    if not any(values):
        values.append(optional_text(record.get("employment_type")))
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def deduplicate_axa_schweiz_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def first_text(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return next((text for item in value if (text := optional_text(item))), None)
    return optional_text(value)


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
