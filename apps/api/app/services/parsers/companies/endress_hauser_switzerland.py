from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from math import ceil
from typing import Any

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ENDRESS_HAUSER_SWITZERLAND_JOBS_BASE_URL = (
    "https://careers.endress.com/Switzerland/content/search/?locale=en_US&"
    "currentPage=1&pageSize=20&addresses%2Fcountry=Switzerland&"
    "orderBy=datePosted&isDesc=true"
)
ENDRESS_HAUSER_SWITZERLAND_JOBS_API_URL = "https://production.api.recruiting-solutions.org/search"
ENDRESS_HAUSER_SWITZERLAND_CUSTOMER_ID = "eh-prod"
ENDRESS_HAUSER_SWITZERLAND_API_KEY = (
    "pk_eh-prod_jOlkBMdFBQyRACdPXssVQNAFmWJNbaNarAjCPCXrprNXxKZdIGEsSYHHTThgpla"
    "XCvIDHKCibUgkuzwiyqDiBazfQsNnrQRx"
)
ENDRESS_HAUSER_SWITZERLAND_PAGE_SIZE = 20
ENDRESS_HAUSER_SWITZERLAND_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
SEARCH_FIELDS = "jobId,title,description,keyWords,jobType,jobLevel, addresses/country"


class EndressHauserSwitzerlandParseError(DirectCompanyRequestError):
    pass


class EndressHauserSwitzerlandJobsParser:
    """Collect the complete Swiss Endress+Hauser catalog from its public API."""

    parser_id = "endress_hauser_switzerland"

    def __init__(
        self,
        *,
        base_url: str = ENDRESS_HAUSER_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = ENDRESS_HAUSER_SWITZERLAND_JOBS_API_URL,
        customer_id: str = ENDRESS_HAUSER_SWITZERLAND_CUSTOMER_ID,
        api_key: str = ENDRESS_HAUSER_SWITZERLAND_API_KEY,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        page_size: int = ENDRESS_HAUSER_SWITZERLAND_PAGE_SIZE,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.customer_id = customer_id
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.page_size = max(1, page_size)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **ENDRESS_HAUSER_SWITZERLAND_HEADERS,
                    "Referer": self.base_url,
                    "customerId": self.customer_id,
                    "x-api-key": self.api_key,
                    "internal": "false",
                    "privateJobBoard": "false",
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
        except EndressHauserSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Endress+Hauser Switzerland vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Endress+Hauser Switzerland vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_endress_hauser_switzerland_jobs(jobs)
        page_label = "page" if pages_fetched == 1 else "pages"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Endress+Hauser Switzerland vacancies "
                f"across {pages_fetched} API {page_label} ({total} listed)"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records: list[dict[str, Any]] = []
        expected_total: int | None = None
        required_pages = 1

        for page_number in range(1, self.max_pages + 1):
            offset = (page_number - 1) * self.page_size
            response = client.post(
                self.api_url,
                json=listing_payload(offset=offset, page_size=self.page_size),
            )
            response.raise_for_status()
            page_total, page_records = parse_listing_payload(response.json())

            if expected_total is None:
                expected_total = page_total
                required_pages = max(1, ceil(expected_total / self.page_size))
                if required_pages > self.max_pages:
                    raise EndressHauserSwitzerlandParseError(
                        f"Endress+Hauser Switzerland exposes {required_pages} pages, "
                        f"above the configured limit of {self.max_pages}"
                    )
            elif page_total != expected_total:
                raise EndressHauserSwitzerlandParseError(
                    "Endress+Hauser Switzerland changed its vacancy total during pagination"
                )

            expected_page_size = min(
                self.page_size,
                max(0, expected_total - offset),
            )
            if len(page_records) != expected_page_size:
                raise EndressHauserSwitzerlandParseError(
                    f"Endress+Hauser Switzerland page {page_number} returned "
                    f"{len(page_records)} vacancies, expected {expected_page_size}"
                )

            for record in page_records:
                normalized = sanitize_raw_record(record)
                normalized["listing_page"] = page_number
                normalized["total_available"] = expected_total
                records.append(normalized)

            if page_number >= required_pages:
                break

        if expected_total is None:
            raise EndressHauserSwitzerlandParseError(
                "Endress+Hauser Switzerland jobs response was not collected"
            )
        if len(records) != expected_total:
            raise EndressHauserSwitzerlandParseError(
                f"Endress+Hauser Switzerland returned {len(records)} vacancies of {expected_total}"
            )
        return records, required_pages, expected_total

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        public_url = optional_text(record.get("link"))
        salary_min = optional_integer(record.get("salaryMin"))
        salary_max = optional_integer(record.get("salaryMax"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=extract_company(record),
            location=extract_location(record),
            url=public_url,
            apply_url=optional_text(record.get("applyUrl")) or public_url,
            posted_at=optional_text(record.get("datePosted")),
            employment_type=extract_employment_type(record),
            seniority=optional_text(record.get("jobLevel")),
            description=html_to_text(record.get("description")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=(
                optional_text(record.get("currency"))
                if salary_min is not None or salary_max is not None
                else None
            ),
            raw=dict(record),
        )


def listing_payload(*, offset: int, page_size: int) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "count": True,
        "facets": [],
        "filter": (
            f"datePosted lt {now} and "
            "(addresses/any(jt: jt/country eq 'Switzerland')) and "
            "language eq 'en_US'"
        ),
        "orderby": "datePosted desc",
        "search": "*",
        "searchFields": SEARCH_FIELDS,
        "select": "*",
        "skip": offset,
        "top": page_size,
    }


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise EndressHauserSwitzerlandParseError(
            "Endress+Hauser Switzerland jobs response must be an object"
        )
    total = payload.get("@odata.count")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise EndressHauserSwitzerlandParseError(
            "Endress+Hauser Switzerland jobs response has an invalid total"
        )
    value = payload.get("value")
    if not isinstance(value, list):
        raise EndressHauserSwitzerlandParseError(
            "Endress+Hauser Switzerland jobs response has invalid value"
        )

    records: list[dict[str, Any]] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not optional_text(item.get("jobId"))
            or not optional_text(item.get("title"))
            or not optional_text(item.get("link"))
        ):
            raise EndressHauserSwitzerlandParseError(
                "Endress+Hauser Switzerland jobs response contains an incomplete vacancy"
            )
        records.append(item)
    return total, records


def sanitize_raw_record(record: dict[str, Any]) -> dict[str, Any]:
    """Drop repeated embedded recruiter photos while retaining useful metadata."""

    sanitized = dict(record)
    recruiter = sanitized.get("recruiter")
    if isinstance(recruiter, dict) and "photo" in recruiter:
        sanitized["recruiter"] = {key: value for key, value in recruiter.items() if key != "photo"}
        sanitized["raw_fields_removed"] = ["recruiter.photo"]
    return sanitized


def extract_company(record: dict[str, Any]) -> str:
    organisation = record.get("hiringOrganisation")
    if isinstance(organisation, dict):
        name = optional_text(organisation.get("name"))
        if name:
            return name
    return optional_text(record.get("division")) or "Endress+Hauser"


def extract_location(record: dict[str, Any]) -> str | None:
    addresses = record.get("addresses")
    if not isinstance(addresses, Sequence) or isinstance(addresses, (str, bytes)):
        return None

    locations: list[str] = []
    for address in addresses:
        if not isinstance(address, dict):
            continue
        city = optional_text(address.get("city"))
        country = optional_text(address.get("country"))
        location = ", ".join(part for part in (city, country) if part)
        if location and location not in locations:
            locations.append(location)
    return "; ".join(locations) or None


def extract_employment_type(record: dict[str, Any]) -> str | None:
    values = [
        value for field in ("workHours", "jobType") if (value := optional_text(record.get(field)))
    ]
    return " · ".join(dict.fromkeys(values)) or None


def deduplicate_endress_hauser_switzerland_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("jobId")) or job.url or ""
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
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def optional_integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
