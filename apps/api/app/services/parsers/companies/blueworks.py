from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BLUEWORKS_CAREERS_URL = "https://join.com/companies/blue"
BLUEWORKS_API_URL = "https://join.com/api/public/companies/145851/jobs"
BLUEWORKS_COMPANY_ID = 145851
BLUEWORKS_COMPANY_NAME = "blueworks AG"
BLUEWORKS_COMPANY_SLUG = "blue"
JOIN_PAGE_SIZE = 5
JOIN_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
ID_PARAM_PATTERN = re.compile(r"^[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$")


class BlueworksParseError(DirectCompanyRequestError):
    pass


class BlueworksJobsParser:
    """Collect the complete public blueworks catalog from JOIN."""

    parser_id = "blueworks"

    def __init__(
        self,
        *,
        base_url: str = BLUEWORKS_CAREERS_URL,
        api_url: str = BLUEWORKS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**JOIN_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                company_response = client.get(self.base_url)
                company_response.raise_for_status()
                company_id = parse_company_html(
                    company_response.text,
                    page_url=str(company_response.url),
                    expected_url=self.base_url,
                )
                if company_id != extract_api_company_id(self.api_url):
                    raise BlueworksParseError(
                        "blueworks JOIN API does not match the official company page"
                    )
                records = self.fetch_catalog(client, company_id=company_id)
                self.enrich_records(client, records)
        except BlueworksParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("blueworks vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("blueworks vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_blueworks_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} blueworks vacancies from the official JOIN catalog"),
        )

    def fetch_catalog(
        self,
        client: httpx.Client,
        *,
        company_id: int,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        expected_total: int | None = None
        expected_page_count: int | None = None
        page = 1
        while True:
            response = client.get(
                self.api_url,
                params=[
                    ("page", str(page)),
                    ("pageSize", str(JOIN_PAGE_SIZE)),
                    ("withAggregations", "true"),
                    ("aggregateBy", "categoryId"),
                    ("aggregateBy", "place"),
                    ("sort", "+title"),
                ],
                headers={"Accept": "application/json", "Referer": self.base_url},
            )
            response.raise_for_status()
            parsed = parse_catalog_payload(
                response.json(),
                expected_page=page,
                expected_company_id=company_id,
            )
            total = parsed["total"]
            page_count = parsed["page_count"]
            if expected_total is None:
                expected_total = total
                expected_page_count = page_count
                if page_count > self.max_pages:
                    raise BlueworksParseError(
                        "blueworks catalog is above the configured page limit"
                    )
            elif total != expected_total or page_count != expected_page_count:
                raise BlueworksParseError("blueworks catalog changed during pagination")
            records.extend(parsed["items"])
            if page_count == 0 or page >= page_count:
                break
            page += 1

        record_ids = [record["id"] for record in records]
        if len(record_ids) != len(set(record_ids)):
            raise BlueworksParseError("blueworks catalog contains duplicate vacancy IDs")
        if expected_total is None or len(records) != expected_total:
            raise BlueworksParseError(
                "blueworks catalog did not return its advertised vacancy total"
            )
        return records

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
                response = client.get(
                    record["stable_url"],
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_id=record["id"],
                    expected_title=record["title"],
                )
                return record, detail
            except (httpx.HTTPError, BlueworksParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        workers = min(self.detail_workers, len(records))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_company_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> int:
    if not same_url(page_url, expected_url):
        raise BlueworksParseError("blueworks JOIN company page returned unexpected content")
    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    title = selector_text(page, "head > title")
    next_data = extract_next_data(page)
    initial_state = nested_dict(next_data, "props", "pageProps", "initialState")
    company = initial_state.get("company")
    query = next_data.get("query")
    organizations = [
        item for item in extract_json_objects(page) if item.get("@type") == "Organization"
    ]
    organization_valid = any(
        optional_text(item.get("name")) == BLUEWORKS_COMPANY_NAME
        and same_url(item.get("url"), expected_url)
        and same_url(item.get("sameAs"), "https://blue.works")
        for item in organizations
    )
    if (
        canonicals != {expected_url}
        or og_urls != {expected_url}
        or title != "Jobs at blueworks AG | JOIN"
        or next_data.get("page")
        not in {"/companies/[companySlug]", "/companies/[companySlug]/_dynamic"}
        or not isinstance(query, dict)
        or query.get("companySlug") != BLUEWORKS_COMPANY_SLUG
        or not isinstance(company, dict)
        or company.get("id") != BLUEWORKS_COMPANY_ID
        or optional_text(company.get("name")) != BLUEWORKS_COMPANY_NAME
        or company.get("domain") != BLUEWORKS_COMPANY_SLUG
        or company.get("isPublic") is not True
        or not organization_valid
    ):
        raise BlueworksParseError("blueworks JOIN company page has an unexpected identity")
    return BLUEWORKS_COMPANY_ID


def parse_catalog_payload(
    payload: Any,
    *,
    expected_page: int,
    expected_company_id: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BlueworksParseError("blueworks JOIN API returned an invalid payload")
    items = payload.get("items")
    pagination = payload.get("pagination")
    if not isinstance(items, list) or not isinstance(pagination, dict):
        raise BlueworksParseError("blueworks JOIN API returned an invalid payload")
    total = non_negative_int(pagination.get("rowCount"))
    page_count = non_negative_int(pagination.get("pageCount"))
    current_page = positive_int(pagination.get("page"))
    page_size = non_negative_int(pagination.get("pageSize"))
    calculated_page_count = math.ceil(total / JOIN_PAGE_SIZE) if total else 0
    expected_items = min(
        JOIN_PAGE_SIZE,
        max(0, total - ((expected_page - 1) * JOIN_PAGE_SIZE)),
    )
    if (
        total is None
        or page_count is None
        or current_page != expected_page
        or page_size != len(items)
        or page_count != calculated_page_count
        or len(items) != expected_items
    ):
        raise BlueworksParseError("blueworks JOIN API returned inconsistent pagination")
    return {
        "items": [
            parse_catalog_item(
                item,
                expected_company_id=expected_company_id,
                page=expected_page,
            )
            for item in items
        ],
        "total": total,
        "page_count": page_count,
    }


def parse_catalog_item(
    item: Any,
    *,
    expected_company_id: int,
    page: int,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise BlueworksParseError("blueworks JOIN catalog contains an invalid vacancy")
    job_id = positive_int(item.get("id"))
    id_param = optional_text(item.get("idParam"))
    title = optional_text(item.get("title"))
    company_id = positive_int(item.get("companyId"))
    if (
        job_id is None
        or company_id != expected_company_id
        or not id_param
        or not ID_PARAM_PATTERN.fullmatch(id_param)
        or not title
    ):
        raise BlueworksParseError("blueworks JOIN catalog contains an incomplete vacancy")
    country = item.get("country")
    if not isinstance(country, dict) or not optional_text(country.get("iso3166")):
        raise BlueworksParseError("blueworks JOIN catalog contains an incomplete vacancy")
    return {
        **item,
        "id": job_id,
        "idParam": id_param,
        "title": title,
        "page": page,
        "stable_url": f"{BLUEWORKS_CAREERS_URL}/{job_id}",
        "current_url": f"{BLUEWORKS_CAREERS_URL}/{id_param}",
    }


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_id: int,
    expected_title: str,
) -> dict[str, Any]:
    page = Selector(page_html)
    next_data = extract_next_data(page)
    initial_state = nested_dict(next_data, "props", "pageProps", "initialState")
    job = initial_state.get("job")
    if not isinstance(job, dict):
        raise BlueworksParseError("blueworks JOIN detail page contains an incomplete vacancy")
    company = job.get("company")
    id_param = optional_text(job.get("idParam"))
    canonical_url = f"{BLUEWORKS_CAREERS_URL}/{id_param}" if id_param else None
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    schemas = [item for item in extract_json_objects(page) if item.get("@type") == "JobPosting"]
    schema = schemas[0] if len(schemas) == 1 else {}
    hiring_organization = schema.get("hiringOrganization")
    title = optional_text(job.get("title"))
    description = optional_multiline_text(job.get("description"))
    if (
        job.get("id") != expected_id
        or title != expected_title
        or job.get("status") != "ONLINE"
        or not id_param
        or not ID_PARAM_PATTERN.fullmatch(id_param)
        or not canonical_url
        or canonicals != {canonical_url}
        or not same_url(page_url, canonical_url)
        or next_data.get("page")
        not in {
            "/companies/[companySlug]/[id]",
            "/companies/[companySlug]/[id]/_dynamic",
        }
        or not isinstance(company, dict)
        or company.get("id") != BLUEWORKS_COMPANY_ID
        or company.get("domain") != BLUEWORKS_COMPANY_SLUG
        or optional_text(company.get("name")) != BLUEWORKS_COMPANY_NAME
        or not description
        or not isinstance(hiring_organization, dict)
        or optional_text(hiring_organization.get("name")) != BLUEWORKS_COMPANY_NAME
        or not same_url(schema.get("url"), canonical_url)
        or html.unescape(optional_text(schema.get("title")) or "") != title
    ):
        raise BlueworksParseError("blueworks JOIN detail page contains an incomplete vacancy")
    return {
        "title": title,
        "location": format_location(job),
        "apply_url": canonical_url,
        "posted_at": normalize_iso_date(job.get("createdAt")),
        "employment_type": normalize_employment_type(job.get("employmentType")),
        "description": description,
        "category": optional_text((job.get("category") or {}).get("name")),
        "workplace_type": optional_text(job.get("workplaceType")),
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="blueworks",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=BLUEWORKS_COMPANY_NAME,
        location=optional_text(detail.get("location")) or format_location(record),
        url=optional_text(record.get("stable_url")),
        apply_url=(
            optional_text(detail.get("apply_url")) or optional_text(record.get("current_url"))
        ),
        posted_at=(
            optional_text(detail.get("posted_at")) or normalize_iso_date(record.get("createdAt"))
        ),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or normalize_employment_type(record.get("employmentType"))
        ),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def format_location(value: dict[str, Any]) -> str | None:
    city = value.get("city")
    if not isinstance(city, dict):
        office = value.get("office")
        city = office.get("city") if isinstance(office, dict) else None
    city = city if isinstance(city, dict) else {}
    city_name = optional_text(city.get("cityName"))
    country_name = optional_text(city.get("countryName"))
    location = ", ".join(part for part in (city_name, country_name) if part)
    workplace_type = optional_text(value.get("workplaceType"))
    if workplace_type == "REMOTE" and not location:
        return "Remote"
    if location and workplace_type in {"HYBRID", "REMOTE"}:
        return f"{location} ({workplace_type.title()})"
    return location or None


def normalize_employment_type(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    google_type = optional_text(value.get("googleType"))
    normalized = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
        "VOLUNTEER": "Volunteer",
        "PER_DIEM": "Per diem",
        "OTHER": "Other",
    }.get(google_type or "")
    return normalized or optional_text(value.get("name"))


def extract_next_data(page: Selector) -> dict[str, Any]:
    values = page.css("script#__NEXT_DATA__::text").getall()
    if len(values) != 1:
        raise BlueworksParseError("JOIN page is missing its application data")
    try:
        payload = json.loads(str(values[0]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise BlueworksParseError("JOIN page has invalid application data") from exc
    if not isinstance(payload, dict):
        raise BlueworksParseError("JOIN page has invalid application data")
    return payload


def extract_json_objects(page: Selector) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            result.append(payload)
        elif isinstance(payload, list):
            result.extend(item for item in payload if isinstance(item, dict))
    return result


def extract_api_company_id(value: Any) -> int | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = re.fullmatch(r"/api/public/companies/([0-9]+)/jobs", parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "join.com"
        or parts.query
        or parts.fragment
        or not match
    ):
        return None
    return int(match.group(1))


def nested_dict(value: Any, *keys: str) -> dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and actual.query == target.query
        and not actual.fragment
    )


def deduplicate_blueworks_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    nodes = selector.css(css)
    if len(nodes) != 1:
        return None
    return optional_text(" ".join(nodes[0].css("::text").getall()))


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f"{css}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(html.unescape(str(value)).replace("\xa0", " ").split())
    return text or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    lines = [" ".join(line.split()) for line in html.unescape(str(value)).splitlines()]
    compact: list[str] = []
    for line in lines:
        if line:
            compact.append(line)
        elif compact and compact[-1]:
            compact.append("")
    return "\n".join(compact).strip() or None
