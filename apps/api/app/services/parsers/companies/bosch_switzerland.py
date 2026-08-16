from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BOSCH_SWITZERLAND_JOBS_BASE_URL = "https://jobs.bosch.com/en/?pages=1&country=ch#"
BOSCH_COUNTRY_CODE = "ch"
BOSCH_COMPANY_IDENTIFIER = "BoschGroup"
BOSCH_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
JOBS_API_BLOCK_PATTERN = re.compile(
    r"jobsApi\s*:\s*\{(?P<body>.*?)\}\s*,\s*jobAdLinkPrefix",
    re.DOTALL,
)
CONFIG_VALUE_PATTERN = re.compile(
    r'(?P<key>baseUrl|tenant|project|collection|apiKey)\s*:\s*"(?P<value>[^"]+)"'
)
JOB_PREFIX_PATTERN = re.compile(r'jobAdLinkPrefix\s*:\s*"(?P<value>[^"]+)"')
SMARTRECRUITERS_JOB_PATH = re.compile(
    r"^/BoschGroup/(?P<id>\d+)(?:-[^/?#]+)?/?$",
    re.IGNORECASE,
)


class BoschSwitzerlandParseError(DirectCompanyRequestError):
    pass


@dataclass(frozen=True)
class BoschApiConfig:
    base_url: str
    tenant: str
    project: str
    collection: str
    api_key: str
    job_prefix: str

    @property
    def collection_url(self) -> str:
        path = f"/{self.tenant}/{self.project}.{self.collection}.content/"
        return urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    @property
    def listing_url(self) -> str:
        return urljoin(self.collection_url, "_aggrs/get_jobs")


class BoschSwitzerlandJobsParser:
    """Collect the complete Bosch Group Switzerland CaaS catalog."""

    parser_id = "bosch_switzerland"

    def __init__(
        self,
        *,
        base_url: str = BOSCH_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        page_size: int = 100,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        page_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.page_size = min(200, max(1, page_size))
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.page_workers = min(12, max(1, page_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            validate_base_url(self.base_url)
            with httpx.Client(
                headers={**BOSCH_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                api_config = self.initialize_api(client)
                records, total, pages_fetched, catalog_passes = self.collect_catalog(
                    client, api_config=api_config
                )
        except BoschSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Bosch Switzerland vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Bosch Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bosch_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Bosch Switzerland vacancies "
                f"from {total} CaaS country records across {pages_fetched} API "
                f"page requests in {catalog_passes} catalog pass(es)"
            ),
        )

    def initialize_api(self, client: httpx.Client) -> BoschApiConfig:
        response = client.get(self.base_url, headers={"Accept": "text/html"})
        response.raise_for_status()
        return parse_api_config(response.text)

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        api_config: BoschApiConfig,
        page_number: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.get(
            api_config.listing_url,
            params={
                "pagesize": self.page_size,
                "page": page_number,
                "avars": json.dumps(
                    {
                        "country": [BOSCH_COUNTRY_CODE],
                        "sort": {"releasedDate": -1},
                        "page_language": "en",
                    },
                    separators=(",", ":"),
                ),
            },
            headers={"Authorization": f"Bearer {api_config.api_key}"},
        )
        response.raise_for_status()
        total, records = parse_listing_payload(response.json())
        return page_number, total, records

    def fetch_detail_page(
        self,
        client: httpx.Client,
        *,
        api_config: BoschApiConfig,
        page_number: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        response = client.get(
            api_config.collection_url,
            params={
                "rep": "pj",
                "filter": json.dumps(
                    {"location.country": BOSCH_COUNTRY_CODE},
                    separators=(",", ":"),
                ),
                "pagesize": self.page_size,
                "page": page_number,
            },
            headers={"Authorization": f"Bearer {api_config.api_key}"},
        )
        response.raise_for_status()
        records = parse_detail_payload(response.json(), api_config=api_config)
        return page_number, records

    def collect_catalog(
        self,
        client: httpx.Client,
        *,
        api_config: BoschApiConfig,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        pages_fetched = 0
        last_total = 0
        last_unique = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_listing_page(
                client,
                api_config=api_config,
                page_number=1,
            )
            pages_fetched += 1
            total = first_page[1]
            last_total = total
            required_pages = max(1, ceil(total / self.page_size))
            if required_pages > self.max_pages:
                raise BoschSwitzerlandParseError(
                    f"Bosch Switzerland exposes {required_pages} pages, above "
                    f"the configured limit of {self.max_pages}"
                )
            if total == 0:
                if first_page[2]:
                    raise BoschSwitzerlandParseError(
                        "Bosch Switzerland returned vacancies for an empty catalog"
                    )
                return [], 0, pages_fetched, catalog_pass

            remaining_pages = list(range(2, required_pages + 1))
            listing_pages = [first_page]
            if remaining_pages:
                listing_pages.extend(
                    self.fetch_pages(
                        client,
                        api_config=api_config,
                        page_numbers=remaining_pages,
                        detail=False,
                    )
                )
                pages_fetched += len(remaining_pages)

            detail_pages = self.fetch_pages(
                client,
                api_config=api_config,
                page_numbers=list(range(1, required_pages + 1)),
                detail=True,
            )
            pages_fetched += required_pages

            listings_by_id: dict[str, dict[str, Any]] = {}
            details_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            for page_number, page_total, records in sorted(listing_pages):
                expected_count = min(
                    self.page_size,
                    max(0, total - ((page_number - 1) * self.page_size)),
                )
                if page_total != total or len(records) != expected_count:
                    catalog_changed = True
                for record in records:
                    job_id = record["id"]
                    if job_id in listings_by_id:
                        catalog_changed = True
                    normalized = dict(record)
                    normalized["listing_page"] = page_number
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = total
                    listings_by_id.setdefault(job_id, normalized)

            for page_number, records in sorted(detail_pages):
                expected_count = min(
                    self.page_size,
                    max(0, total - ((page_number - 1) * self.page_size)),
                )
                if len(records) != expected_count:
                    catalog_changed = True
                for record in records:
                    job_id = record["id"]
                    if job_id in details_by_id:
                        catalog_changed = True
                    details_by_id.setdefault(job_id, record)

            last_unique = len(listings_by_id)
            if (
                catalog_changed
                or last_unique != total
                or len(details_by_id) != total
                or listings_by_id.keys() != details_by_id.keys()
            ):
                continue

            merged: list[dict[str, Any]] = []
            for job_id, listing in listings_by_id.items():
                detail = details_by_id[job_id]
                validate_listing_detail_pair(listing, detail)
                listing["detail"] = detail
                merged.append(listing)
            return merged, total, pages_fetched, catalog_pass

        raise BoschSwitzerlandParseError(
            f"Bosch Switzerland yielded {last_unique} unique vacancies of "
            f"{last_total} country records"
        )

    def fetch_pages(
        self,
        client: httpx.Client,
        *,
        api_config: BoschApiConfig,
        page_numbers: list[int],
        detail: bool,
    ) -> list[Any]:
        if not page_numbers:
            return []
        method = self.fetch_detail_page if detail else self.fetch_listing_page
        with ThreadPoolExecutor(max_workers=min(self.page_workers, len(page_numbers))) as executor:
            futures = [
                executor.submit(
                    method,
                    client,
                    api_config=api_config,
                    page_number=page_number,
                )
                for page_number in page_numbers
            ]
            return [future.result() for future in as_completed(futures)]

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        if not isinstance(detail, Mapping):
            raise BoschSwitzerlandParseError(
                "Bosch Switzerland vacancy is missing its detail record"
            )
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("name")) or optional_text(record.get("title")),
            company=(
                custom_field_value(detail, "586a9995e4b0daa006ae1078")
                or custom_field_value(detail, "6852d3dc824a8b003b95d20f")
                or optional_text(nested_value(detail, "company", "name"))
                or "Bosch Group"
            ),
            location=extract_location(detail),
            url=optional_text(detail.get("public_url")),
            apply_url=optional_text(detail.get("applyUrl")),
            posted_at=normalize_date(detail.get("releasedDate")),
            employment_type=normalize_employment_type(
                nested_value(detail, "typeOfEmployment", "label")
                or nested_value(record, "working_hours", "valueLabel")
            ),
            seniority=optional_text(nested_value(detail, "experienceLevel", "label")),
            description=extract_description(detail),
            raw=dict(record),
        )


def validate_base_url(base_url: str) -> None:
    parts = urlsplit(base_url)
    params = parse_qs(parts.query)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.bosch.com"
        or parts.path.rstrip("/") != "/en"
        or params.get("country") != [BOSCH_COUNTRY_CODE]
    ):
        raise BoschSwitzerlandParseError("Bosch careers URL lost its Switzerland country scope")


def parse_api_config(page_html: str) -> BoschApiConfig:
    block_match = JOBS_API_BLOCK_PATTERN.search(page_html)
    prefix_match = JOB_PREFIX_PATTERN.search(page_html)
    if not block_match or not prefix_match:
        raise BoschSwitzerlandParseError(
            "Bosch careers page is missing its public jobs API configuration"
        )
    values = {
        match.group("key"): html.unescape(match.group("value"))
        for match in CONFIG_VALUE_PATTERN.finditer(block_match.group("body"))
    }
    required = {"baseUrl", "tenant", "project", "collection", "apiKey"}
    if values.keys() != required:
        raise BoschSwitzerlandParseError(
            "Bosch careers page has an incomplete jobs API configuration"
        )
    config = BoschApiConfig(
        base_url=values["baseUrl"],
        tenant=values["tenant"],
        project=values["project"],
        collection=values["collection"],
        api_key=values["apiKey"],
        job_prefix=html.unescape(prefix_match.group("value")),
    )
    api_parts = urlsplit(config.base_url)
    prefix_parts = urlsplit(config.job_prefix)
    if (
        api_parts.scheme != "https"
        or api_parts.netloc.casefold() != "bosch-i3-caas-api.e-spirit.cloud"
        or api_parts.path.rstrip("/")
        or config.tenant != "bosch-i3-prod"
        or config.project != "bosch-de"
        or config.collection != "jobs"
        or not re.fullmatch(r"[0-9a-f-]{36}", config.api_key, re.IGNORECASE)
        or prefix_parts.scheme != "https"
        or prefix_parts.netloc.casefold() != "jobs.bosch.com"
        or prefix_parts.path != "/en/job/"
    ):
        raise BoschSwitzerlandParseError(
            "Bosch careers page returned an unexpected jobs API configuration"
        )
    return config


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, Mapping):
        raise BoschSwitzerlandParseError("Bosch jobs aggregation returned a non-object response")
    embedded = payload.get("_embedded")
    results = embedded.get("rh:result") if isinstance(embedded, Mapping) else None
    if (
        not isinstance(results, Sequence)
        or isinstance(results, (str, bytes))
        or len(results) != 1
        or not isinstance(results[0], Mapping)
    ):
        raise BoschSwitzerlandParseError("Bosch jobs aggregation is missing its result contract")
    result = results[0]
    meta = result.get("meta")
    data = result.get("data")
    if (
        not isinstance(meta, Sequence)
        or isinstance(meta, (str, bytes))
        or len(meta) != 1
        or not isinstance(meta[0], Mapping)
        or not isinstance(data, Sequence)
        or isinstance(data, (str, bytes))
    ):
        raise BoschSwitzerlandParseError("Bosch jobs aggregation has invalid pagination metadata")
    total = required_non_negative_integer(meta[0].get("count"), "count")
    records = [normalize_listing_record(item) for item in data]
    if len({record["id"] for record in records}) != len(records):
        raise BoschSwitzerlandParseError("Bosch jobs aggregation contains duplicate vacancy IDs")
    return total, records


def normalize_listing_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BoschSwitzerlandParseError("Bosch jobs aggregation contains a malformed vacancy")
    job_id = optional_text(value.get("refNumber"))
    title = optional_text(value.get("name"))
    slug = optional_text(value.get("jobUrl"))
    location = value.get("location")
    country = value.get("country")
    if (
        not job_id
        or optional_text(value.get("_id")) != job_id
        or not title
        or not slug
        or job_id.casefold() not in slug.casefold()
        or not isinstance(location, Mapping)
        or optional_text(location.get("country")).casefold() != BOSCH_COUNTRY_CODE
        or not isinstance(country, Mapping)
        or optional_text(country.get("valueId")).casefold() != BOSCH_COUNTRY_CODE
    ):
        raise BoschSwitzerlandParseError("Bosch jobs aggregation contains an invalid Swiss vacancy")
    return {
        "id": job_id,
        "title": title,
        "slug": slug,
        "location": dict(location),
        "releasedDate": optional_text(value.get("releasedDate")),
        "function": mapping_copy(value.get("function")),
        "positionType": mapping_copy(value.get("positionType")),
        "working_hours": mapping_copy(value.get("working_hours")),
        "type_of_contract": mapping_copy(value.get("type_of_contract")),
        "legal_entity": mapping_copy(value.get("legal_entity")),
        "work_mode": optional_text(value.get("work_mode")),
        "language": mapping_copy(value.get("language")),
        "api": dict(value),
    }


def parse_detail_payload(
    payload: Any,
    *,
    api_config: BoschApiConfig,
) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise BoschSwitzerlandParseError(
            "Bosch jobs detail collection returned a non-object response"
        )
    returned = required_non_negative_integer(payload.get("_returned"), "_returned")
    embedded = payload.get("_embedded")
    if not isinstance(embedded, Sequence) or isinstance(embedded, (str, bytes)):
        raise BoschSwitzerlandParseError("Bosch jobs detail collection is missing its records")
    if returned != len(embedded):
        raise BoschSwitzerlandParseError(
            "Bosch jobs detail collection returned inconsistent record metadata"
        )
    records = [normalize_detail_record(item, api_config=api_config) for item in embedded]
    if len({record["id"] for record in records}) != len(records):
        raise BoschSwitzerlandParseError(
            "Bosch jobs detail collection contains duplicate vacancy IDs"
        )
    return records


def normalize_detail_record(
    value: Any,
    *,
    api_config: BoschApiConfig,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BoschSwitzerlandParseError(
            "Bosch jobs detail collection contains a malformed vacancy"
        )
    record = dict(value)
    job_id = optional_text(record.get("refNumber"))
    title = optional_text(record.get("name"))
    slug = optional_text(record.get("jobUrl"))
    company = record.get("company")
    location = record.get("location")
    if (
        not job_id
        or not title
        or not slug
        or job_id.casefold() not in slug.casefold()
        or record.get("active") is not True
        or record.get("defaultJobAd") is not True
        or optional_text(record.get("visibility")) != "PUBLIC"
        or not isinstance(company, Mapping)
        or optional_text(company.get("identifier")) != BOSCH_COMPANY_IDENTIFIER
        or not isinstance(location, Mapping)
        or optional_text(location.get("country")).casefold() != BOSCH_COUNTRY_CODE
        or optional_text(location.get("country_abbr")).casefold() != BOSCH_COUNTRY_CODE
    ):
        raise BoschSwitzerlandParseError(
            "Bosch jobs detail collection contains an invalid Swiss vacancy"
        )
    public_url = urljoin(api_config.job_prefix, slug)
    validate_public_url(public_url, slug=slug)
    validate_smartrecruiters_url(
        record.get("applyUrl"),
        expected_posting_id=record.get("id"),
    )
    validate_smartrecruiters_url(
        record.get("postingUrl"),
        expected_posting_id=record.get("id"),
    )
    record["id"] = job_id
    record["public_url"] = public_url
    return record


def validate_listing_detail_pair(listing: Mapping[str, Any], detail: Mapping[str, Any]) -> None:
    if (
        listing.get("id") != detail.get("id")
        or optional_text(listing.get("title")) != optional_text(detail.get("name"))
        or optional_text(listing.get("slug")) != optional_text(detail.get("jobUrl"))
        or normalize_date(listing.get("releasedDate")) != normalize_date(detail.get("releasedDate"))
    ):
        raise BoschSwitzerlandParseError(
            "Bosch listing and detail records have mismatched vacancy data"
        )


def validate_public_url(value: str, *, slug: str) -> None:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.bosch.com"
        or parts.path != f"/en/job/{slug}"
        or parts.query
        or parts.fragment
    ):
        raise BoschSwitzerlandParseError("Bosch vacancy has an invalid public URL")


def validate_smartrecruiters_url(value: Any, *, expected_posting_id: Any) -> None:
    url = optional_text(value)
    posting_id = optional_text(expected_posting_id)
    parts = urlsplit(url or "")
    match = SMARTRECRUITERS_JOB_PATH.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.smartrecruiters.com"
        or not match
        or not posting_id
        or match.group("id") != posting_id
        or parts.fragment
    ):
        raise BoschSwitzerlandParseError("Bosch vacancy has an invalid SmartRecruiters URL")


def extract_description(detail: Mapping[str, Any]) -> str | None:
    sections = nested_value(detail, "jobAd", "sections")
    if not isinstance(sections, Mapping):
        return None
    blocks: list[str] = []
    for key in (
        "companyDescription",
        "jobDescription",
        "qualifications",
        "additionalInformation",
    ):
        section = sections.get(key)
        if not isinstance(section, Mapping):
            continue
        title = optional_text(section.get("title"))
        text = html_to_text(section.get("text"))
        block = optional_multiline_text("\n\n".join(item for item in (title, text) if item))
        if block:
            blocks.append(block)
    return optional_multiline_text("\n\n".join(blocks))


def extract_location(detail: Mapping[str, Any]) -> str:
    location = detail.get("location")
    if not isinstance(location, Mapping):
        return "Switzerland"
    return (
        optional_text(location.get("fullLocation"))
        or ", ".join(
            value
            for value in (
                optional_text(location.get("city")),
                optional_text(location.get("region")),
                "Switzerland",
            )
            if value
        )
        or "Switzerland"
    )


def custom_field_value(detail: Mapping[str, Any], field_id: str) -> str | None:
    fields = detail.get("customField")
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        return None
    return next(
        (
            optional_text(item.get("valueLabel"))
            for item in fields
            if isinstance(item, Mapping) and item.get("fieldId") == field_id
        ),
        None,
    )


def normalize_employment_type(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    labels = {
        "vollzeit": "Full Time",
        "teilzeit": "Part Time",
        "vollzeit und/oder teilzeit": "Full Time / Part Time",
        "full-time": "Full Time",
        "part-time": "Part Time",
    }
    return labels.get(text.casefold(), text)


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def deduplicate_bosch_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def required_non_negative_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise BoschSwitzerlandParseError(f"Bosch jobs API has invalid {field_name}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BoschSwitzerlandParseError(f"Bosch jobs API has invalid {field_name}") from exc
    if parsed < 0:
        raise BoschSwitzerlandParseError(f"Bosch jobs API has invalid {field_name}")
    return parsed


def mapping_copy(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def html_to_text(value: Any) -> str | None:
    text = str(value or "")
    if not text:
        return None
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


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
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
