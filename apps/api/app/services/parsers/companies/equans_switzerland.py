from __future__ import annotations

import re
from collections.abc import Iterable
from math import ceil
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

EQUANS_SWITZERLAND_JOBS_BASE_URL = (
    "https://www.equans.com/join-us?jobs_offer%5BrefinementList%5D%5Bcountry_en%5D"
    "%5B0%5D=Switzerland"
)
EQUANS_SWITZERLAND_JOBS_SEARCH_URL = "https://O7FDVQDWPV-dsn.algolia.net/1/indexes/jobs_offer/query"
EQUANS_ALGOLIA_APPLICATION_ID = "O7FDVQDWPV"
EQUANS_ALGOLIA_API_KEY = "2a5554adbdb2674d295f76ac88657541"
EQUANS_RESULTS_PER_PAGE = 24
EQUANS_FILTERS = "locale_en.id:en AND country_en:Switzerland"
EQUANS_ATTRIBUTES = (
    "objectID",
    "id",
    "title_en",
    "description_en",
    "country_en",
    "region_en",
    "locality_en",
    "state_en",
    "address_en",
    "zip_code_en",
    "contract_type_en",
    "job_scheddule_en",
    "url_en",
    "apply_url_en",
    "type",
    "created_at",
    "updated_at",
)
EQUANS_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_ID_PATTERN = re.compile(r"^\d+$")
JOB_PATH_PATTERN = re.compile(
    r"^/(?:en/)?jobs/(?P<id>\d+)-[a-z0-9][a-z0-9-]*$", re.IGNORECASE
)
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class EquansSwitzerlandParseError(DirectCompanyRequestError):
    pass


class EquansSwitzerlandJobsParser:
    """Collect the complete Equans catalog facet for Switzerland."""

    parser_id = "equans_switzerland"

    def __init__(
        self,
        *,
        base_url: str = EQUANS_SWITZERLAND_JOBS_BASE_URL,
        search_url: str = EQUANS_SWITZERLAND_JOBS_SEARCH_URL,
        application_id: str = EQUANS_ALGOLIA_APPLICATION_ID,
        api_key: str = EQUANS_ALGOLIA_API_KEY,
        timeout_seconds: float = 30.0,
        max_pages: int = 40,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.search_url = search_url
        self.application_id = application_id
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **EQUANS_HEADERS,
                    "Referer": self.base_url,
                    "x-algolia-application-id": self.application_id,
                    "x-algolia-api-key": self.api_key,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, page_requests, total = self.collect_records(client)
        except EquansSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Equans vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Equans vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_equans_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Equans Switzerland vacancies from "
                f"{total} Swiss catalog records across {page_requests} API page requests"
            ),
        )

    def fetch_page(
        self,
        client: httpx.Client,
        *,
        page: int,
    ) -> tuple[int, int, int, list[dict[str, Any]]]:
        response = client.post(
            self.search_url,
            json={
                "query": "",
                "filters": EQUANS_FILTERS,
                "hitsPerPage": EQUANS_RESULTS_PER_PAGE,
                "page": page,
                "facets": ["country_en"],
                "attributesToRetrieve": list(EQUANS_ATTRIBUTES),
            },
        )
        response.raise_for_status()
        return parse_search_payload(response.json(), expected_page=page)

    def collect_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        page_requests = 0
        last_total = 0
        last_unique = 0

        # Algolia pages can shift when an offer is added or removed. Accept a
        # snapshot only when every page agrees on totals and all IDs are unique.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_page(client, page=0)
            page_requests += 1
            expected_total = first_page[1]
            expected_pages = first_page[2]
            last_total = expected_total
            required_pages = max(1, ceil(expected_total / EQUANS_RESULTS_PER_PAGE))
            if expected_pages != (0 if expected_total == 0 else required_pages):
                raise EquansSwitzerlandParseError(
                    "Equans catalog pagination is incomplete for its declared total"
                )
            if required_pages > self.max_pages:
                raise EquansSwitzerlandParseError(
                    f"Equans exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            pages = [first_page]
            for page in range(1, required_pages):
                pages.append(self.fetch_page(client, page=page))
                page_requests += 1

            records_by_id: dict[str, dict[str, Any]] = {}
            records_seen = 0
            catalog_changed = False
            for page, total, page_count, records in pages:
                if (
                    total != expected_total
                    or page_count != expected_pages
                    or (page < required_pages and not records and expected_total > 0)
                ):
                    catalog_changed = True
                    break
                records_seen += len(records)
                for record in records:
                    job_id = str(record["id"])
                    normalized = dict(record)
                    normalized["listing_page"] = page
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)

            last_unique = len(records_by_id)
            if catalog_changed or records_seen != expected_total:
                continue
            if last_unique == expected_total:
                return list(records_by_id.values()), page_requests, expected_total

        raise EquansSwitzerlandParseError(
            f"Equans yielded only {last_unique} unique vacancies of {last_total} "
            f"after {self.max_catalog_passes} catalog passes"
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        public_url = build_job_url(self.base_url, record.get("url_en"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title_en")),
            company="Equans",
            location=extract_location(record),
            url=public_url,
            # Equans publishes one generic SuccessFactors URL for every offer.
            # Keep the vacancy page so the offer ID/context is not lost.
            apply_url=public_url,
            posted_at=optional_text(record.get("created_at")),
            employment_type=extract_employment_type(record),
            seniority=None,
            description=optional_text(record.get("description_en")),
            raw=dict(record),
        )


def parse_search_payload(
    payload: Any,
    *,
    expected_page: int,
) -> tuple[int, int, int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise EquansSwitzerlandParseError("Equans search response must be an object")
    page = payload.get("page")
    total = payload.get("nbHits")
    pages = payload.get("nbPages")
    page_size = payload.get("hitsPerPage")
    hits = payload.get("hits")
    facets = payload.get("facets")
    country_facets = facets.get("country_en") if isinstance(facets, dict) else None
    if (
        isinstance(page, bool)
        or not isinstance(page, int)
        or page != expected_page
        or isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or isinstance(pages, bool)
        or not isinstance(pages, int)
        or pages < 0
        or page_size != EQUANS_RESULTS_PER_PAGE
        or not isinstance(hits, list)
        or payload.get("exhaustiveNbHits") is not True
        or not isinstance(country_facets, dict)
        or country_facets.get("Switzerland") != total
    ):
        raise EquansSwitzerlandParseError(
            "Equans search response has invalid pagination or Swiss facets"
        )

    records = [validate_record(hit) for hit in hits]
    return page, total, pages, records


def validate_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EquansSwitzerlandParseError("Equans catalog contains an invalid vacancy")
    job_id = optional_text(value.get("id"))
    object_id = optional_text(value.get("objectID"))
    title = optional_text(value.get("title_en"))
    description = optional_text(value.get("description_en"))
    public_path = optional_text(value.get("url_en"))
    path_match = JOB_PATH_PATTERN.fullmatch(urlsplit(public_path or "").path)
    region = value.get("region_en")
    region_country = (
        optional_text(region.get("hierarchicalTerm.lvl0")) if isinstance(region, dict) else None
    )
    if (
        not job_id
        or not JOB_ID_PATTERN.fullmatch(job_id)
        or object_id != job_id
        or not title
        or not description
        or optional_text(value.get("country_en")) != "Switzerland"
        or region_country != "Switzerland"
        or not optional_text(value.get("locality_en"))
        or not optional_text(value.get("state_en"))
        or not optional_text(value.get("zip_code_en"))
        or not path_match
        or path_match.group("id") != job_id
        or optional_text(value.get("type")) not in {"success_factor", "icims"}
        or not valid_timestamp(value.get("created_at"))
        or not valid_timestamp(value.get("updated_at"))
    ):
        raise EquansSwitzerlandParseError(
            "Equans catalog contains an incomplete or non-Swiss vacancy"
        )
    return dict(value)


def build_job_url(base_url: str, value: Any) -> str:
    path = optional_text(value)
    if not path:
        return base_url
    return urljoin(base_url, path)


def extract_location(record: dict[str, Any]) -> str | None:
    parts = [
        optional_text(record.get("locality_en")),
        optional_text(record.get("state_en")),
        optional_text(record.get("country_en")),
    ]
    return ", ".join(dict.fromkeys(part for part in parts if part)) or None


def extract_employment_type(record: dict[str, Any]) -> str | None:
    schedule = optional_text(record.get("job_scheddule_en"))
    contract = optional_text(record.get("contract_type_en"))
    if contract:
        contract = re.sub(r"^[A-Z]{3}_", "", contract).replace("_", " ")
    return " · ".join(dict.fromkeys(part for part in (contract, schedule) if part)) or None


def deduplicate_equans_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = optional_text(job.raw.get("id"))
        key = job_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def valid_timestamp(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and TIMESTAMP_PATTERN.fullmatch(text))


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
