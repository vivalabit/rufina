from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ELCA_JOBS_BASE_URL = (
    "https://iaaras.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs"
)
ELCA_JOBS_API_URL = "https://iaaras.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest"
ELCA_SITE_NUMBER = "CX_1"
ELCA_SWITZERLAND_LOCATION_ID = "300000000447207"
ELCA_RESULTS_PER_PAGE = 25
ELCA_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_ID_PATTERN = re.compile(r"^\d+$")


class ElcaParseError(DirectCompanyRequestError):
    pass


class ElcaJobsParser:
    """Collect ELCA vacancies published for Switzerland in Oracle HCM."""

    parser_id = "elca"

    def __init__(
        self,
        *,
        base_url: str = ELCA_JOBS_BASE_URL,
        api_url: str = ELCA_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ELCA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except ElcaParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("ELCA vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("ELCA vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_elca_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} ELCA vacancies from {total} Swiss catalog "
                f"records across {pages_fetched} API page requests"
            ),
        )

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        finder = ",".join(
            (
                f"siteNumber={ELCA_SITE_NUMBER}",
                f"selectedLocationsFacet={ELCA_SWITZERLAND_LOCATION_ID}",
                f"limit={ELCA_RESULTS_PER_PAGE}",
                f"offset={offset}",
                "sortBy=POSTING_DATES_DESC",
            )
        )
        response = client.get(
            f"{self.api_url}/recruitingCEJobRequisitions",
            params={
                "onlyData": "true",
                "expand": "requisitionList",
                "finder": f"findReqs;{finder}",
            },
        )
        response.raise_for_status()
        page_offset, total, records = parse_listing_payload(response.json())
        if page_offset != offset:
            raise ElcaParseError(
                f"ELCA returned offset {page_offset} for requested offset {offset}"
            )
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        pages_fetched = 0
        last_total = 0
        last_unique = 0

        # Oracle offset pages can shift while vacancies are published. Accept
        # only a pass whose declared count, record count and stable IDs agree.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            expected_total = first_page[1]
            last_total = expected_total
            required_pages = max(1, ceil(expected_total / ELCA_RESULTS_PER_PAGE))
            if required_pages > self.max_pages:
                raise ElcaParseError(
                    f"ELCA exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            pages = [first_page]
            for offset in range(
                ELCA_RESULTS_PER_PAGE,
                expected_total,
                ELCA_RESULTS_PER_PAGE,
            ):
                pages.append(self.fetch_listing_page(client, offset=offset))
                pages_fetched += 1

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            records_seen = 0
            for offset, page_total, records in pages:
                if page_total != expected_total or (offset < expected_total and not records):
                    catalog_changed = True
                    break
                records_seen += len(records)
                for record in records:
                    job_id = optional_text(record.get("Id"))
                    if not job_id:
                        continue
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)

            last_unique = len(records_by_id)
            if catalog_changed or records_seen != expected_total:
                continue
            if last_unique == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total

        raise ElcaParseError(
            f"ELCA yielded only {last_unique} unique vacancies of {last_total} "
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
            job_id = str(record["Id"])
            try:
                response = client.get(
                    f"{self.api_url}/recruitingCEJobRequisitionDetails",
                    params={
                        "expand": "all",
                        "onlyData": "true",
                        "finder": f"ById;Id={job_id},siteNumber={ELCA_SITE_NUMBER}",
                    },
                )
                response.raise_for_status()
                return record, parse_detail_payload(
                    response.json(),
                    expected_job_id=job_id,
                )
            except (httpx.HTTPError, ElcaParseError, ValueError) as exc:
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
        job_id = optional_text(record.get("Id"))
        public_url = build_job_url(self.base_url, job_id) if job_id else self.base_url

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("Title")) or optional_text(record.get("Title")),
            company=first_text(
                detail.get("LegalEmployer"),
                detail.get("Organization"),
                record.get("LegalEmployer"),
                "ELCA",
            ),
            location=extract_location(detail or record),
            url=public_url,
            apply_url=build_apply_url(public_url),
            posted_at=(
                optional_text(detail.get("ExternalPostedStartDate"))
                or optional_text(record.get("PostedDate"))
            ),
            employment_type=first_text(
                detail.get("JobSchedule"),
                detail.get("ContractType"),
                detail.get("WorkerType"),
                detail.get("JobType"),
                record.get("JobSchedule"),
            ),
            seniority=first_text(
                detail.get("JobLevel"),
                detail.get("RequisitionType"),
                record.get("ManagerLevel"),
            ),
            description=extract_description(detail or record),
            raw=dict(record),
        )


def parse_listing_payload(payload: Any) -> tuple[int, int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ElcaParseError("ELCA jobs response must be an object")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise ElcaParseError("ELCA jobs response has invalid search results")
    result = items[0]
    total = result.get("TotalJobsCount")
    offset = result.get("Offset")
    records = result.get("requisitionList")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ElcaParseError("ELCA jobs response has an invalid total")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ElcaParseError("ELCA jobs response has an invalid offset")
    if not isinstance(records, list):
        raise ElcaParseError("ELCA jobs response has invalid vacancies")

    normalized: list[dict[str, Any]] = []
    for item in records:
        if (
            not isinstance(item, dict)
            or not valid_job_id(item.get("Id"))
            or not optional_text(item.get("Title"))
            or not is_swiss_vacancy(item)
        ):
            raise ElcaParseError("ELCA jobs response contains an incomplete or non-Swiss vacancy")
        normalized.append(item)
    return offset, total, normalized


def parse_detail_payload(payload: Any, *, expected_job_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ElcaParseError("ELCA detail response must be an object")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise ElcaParseError("ELCA detail response has invalid vacancy data")
    detail = items[0]
    if (
        optional_text(detail.get("Id")) != expected_job_id
        or not optional_text(detail.get("Title"))
        or not is_swiss_vacancy(detail)
    ):
        raise ElcaParseError("ELCA detail response returned another vacancy")
    return detail


def is_swiss_vacancy(record: dict[str, Any]) -> bool:
    if optional_text(record.get("PrimaryLocationCountry")) == "CH":
        return True
    for key in ("secondaryLocations", "otherWorkLocations", "workLocation"):
        locations = record.get(key)
        if not isinstance(locations, list):
            continue
        for location in locations:
            if not isinstance(location, dict):
                continue
            if first_text(location.get("CountryCode"), location.get("Country")) == "CH":
                return True
            if optional_text(location.get("GeographyId")) == ELCA_SWITZERLAND_LOCATION_ID:
                return True
    return False


def extract_location(record: dict[str, Any]) -> str | None:
    locations: list[str] = []
    primary = optional_text(record.get("PrimaryLocation"))
    if primary:
        locations.append(primary)
    for key in ("secondaryLocations", "otherWorkLocations"):
        values = record.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            location = first_text(
                value.get("Name"),
                value.get("LocationName"),
                value.get("locationName"),
            )
            if location and location not in locations:
                locations.append(location)
    if locations:
        return "; ".join(locations)

    work_locations = record.get("workLocation")
    if isinstance(work_locations, list):
        for value in work_locations:
            if isinstance(value, dict) and (
                location := first_text(value.get("LocationName"), value.get("TownOrCity"))
            ):
                locations.append(location)
    return "; ".join(dict.fromkeys(locations)) or None


def extract_description(record: dict[str, Any]) -> str | None:
    sections: list[str] = []
    for label, key in (
        ("Description", "ExternalDescriptionStr"),
        ("Responsibilities", "ExternalResponsibilitiesStr"),
        ("Qualifications", "ExternalQualificationsStr"),
        ("About ELCA", "CorporateDescriptionStr"),
    ):
        content = html_to_text(record.get(key))
        if content:
            sections.append(f"{label}\n{content}")
    if sections:
        return "\n\n".join(sections)
    return html_to_text(record.get("ShortDescriptionStr"))


def build_job_url(base_url: str, job_id: str) -> str:
    parts = urlsplit(base_url)
    base_path = parts.path.rstrip("/").removesuffix("/jobs")
    return urlunsplit((parts.scheme, parts.netloc, f"{base_path}/job/{job_id}", "", ""))


def build_apply_url(public_url: str) -> str:
    return f"{public_url.rstrip('/')}/apply/email"


def deduplicate_elca_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = optional_text(job.raw.get("Id"))
        key = job_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def first_text(*values: Any) -> str | None:
    for value in values:
        if text := optional_text(value):
            return text
    return None


def valid_job_id(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and JOB_ID_PATTERN.fullmatch(text))


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
