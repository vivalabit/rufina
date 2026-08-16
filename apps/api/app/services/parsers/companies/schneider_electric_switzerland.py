from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

SCHNEIDER_ELECTRIC_SWITZERLAND_JOBS_BASE_URL = (
    "https://careers.se.com/jobs?lang=de-DE&country=Switzerland&page=1"
)
SCHNEIDER_ELECTRIC_COMPANY = "Schneider Electric"
SCHNEIDER_ELECTRIC_COUNTRY = "Switzerland"
SCHNEIDER_ELECTRIC_COUNTRY_CODE = "CH"
SCHNEIDER_ELECTRIC_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "Referer": SCHNEIDER_ELECTRIC_SWITZERLAND_JOBS_BASE_URL,
}
JOB_PATH_PATTERN = re.compile(r"^/jobs/(\d+)/?$")
APPLY_PATH_PATTERN = re.compile(r"^/jobs/(\d+)/login/?$")
ALLOWED_APPLY_HOSTS = {"careers-se.icims.com", "grcareers-se.icims.com"}


class SchneiderElectricSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SchneiderElectricSwitzerlandJobsParser:
    """Collect the complete Schneider Electric Switzerland Jibe catalog."""

    parser_id = "schneider_electric_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SCHNEIDER_ELECTRIC_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        page_workers: int = 8,
        fetch_page: Callable[[str], ScraplingResponse | Mapping[str, Any]] | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.page_workers = min(12, max(1, page_workers))
        self.fetch_page = fetch_page or self._fetch_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            records, total, pages_fetched, catalog_passes = self.collect_listing_records()
        except SchneiderElectricSwitzerlandParseError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Schneider Electric Switzerland vacancy parsing failed"
            ) from exc
        except Exception as exc:
            raise DirectCompanyRequestError(
                "Schneider Electric Switzerland vacancy request failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_schneider_electric_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Schneider Electric Switzerland "
                f"vacancies from {total} Jibe country records across "
                f"{pages_fetched} page requests in {catalog_passes} catalog "
                "pass(es)"
            ),
        )

    def _fetch_with_scrapling(self, url: str) -> ScraplingResponse:
        response = Fetcher.get(
            url,
            headers=SCHNEIDER_ELECTRIC_HEADERS,
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        status = int(getattr(response, "status", 0) or 0)
        if not 200 <= status < 300:
            raise SchneiderElectricSwitzerlandParseError(
                f"Schneider Electric careers API returned HTTP {status}"
            )
        return response

    def fetch_listing_page(
        self,
        *,
        page_number: int,
    ) -> tuple[int, int, int, list[dict[str, Any]]]:
        page_url = listing_page_url(self.base_url, page_number=page_number)
        response = self.fetch_page(page_url)
        payload = load_json_payload(response)
        total, page_size, records = parse_listing_payload(
            payload,
            page_url=page_url,
            expected_page=page_number,
        )
        return page_number, total, page_size, records

    def collect_listing_records(
        self,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        pages_fetched = 0
        last_unique_count = 0
        last_total = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_listing_page(page_number=1)
            pages_fetched += 1
            total = first_page[1]
            page_size = first_page[2]
            last_total = total
            total_pages = max(1, ceil(total / page_size))
            if total_pages > self.max_pages:
                raise SchneiderElectricSwitzerlandParseError(
                    f"Schneider Electric Switzerland exposes {total_pages} pages, "
                    f"above the configured limit of {self.max_pages}"
                )

            page_results = [first_page]
            remaining_pages = list(range(2, total_pages + 1))
            if remaining_pages:
                with ThreadPoolExecutor(
                    max_workers=min(self.page_workers, len(remaining_pages))
                ) as executor:
                    futures = [
                        executor.submit(
                            self.fetch_listing_page,
                            page_number=page_number,
                        )
                        for page_number in remaining_pages
                    ]
                    page_results.extend(future.result() for future in as_completed(futures))
                pages_fetched += len(remaining_pages)

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            for page_number, page_total, current_page_size, records in sorted(page_results):
                expected_count = min(
                    page_size,
                    max(0, total - ((page_number - 1) * page_size)),
                )
                if (
                    page_total != total
                    or current_page_size != page_size
                    or len(records) != expected_count
                ):
                    catalog_changed = True
                for record in records:
                    normalized = dict(record)
                    normalized["listing_page"] = page_number
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = total
                    job_id = normalized["id"]
                    if job_id in records_by_id:
                        catalog_changed = True
                    records_by_id.setdefault(job_id, normalized)

            last_unique_count = len(records_by_id)
            if not catalog_changed and last_unique_count == total:
                return (
                    list(records_by_id.values()),
                    total,
                    pages_fetched,
                    catalog_pass,
                )

        raise SchneiderElectricSwitzerlandParseError(
            f"Schneider Electric Switzerland yielded {last_unique_count} unique "
            f"vacancies of {last_total} country records"
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        description = optional_multiline_text(record.get("description"))
        salary_min = extract_minimum_salary(description)
        raw = dict(record)
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=SCHNEIDER_ELECTRIC_COMPANY,
            location=optional_text(record.get("location")),
            url=optional_text(record.get("url")),
            apply_url=optional_text(record.get("apply_url")),
            posted_at=optional_text(record.get("posted_at")),
            employment_type=normalize_employment_type(record.get("employment_type")),
            description=description,
            salary=(f"From CHF {salary_min:,} per year" if salary_min else None),
            salary_min=salary_min,
            salary_currency="CHF" if salary_min else None,
            salary_unit="year" if salary_min else None,
            raw=raw,
        )


def listing_page_url(base_url: str, *, page_number: int) -> str:
    parts = urlsplit(base_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    country = optional_text(params.get("country"))
    if (
        parts.scheme != "https"
        or parts.netloc.lower() != "careers.se.com"
        or parts.path.rstrip("/") != "/jobs"
        or country != SCHNEIDER_ELECTRIC_COUNTRY
    ):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric base URL lost its Switzerland country scope"
        )
    language = optional_text(params.get("lang")) or "de-DE"
    api_params = {
        "lang": language,
        "country": SCHNEIDER_ELECTRIC_COUNTRY,
        "page": str(max(1, page_number)),
        "internal": "false",
    }
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/api/jobs",
            urlencode(api_params),
            "",
        )
    )


def load_json_payload(
    response: ScraplingResponse | Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return response
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric careers API returned a non-object response"
        )
    return payload


def parse_listing_payload(
    payload: Mapping[str, Any],
    *,
    page_url: str,
    expected_page: int,
) -> tuple[int, int, list[dict[str, Any]]]:
    validate_api_url(page_url, expected_page=expected_page)
    total = required_non_negative_integer(payload.get("totalCount"), "totalCount")
    jobs = payload.get("jobs")
    filters = payload.get("filter")
    if not isinstance(jobs, Sequence) or isinstance(jobs, (str, bytes)):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric careers API is missing its jobs array"
        )
    if not isinstance(filters, Mapping):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric careers API is missing its filter contract"
        )
    page_size = required_positive_integer(filters.get("displayLimit"), "displayLimit")
    validate_country_facet(filters, total=total)

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in jobs:
        if not isinstance(item, Mapping) or not isinstance(item.get("data"), Mapping):
            raise SchneiderElectricSwitzerlandParseError(
                "Schneider Electric careers API contains a malformed vacancy"
            )
        record = normalize_api_record(item["data"])
        if record["id"] in seen_ids:
            raise SchneiderElectricSwitzerlandParseError(
                "Schneider Electric careers API contains duplicate vacancy IDs"
            )
        seen_ids.add(record["id"])
        records.append(record)

    return total, page_size, records


def normalize_api_record(data: Mapping[str, Any]) -> dict[str, Any]:
    job_id = optional_text(data.get("slug"))
    req_id = optional_text(data.get("req_id"))
    title = optional_text(data.get("title"))
    company = optional_text(data.get("hiring_organization"))
    description = optional_multiline_text(data.get("description"))
    language = optional_text(data.get("language"))
    if (
        not job_id
        or not job_id.isdigit()
        or req_id != job_id
        or not title
        or company != SCHNEIDER_ELECTRIC_COMPANY
        or not description
        or not language
    ):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric careers API contains an incomplete vacancy"
        )

    swiss_locations = collect_swiss_locations(data)
    if not swiss_locations:
        raise SchneiderElectricSwitzerlandParseError(
            f"Schneider Electric country facet returned non-Swiss vacancy {job_id}"
        )

    metadata = data.get("meta_data")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    canonical_url = optional_text(metadata.get("canonical_url"))
    public_url = canonical_url or urljoin(
        SCHNEIDER_ELECTRIC_SWITZERLAND_JOBS_BASE_URL,
        f"/jobs/{job_id}?lang={language}",
    )
    apply_url = optional_text(data.get("apply_url"))
    validate_public_url(public_url, expected_job_id=job_id)
    validate_apply_url(apply_url, expected_job_id=job_id)

    posted_at = extract_posted_at(data, metadata=metadata)
    categories = normalize_named_values(data.get("categories"))
    work_models = normalize_string_values(data.get("tags7"))
    return {
        "id": job_id,
        "title": title,
        "company": company,
        "location": "; ".join(swiss_locations),
        "swiss_locations": swiss_locations,
        "url": public_url,
        "apply_url": apply_url,
        "posted_at": posted_at,
        "employment_type": optional_text(data.get("employment_type")),
        "category": "; ".join(categories) if categories else None,
        "work_model": "; ".join(work_models) if work_models else None,
        "language": language,
        "description": description,
        "api": dict(data),
    }


def validate_api_url(page_url: str, *, expected_page: int) -> None:
    parts = urlsplit(page_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    if (
        parts.scheme != "https"
        or parts.netloc.lower() != "careers.se.com"
        or parts.path != "/api/jobs"
        or params.get("country") != SCHNEIDER_ELECTRIC_COUNTRY
        or params.get("page") != str(expected_page)
        or params.get("internal") != "false"
    ):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric careers API request lost its country or page scope"
        )


def validate_country_facet(filters: Mapping[str, Any], *, total: int) -> None:
    facet_list = filters.get("facetList")
    facets = facet_list.get("country") if isinstance(facet_list, Mapping) else None
    if total == 0 and (facets is None or facets == []):
        return
    if not isinstance(facets, Sequence) or isinstance(facets, (str, bytes)):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric careers API is missing its country facet"
        )
    swiss_count = next(
        (
            required_non_negative_integer(item.get("count"), "country count")
            for item in facets
            if isinstance(item, Mapping)
            and optional_text(item.get("term")) == SCHNEIDER_ELECTRIC_COUNTRY
        ),
        None,
    )
    if swiss_count != total:
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric country facet does not match the declared total"
        )


def collect_swiss_locations(data: Mapping[str, Any]) -> list[str]:
    locations: list[Mapping[str, Any]] = [data]
    additional = data.get("additional_locations")
    if additional is not None:
        if not isinstance(additional, Sequence) or isinstance(additional, (str, bytes)):
            raise SchneiderElectricSwitzerlandParseError(
                "Schneider Electric vacancy has malformed additional locations"
            )
        if not all(isinstance(item, Mapping) for item in additional):
            raise SchneiderElectricSwitzerlandParseError(
                "Schneider Electric vacancy has malformed additional locations"
            )
        locations.extend(additional)  # type: ignore[arg-type]

    swiss_locations: list[str] = []
    for location in locations:
        country = optional_text(location.get("country"))
        country_code = optional_text(location.get("country_code"))
        if country != SCHNEIDER_ELECTRIC_COUNTRY or country_code != SCHNEIDER_ELECTRIC_COUNTRY_CODE:
            continue
        formatted = format_location(location)
        if formatted:
            swiss_locations.append(formatted)
    return list(dict.fromkeys(swiss_locations))


def format_location(location: Mapping[str, Any]) -> str | None:
    country = optional_text(location.get("country"))
    city = optional_text(location.get("city"))
    state = optional_text(location.get("state"))
    if city or state:
        return ", ".join(dict.fromkeys(value for value in (city, state, country) if value))
    location_name = optional_text(location.get("location_name"))
    if location_name and location_name.casefold() == (country or "").casefold():
        return country
    return country


def validate_public_url(url: str | None, *, expected_job_id: str) -> None:
    parts = urlsplit(url or "")
    match = JOB_PATH_PATTERN.match(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.lower() != "careers.se.com"
        or not match
        or match.group(1) != expected_job_id
    ):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric vacancy has an invalid public URL"
        )


def validate_apply_url(url: str | None, *, expected_job_id: str) -> None:
    parts = urlsplit(url or "")
    match = APPLY_PATH_PATTERN.match(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.lower() not in ALLOWED_APPLY_HOSTS
        or not match
        or match.group(1) != expected_job_id
    ):
        raise SchneiderElectricSwitzerlandParseError(
            "Schneider Electric vacancy has an invalid iCIMS application URL"
        )


def extract_posted_at(
    data: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any],
) -> str | None:
    icims = metadata.get("icims")
    icims = icims if isinstance(icims, Mapping) else {}
    posted_site = icims.get("primary_posted_site_object")
    posted_site = posted_site if isinstance(posted_site, Mapping) else {}
    return normalize_date(posted_site.get("datePosted") or data.get("posted_date"))


def normalize_named_values(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return list(
        dict.fromkeys(
            text
            for item in value
            if isinstance(item, Mapping) and (text := optional_text(item.get("name")))
        )
    )


def normalize_string_values(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return list(dict.fromkeys(text for item in value if (text := optional_text(item))))


def normalize_employment_type(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    normalized = text.replace("-", "_").replace(" ", "_").upper()
    labels = {
        "FULL_TIME": "Full Time",
        "PART_TIME": "Part Time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
    }
    return labels.get(normalized, text.replace("_", " ").title())


def extract_minimum_salary(description: str | None) -> int | None:
    if not description:
        return None
    match = re.search(
        r"(?:Jahreszielgehalt|annual target salary).{0,80}?"
        r"(?:min(?:imum)?\.?\s*)?CHF\s*([\d'’., ]+)",
        description,
        re.IGNORECASE,
    )
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else None


def deduplicate_schneider_electric_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or extract_job_id(job.apply_url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    for pattern in (JOB_PATH_PATTERN, APPLY_PATH_PATTERN):
        if match := pattern.match(path):
            return match.group(1)
    return None


def required_non_negative_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise SchneiderElectricSwitzerlandParseError(
            f"Schneider Electric careers API has invalid {field_name}"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SchneiderElectricSwitzerlandParseError(
            f"Schneider Electric careers API has invalid {field_name}"
        ) from exc
    if parsed < 0:
        raise SchneiderElectricSwitzerlandParseError(
            f"Schneider Electric careers API has invalid {field_name}"
        )
    return parsed


def required_positive_integer(value: Any, field_name: str) -> int:
    parsed = required_non_negative_integer(value, field_name)
    if parsed < 1:
        raise SchneiderElectricSwitzerlandParseError(
            f"Schneider Electric careers API has invalid {field_name}"
        )
    return parsed


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    iso_candidate = text.replace("+0000", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date().isoformat()
    except ValueError:
        pass
    for date_format in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = (
        str(value)
        .replace("\u200b", "")
        .replace("\u202f", " ")
        .replace("\xa0", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
