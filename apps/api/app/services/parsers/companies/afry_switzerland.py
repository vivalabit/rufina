from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AFRY_JOBS_BASE_URL = "https://afry.com/de-ch/karriere/verfugbare-stellen"
AFRY_JOBS_CATALOG_URL = "https://afry.com/de-ch/api/afp-hr-smartrecruiteres-job-list"
AFRY_JOBS_DETAIL_API_URL = "https://api.smartrecruiters.com/v1/companies/AFRY/postings"
AFRY_COMPANY_IDENTIFIER = "AFRY"
SWISS_COUNTRY_ID = "ch"
DETAIL_PATH_PATTERN = re.compile(
    r"^/en/career/available-jobs/(REF[0-9A-Z]+)-[a-z0-9-]+$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")
AFRY_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class AfrySwitzerlandParseError(DirectCompanyRequestError):
    pass


class AfrySwitzerlandJobsParser:
    """Collect AFRY's complete public catalog from SmartRecruiters."""

    parser_id = "afry_switzerland"

    def __init__(
        self,
        *,
        base_url: str = AFRY_JOBS_BASE_URL,
        catalog_url: str = AFRY_JOBS_CATALOG_URL,
        detail_api_url: str = AFRY_JOBS_DETAIL_API_URL,
        timeout_seconds: float = 30.0,
        max_catalog_records: int = 2_000,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.detail_api_url = detail_api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_catalog_records = max(1, max_catalog_records)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**AFRY_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.catalog_url)
                response.raise_for_status()
                records, total = parse_catalog_payload(
                    response.json(),
                    page_url=self.base_url,
                    detail_api_url=self.detail_api_url,
                    max_records=self.max_catalog_records,
                )
                self.enrich_records(client, records)
        except AfrySwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("AFRY vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("AFRY vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_afry_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} AFRY Switzerland vacancies from "
                f"{total} global catalog records"
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
            try:
                response = client.get(record["ref"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_payload(
                    response.json(),
                    expected_job_id=record["id"],
                    expected_title=record["name"],
                    expected_reference=record["reference"],
                    expected_cities=record["city_names"],
                    listed_locations=record.get("Cities"),
                )
            except (httpx.HTTPError, AfrySwitzerlandParseError, TypeError, ValueError) as exc:
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
        source_record = detail or record
        job_id = optional_text(record.get("id"))
        apply_url = valid_posting_url(
            detail.get("applyUrl"),
            job_id=job_id,
            require_apply_query=True,
        )
        public_url = optional_text(record.get("public_url"))
        salary_min, salary_max, salary_currency, salary_unit = extract_compensation(
            detail.get("compensation")
        )

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(source_record.get("name")),
            company="AFRY",
            location=extract_location(
                detail if valid_swiss_location(detail.get("location")) else record
            ),
            url=public_url,
            apply_url=apply_url or public_url,
            posted_at=optional_text(source_record.get("releasedDate")),
            employment_type=extract_employment_type(source_record, title=record.get("name")),
            seniority=extract_seniority(source_record),
            description=extract_description(detail),
            salary=format_salary(
                salary_min,
                salary_max,
                salary_currency,
                salary_unit,
            ),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_unit=salary_unit,
            raw=dict(record),
        )


def parse_catalog_payload(
    payload: Any,
    *,
    page_url: str,
    detail_api_url: str,
    max_records: int,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise AfrySwitzerlandParseError("AFRY catalog response must be an object")
    adverts = payload.get("Adverts")
    countries = payload.get("Countries")
    if payload.get("CacheCold") is not False:
        raise AfrySwitzerlandParseError("AFRY catalog cache is not ready")
    if optional_text(payload.get("DefaultCountry")) != SWISS_COUNTRY_ID:
        raise AfrySwitzerlandParseError("AFRY catalog is missing its Swiss default filter")
    if not isinstance(adverts, list) or not isinstance(countries, list):
        raise AfrySwitzerlandParseError("AFRY catalog response has invalid content")
    if len(adverts) > max_records:
        raise AfrySwitzerlandParseError(
            f"AFRY returned {len(adverts)} records, above the configured limit of {max_records}"
        )

    country_ids: set[str] = set()
    for country in countries:
        country_id = optional_text(country.get("Id")) if isinstance(country, dict) else None
        if not country_id or not optional_text(country.get("Name")) or country_id in country_ids:
            raise AfrySwitzerlandParseError("AFRY catalog contains invalid country facets")
        country_ids.add(country_id)
    if SWISS_COUNTRY_ID not in country_ids:
        raise AfrySwitzerlandParseError("AFRY catalog is missing the Switzerland facet")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in adverts:
        if not isinstance(item, dict):
            raise AfrySwitzerlandParseError("AFRY catalog contains an invalid vacancy")
        job_id = extract_job_id(item.get("Id"))
        item_countries = item.get("Countries")
        ids = country_ids_from_listing(item_countries)
        if not job_id or not ids:
            raise AfrySwitzerlandParseError("AFRY catalog contains an incomplete vacancy")
        if job_id in seen_ids:
            raise AfrySwitzerlandParseError("AFRY catalog contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        if SWISS_COUNTRY_ID in ids:
            records.append(
                validate_listing_record(
                    item,
                    page_url=page_url,
                    detail_api_url=detail_api_url,
                )
            )

    for record in records:
        record["total_available"] = len(records)
        record["global_total_available"] = len(adverts)
    return records, len(adverts)


def validate_listing_record(
    item: Any,
    *,
    page_url: str,
    detail_api_url: str,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise AfrySwitzerlandParseError("AFRY catalog contains an invalid vacancy")
    job_id = extract_job_id(item.get("Id"))
    title = optional_text(item.get("Title"))
    cities = item.get("Cities")
    countries = item.get("Countries")
    detail_path = optional_text(item.get("DetailUrl"))
    detail_url = urljoin(page_url, detail_path) if detail_path else None
    reference = extract_reference(detail_url)
    released_date = optional_text(item.get("LastApplyDate"))
    country_ids = country_ids_from_listing(countries)
    if (
        not isinstance(cities, list)
        or not listing_city_names(cities)
        or any(
            not isinstance(city, dict) or city.get("CountryId") not in country_ids
            for city in cities
        )
    ):
        raise AfrySwitzerlandParseError("AFRY catalog contains an incomplete or non-Swiss vacancy")
    cities = [city for city in cities if city.get("CountryId") == SWISS_COUNTRY_ID]
    city_names = listing_city_names(cities)
    if (
        not job_id
        or not title
        or SWISS_COUNTRY_ID not in country_ids
        or not city_names
        or not valid_listing_cities(cities)
        or not reference
        or not valid_afry_detail_url(detail_url)
        or not valid_date(released_date)
        or not isinstance(item.get("CompetenceAreas"), list)
        or not optional_text(item.get("Language"))
    ):
        raise AfrySwitzerlandParseError("AFRY catalog contains an incomplete or non-Swiss vacancy")
    full_location = f"{', '.join(city_names)}, Switzerland"
    return {
        **item,
        "id": job_id,
        "name": title,
        "releasedDate": released_date,
        "company": {"identifier": AFRY_COMPANY_IDENTIFIER, "name": "AFRY"},
        "location": {
            "city": ", ".join(city_names),
            "country": SWISS_COUNTRY_ID,
            "fullLocation": full_location,
        },
        "reference": reference,
        "city_names": city_names,
        "public_url": detail_url,
        "ref": f"{detail_api_url.rstrip('/')}/{job_id}",
    }


def parse_detail_payload(
    payload: Any,
    *,
    expected_job_id: str,
    expected_title: str,
    expected_reference: str,
    expected_cities: Sequence[str],
    listed_locations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AfrySwitzerlandParseError("AFRY vacancy detail response must be an object")
    job_id = extract_job_id(payload.get("id"))
    sections = nested_dict(payload, "jobAd", "sections")
    location = payload.get("location")
    listed_location = isinstance(location, dict) and any(
        city.get("CountryId") == location.get("country")
        and city.get("Name") == location.get("city")
        for city in (listed_locations or [])
        if isinstance(city, dict)
    )
    if (
        job_id != expected_job_id
        or payload.get("active") is not True
        or optional_text(payload.get("visibility")) != "PUBLIC"
        or optional_text(payload.get("name")) != optional_text(expected_title)
        or optional_text(payload.get("refNumber")) != optional_text(expected_reference)
        or not valid_company(payload.get("company"))
        or not (valid_swiss_location(location) or listed_location)
        or not (detail_city_matches(location, expected_cities) or listed_location)
        or not valid_posting_url(payload.get("postingUrl"), job_id=job_id)
        or not valid_posting_url(
            payload.get("applyUrl"),
            job_id=job_id,
            require_apply_query=True,
        )
        or not optional_text(payload.get("releasedDate"))
        or not isinstance(sections, dict)
        or not extract_description(payload)
    ):
        raise AfrySwitzerlandParseError(
            "AFRY vacancy detail response is incomplete or inconsistent"
        )
    return dict(payload)


def valid_company(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and optional_text(value.get("identifier")) == AFRY_COMPANY_IDENTIFIER
        and optional_text(value.get("name")) == "AFRY"
    )


def valid_swiss_location(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    country = optional_text(value.get("country"))
    return (
        country is not None
        and country.casefold() == "ch"
        and bool(optional_text(value.get("city")) or optional_text(value.get("fullLocation")))
    )


def country_ids_from_listing(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    ids: set[str] = set()
    for country in value:
        country_id = optional_text(country.get("Id")) if isinstance(country, dict) else None
        if not country_id or not optional_text(country.get("Name")) or country_id in ids:
            return set()
        ids.add(country_id)
    return ids


def listing_city_names(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    names: list[str] = []
    seen_ids: set[str] = set()
    for city in value:
        city_id = optional_text(city.get("Id")) if isinstance(city, dict) else None
        name = optional_text(city.get("Name")) if isinstance(city, dict) else None
        if not city_id or not name or city_id in seen_ids:
            return []
        seen_ids.add(city_id)
        names.append(name)
    return names


def valid_listing_cities(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        return False
    return bool(listing_city_names(value)) and all(
        isinstance(city, dict) and optional_text(city.get("CountryId")) == SWISS_COUNTRY_ID
        for city in value
    )


def valid_afry_detail_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "afry.com"
        and DETAIL_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.query
        and not parts.fragment
    )


def extract_reference(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = DETAIL_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return optional_text(match.group(1)).upper() if match else None


def valid_date(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def detail_city_matches(value: Any, expected_cities: Sequence[str]) -> bool:
    if not isinstance(value, dict):
        return False
    city = optional_text(value.get("city"))
    expected = {item.casefold() for item in expected_cities if optional_text(item)}
    return bool(city and city.casefold() in expected)


def valid_posting_url(
    value: Any,
    *,
    job_id: str | None,
    require_apply_query: bool = False,
) -> str | None:
    text = optional_text(value)
    if not text or not job_id:
        return None
    parts = urlsplit(text)
    path_parts = [part for part in parts.path.split("/") if part]
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.smartrecruiters.com"
        or len(path_parts) != 2
        or path_parts[0] != AFRY_COMPANY_IDENTIFIER
        or not (path_parts[1] == job_id or path_parts[1].startswith(f"{job_id}-"))
        or parts.fragment
    ):
        return None
    query = parse_qs(parts.query)
    if require_apply_query and query.get("oga") != ["true"]:
        return None
    return text


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    return text if text and text.isdigit() and int(text) > 0 else None


def extract_location(record: dict[str, Any]) -> str | None:
    location = record.get("location")
    location = location if isinstance(location, dict) else {}
    city = optional_text(location.get("city"))
    full_location = optional_text(location.get("fullLocation"))
    if full_location:
        label = ", ".join(part.strip() for part in full_location.split(",") if part.strip())
    else:
        label = ", ".join(
            part
            for part in (
                city,
                optional_text(location.get("region")),
                optional_text(location.get("country")),
            )
            if part
        )
    work_mode = "Remote" if location.get("remote") is True else None
    if location.get("hybrid") is True:
        work_mode = "Hybrid"
    if label and work_mode:
        return f"{label} ({work_mode})"
    return label or work_mode


def extract_employment_type(record: dict[str, Any], *, title: Any = None) -> str | None:
    employment = record.get("typeOfEmployment")
    employment_label = (
        optional_text(employment.get("label")) if isinstance(employment, dict) else None
    )
    workload = extract_workload(title)
    if employment_label and workload:
        return f"{employment_label} ({workload})"
    return employment_label or workload


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := WORKLOAD_PATTERN.search(text)):
        return None
    return optional_text(re.sub(r"\s*[–-]\s*", "–", match.group(0)))


def extract_seniority(record: dict[str, Any]) -> str | None:
    custom = custom_field_value(record, "Experience Level")
    if custom:
        return custom
    experience = record.get("experienceLevel")
    return optional_text(experience.get("label")) if isinstance(experience, dict) else None


def custom_field_value(record: dict[str, Any], label: str) -> str | None:
    fields = record.get("customField")
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        return None
    for field in fields:
        if isinstance(field, dict) and optional_text(field.get("fieldLabel")) == label:
            return optional_text(field.get("valueLabel"))
    return None


def extract_description(record: dict[str, Any]) -> str | None:
    sections = nested_dict(record, "jobAd", "sections")
    if not isinstance(sections, dict):
        return None
    values: list[str] = []
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        text = html_to_text(optional_text(section.get("text")))
        if not text:
            continue
        title = optional_text(section.get("title"))
        value = f"{title}\n{text}" if title else text
        if value not in values:
            values.append(value)
    return "\n\n".join(values) or None


def extract_compensation(
    value: Any,
) -> tuple[int | None, int | None, str | None, str | None]:
    if not isinstance(value, dict):
        return None, None, None, None
    minimum = optional_int(value.get("min"))
    maximum = optional_int(value.get("max"))
    currency = optional_text(value.get("currency"))
    period = optional_text(value.get("period"))
    return minimum, maximum, currency, period.casefold() if period else None


def format_salary(
    minimum: int | None,
    maximum: int | None,
    currency: str | None,
    unit: str | None,
) -> str | None:
    if minimum is None and maximum is None:
        return None
    if minimum is not None and maximum is not None:
        amount = f"{minimum:,}-{maximum:,}"
    elif minimum is not None:
        amount = f"From {minimum:,}"
    else:
        amount = f"Up to {maximum:,}"
    suffix = " ".join(value for value in (currency, unit) if value)
    return f"{amount} {suffix}".strip()


def deduplicate_afry_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def nested_dict(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
