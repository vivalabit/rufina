from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

BKW_SWITZERLAND_JOBS_URL = "https://jobs.bkw.com/en/vacancies"
BKW_SWITZERLAND_API_URL = (
    "https://jobs.bkw.com/_api/v1/structureddata?configFromContentElement=82381&language=en-ch"
)
BKW_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
SWITZERLAND_CATEGORY_ID = "116"
SWISS_COUNTRIES = {"ch", "schweiz", "suisse", "svizzera", "switzerland"}
JOB_PATH_PATTERN = re.compile(
    r"^/offene-stellen/[a-z0-9]+(?:-[a-z0-9]+)*/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    r"^/public/v1/redirect/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/ats/?$",
    re.IGNORECASE,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
HREF_PATTERN = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


class BkwSwitzerlandParseError(DirectCompanyRequestError):
    pass


class BkwSwitzerlandJobsParser:
    """Collect BKW Group vacancies whose official country category is Switzerland."""

    parser_id = "bkw_switzerland"

    def __init__(
        self,
        *,
        base_url: str = BKW_SWITZERLAND_JOBS_URL,
        api_url: str = BKW_SWITZERLAND_API_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 2000,
        detail_workers: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(2, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with CareerHttpClient(
                headers={**BKW_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records, catalog_count = parse_catalog_payload(
                    response.json(),
                    page_url=str(response.url),
                    expected_url=self.api_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except BkwSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(f"BKW Switzerland vacancy request failed: {exc}") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("BKW Switzerland vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bkw_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} BKW Switzerland vacancies from "
                f"{catalog_count} global BKW catalog records"
            ),
        )

    def enrich_records(
        self,
        client: CareerHttpClient,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(
                    str(record["url"]),
                    headers={
                        "Accept": (
                            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                        ),
                        "Referer": self.base_url,
                    },
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=str(record["url"]),
                    expected_id=str(record["id"]),
                    expected_title=str(record["title"]),
                )
            except (httpx.HTTPError, BkwSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                if not record.get("parsed_locations"):
                    record["exclude_unverified"] = True
                return record, None

        def enrich_batch(batch: list[dict[str, Any]], *, workers: int) -> None:
            if not batch:
                return
            with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as executor:
                futures = [executor.submit(fetch_detail, record) for record in batch]
                for future in as_completed(futures):
                    record, detail = future.result()
                    if detail is not None:
                        record["detail"] = detail

        # Resolve country-ambiguous records before the public detail host starts
        # rate-limiting the larger best-effort enrichment batch.
        unverified = [record for record in records if not record.get("parsed_locations")]
        verified = [record for record in records if record.get("parsed_locations")]
        enrich_batch(unverified, workers=min(2, self.detail_workers))
        enrich_batch(verified, workers=self.detail_workers)
        records[:] = [record for record in records if not record.get("exclude_unverified")]


def parse_catalog_payload(
    payload: Any,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> tuple[list[dict[str, Any]], int]:
    if not same_url(page_url, expected_url) or not isinstance(payload, dict):
        raise BkwSwitzerlandParseError("BKW catalog returned unexpected content")
    data = payload.get("data")
    meta = payload.get("meta")
    if not isinstance(data, list) or not isinstance(meta, dict):
        raise BkwSwitzerlandParseError("BKW catalog is missing its data contract")
    validate_country_filter(meta)
    if len(data) > max_jobs:
        raise BkwSwitzerlandParseError(
            f"BKW catalog exceeds the configured limit of {max_jobs} vacancies"
        )

    records: list[dict[str, Any]] = []
    seen_record_ids: set[str] = set()
    seen_job_ids: set[str] = set()
    for candidate in data:
        if not has_swiss_category(candidate):
            continue
        record = parse_swiss_record(candidate, listing_page_url=page_url)
        if not has_swiss_location(record):
            continue
        record_id = str(record["record_id"])
        job_id = str(record["id"])
        if record_id in seen_record_ids or job_id in seen_job_ids:
            raise BkwSwitzerlandParseError("BKW catalog contains duplicate vacancy IDs")
        seen_record_ids.add(record_id)
        seen_job_ids.add(job_id)
        records.append(record)
    return records, len(data)


def validate_country_filter(meta: dict[str, Any]) -> None:
    configuration = meta.get("filterConfiguration")
    filters = configuration.get("filters") if isinstance(configuration, dict) else None
    if not isinstance(filters, list):
        raise BkwSwitzerlandParseError("BKW catalog is missing its country filter")
    country_filters = [
        item for item in filters if isinstance(item, dict) and item.get("identifier") == "Land"
    ]
    if len(country_filters) != 1:
        raise BkwSwitzerlandParseError("BKW catalog changed its country filter")
    country_filter = country_filters[0]
    options = country_filter.get("options")
    swiss_options = (
        [option for option in options if isinstance(option, dict)]
        if isinstance(options, list)
        else []
    )
    if (
        country_filter.get("id") != "115"
        or country_filter.get("type") != "MultiSelect"
        or not any(
            option.get("id") == SWITZERLAND_CATEGORY_ID
            and option.get("title") == "Switzerland"
            and option.get("isHeading") is False
            for option in swiss_options
        )
    ):
        raise BkwSwitzerlandParseError("BKW catalog changed its Switzerland category")


def has_swiss_category(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    relations = candidate.get("relations")
    countries = relations.get("Land") if isinstance(relations, dict) else None
    return isinstance(countries, list) and any(
        isinstance(country, dict)
        and country.get("type") == "category"
        and country.get("id") == SWITZERLAND_CATEGORY_ID
        and country.get("title") == "Switzerland"
        for country in countries
    )


def parse_swiss_record(candidate: Any, *, listing_page_url: str) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise BkwSwitzerlandParseError("BKW catalog contains an invalid vacancy")
    record_id = optional_text(candidate.get("id"))
    title = optional_text(candidate.get("title"))
    url = optional_text(candidate.get("url"))
    job_id = extract_job_id(url)
    relations = candidate.get("relations")
    companies = relation_titles(relations, "Unternehmen")
    locations = candidate.get("locations")
    if (
        candidate.get("type") != "jobs"
        or candidate.get("isExternal") is not True
        or not record_id
        or not record_id.isdigit()
        or not title
        or not job_id
        or not companies
        or (locations is not None and not isinstance(locations, list))
    ):
        raise BkwSwitzerlandParseError("BKW catalog contains an incomplete Swiss vacancy")
    parsed_locations: list[dict[str, str | None]] = []
    for location in locations or []:
        if not isinstance(location, dict) or location.get("type") != "location":
            raise BkwSwitzerlandParseError("BKW catalog contains an invalid vacancy location")
        address = location.get("address")
        if not isinstance(address, dict):
            raise BkwSwitzerlandParseError("BKW catalog contains an invalid vacancy address")
        country = optional_text(address.get("country"))
        city = optional_text(address.get("city"))
        if not country:
            raise BkwSwitzerlandParseError("BKW catalog contains a location without a country")
        parsed_locations.append({"city": city, "country": country})

    return {
        **candidate,
        "id": job_id,
        "record_id": record_id,
        "title": title,
        "url": url,
        "companies": companies,
        "parsed_locations": parsed_locations,
        "employment_types": relation_titles(relations, "Anstellungsart"),
        "positions": relation_titles(relations, "Position"),
        "listing_page_url": listing_page_url,
    }


def has_swiss_location(record: dict[str, Any]) -> bool:
    locations = record.get("parsed_locations")
    if not isinstance(locations, list) or not locations:
        return True
    return any(
        isinstance(location, dict)
        and optional_text(location.get("country"))
        and str(location["country"]).casefold() in SWISS_COUNTRIES
        for location in locations
    )


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_id: str,
    expected_title: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_id:
        raise BkwSwitzerlandParseError("BKW vacancy returned unexpected content")
    schemas = list(extract_job_posting_schemas(page_html))
    if len(schemas) != 1:
        raise BkwSwitzerlandParseError("BKW vacancy is missing its JobPosting data")
    schema = schemas[0]
    title = optional_text(html.unescape(str(schema.get("title", ""))))
    normalized_expected_title = optional_text(html.unescape(expected_title))
    description = html_to_text(optional_text(schema.get("description")))
    company = extract_hiring_organization(schema)
    location = extract_swiss_schema_location(schema)
    apply_urls = {
        normalized
        for href in HREF_PATTERN.findall(page_html)
        if (normalized := normalize_apply_url(href, expected_id=expected_id))
    }
    if (
        not title
        or not normalized_expected_title
        or (
            title.casefold() != normalized_expected_title.casefold()
            and not title.casefold().startswith(f"{normalized_expected_title.casefold()} - ")
        )
        or not description
        or not company
        or not location
        or len(apply_urls) != 1
    ):
        raise BkwSwitzerlandParseError("BKW vacancy contains incomplete detail data")
    return {
        "title": normalized_expected_title,
        "company": company,
        "location": location,
        "apply_url": next(iter(apply_urls)),
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "employment_type": normalize_employment_type(schema.get("employmentType")),
        "description": description,
        "schema": schema,
    }


def extract_job_posting_schemas(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        for candidate in walk_json(payload):
            job_type = candidate.get("@type")
            if job_type == "JobPosting" or (
                isinstance(job_type, list) and "JobPosting" in job_type
            ):
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_hiring_organization(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    return optional_text(organization.get("name")) if isinstance(organization, dict) else None


def extract_swiss_schema_location(schema: dict[str, Any]) -> str | None:
    locations = schema.get("jobLocation")
    candidates = (
        locations
        if isinstance(locations, Sequence) and not isinstance(locations, (str, bytes))
        else [locations]
    )
    values: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        address = candidate.get("address")
        if not isinstance(address, dict):
            continue
        country = optional_text(address.get("addressCountry"))
        if not country or country.casefold() not in SWISS_COUNTRIES:
            continue
        locality = optional_text(address.get("addressLocality"))
        values.append(join_unique(locality, country) or country)
    return "; ".join(dict.fromkeys(values)) or None


def relation_titles(relations: Any, identifier: str) -> list[str]:
    values = relations.get(identifier) if isinstance(relations, dict) else None
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(
            title
            for item in values
            if isinstance(item, dict) and item.get("type") == "category"
            if (title := optional_text(item.get("title")))
        )
    )


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    listing_locations = record.get("parsed_locations")
    cities = (
        [
            optional_text(location.get("city"))
            for location in listing_locations
            if isinstance(location, dict)
            and optional_text(location.get("country"))
            and str(location["country"]).casefold() in SWISS_COUNTRIES
        ]
        if isinstance(listing_locations, list)
        else []
    )
    pensum = record.get("pensum")
    workload = None
    if isinstance(pensum, dict):
        minimum = pensum.get("min")
        maximum = pensum.get("max")
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
            workload = f"{minimum:g}-{maximum:g}%"
    companies = record.get("companies")
    employment_types = record.get("employment_types")
    positions = record.get("positions")
    job_id = str(record["id"])
    return ParsedJob(
        source="bkw_switzerland",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=(
            optional_text(detail.get("company"))
            or (optional_text(companies[0]) if isinstance(companies, list) and companies else None)
            or "BKW"
        ),
        location=optional_text(detail.get("location"))
        or "; ".join(dict.fromkeys(city for city in cities if city))
        or "Switzerland",
        url=optional_text(record.get("url")),
        apply_url=optional_text(detail.get("apply_url")) or build_apply_url(job_id),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=join_unique(
            workload,
            optional_text(detail.get("employment_type")),
            *(optional_text(value) for value in employment_types if isinstance(value, str))
            if isinstance(employment_types, list)
            else (),
        ),
        seniority=join_unique(
            *(optional_text(value) for value in positions if isinstance(value, str))
        )
        if isinstance(positions, list)
        else None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def normalize_employment_type(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return join_unique(*(normalize_employment_type(item) for item in value))
    text = optional_text(value)
    if not text:
        return None
    return {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
    }.get(text.upper(), text.replace("_", " ").title())


def normalize_apply_url(value: Any, *, expected_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parsed = urlsplit(html.unescape(text))
    match = APPLY_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "ohws.prospective.ch"
        or parsed.query
        or parsed.fragment
        or not match
        or match.group(1).lower() != expected_id
    ):
        return None
    return f"https://ohws.prospective.ch/public/v1/redirect/{expected_id}/ats/"


def build_apply_url(job_id: str) -> str:
    return f"https://ohws.prospective.ch/public/v1/redirect/{job_id}/ats/"


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parsed = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "job.bkw.com"
        or parsed.query
        or parsed.fragment
        or not match
    ):
        return None
    job_id = match.group(1).lower()
    try:
        UUID(job_id)
    except ValueError:
        return None
    return job_id


def same_url(left: str, right: str) -> bool:
    def normalized(value: str) -> tuple[str, str, str, str]:
        parsed = urlsplit(value)
        return (
            parsed.scheme.casefold(),
            (parsed.hostname or "").casefold(),
            parsed.path.rstrip("/") or "/",
            parsed.query,
        )

    return normalized(left) == normalized(right)


def deduplicate_bkw_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def join_unique(*values: str | None) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    return normalized or None
