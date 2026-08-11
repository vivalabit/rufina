from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

LUFTHANSA_GROUP_SWITZERLAND_JOBS_URL = (
    "https://apply.lufthansagroup.careers/index.php?ac=search_result"
    "&search_criterion_division%5B%5D=5926"
    "&search_criterion_division%5B%5D=9114"
    "&search_criterion_division%5B%5D=5988"
    "&search_criterion_division%5B%5D=6006"
    "&search_criterion_channel%5B%5D=12"
)
LUFTHANSA_GROUP_JOBS_API_URL = "https://api-apply.lufthansagroup.careers/search/"
LUFTHANSA_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DIVISION_IDS = ("5926", "9114", "5988", "6006")
EXPECTED_COMPANIES = {
    "Edelweiss Air AG",
    "Lufthansa Aviation Training Switzerland AG",
    "Swiss AviationSoftware Ltd.",
    "Swiss International Air Lines AG",
}
MATCHED_OBJECT_DESCRIPTOR = (
    "ID",
    "PositionID",
    "PositionTitle",
    "PositionURI",
    "PositionShortURI",
    "PositionLocation.CountryName",
    "PositionLocation.CountryCode",
    "PositionLocation.CityName",
    "PositionLocation.PostalCode",
    "JobCategory.Name",
    "PublicationStartDate",
    "PublicationEndDate",
    "ParentOrganizationName",
    "OrganizationShortName",
    "CareerLevel.Name",
    "PositionSchedule.Name",
    "PositionOfferingType.Name",
    "PositionStartDate",
    "PublicationCode",
)
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3}(?:\s*[–-]\s*\d{1,3})?)\s*%")


class LufthansaGroupSwitzerlandParseError(DirectCompanyRequestError):
    pass


class LufthansaGroupSwitzerlandJobsParser:
    """Collect the complete Swiss catalog for four Lufthansa Group companies."""

    parser_id = "lufthansa_group_switzerland"

    def __init__(
        self,
        *,
        base_url: str = LUFTHANSA_GROUP_SWITZERLAND_JOBS_URL,
        api_url: str = LUFTHANSA_GROUP_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        page_size: int = 100,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.page_size = min(100, max(1, page_size))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**LUFTHANSA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                all_records, pages_fetched, total = self.collect_listing_records(client)
                records = [record for record in all_records if record["is_swiss"]]
                self.enrich_records(client, records)
        except LufthansaGroupSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Lufthansa Group Switzerland vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Lufthansa Group Switzerland vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_lufthansa_group_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Lufthansa Group Switzerland vacancies from "
                f"{total} catalog records across {pages_fetched} API {request_label}"
            ),
        )

    def build_search_payload(self, *, page: int) -> dict[str, Any]:
        return {
            "LanguageCode": "EN",
            "SearchParameters": {
                "FirstItem": ((page - 1) * self.page_size) + 1,
                "CountItem": self.page_size,
                "Sort": [
                    {
                        "Criterion": "PublicationStartDate",
                        "Direction": "DESC",
                    }
                ],
                "MatchedObjectDescriptor": list(MATCHED_OBJECT_DESCRIPTOR),
            },
            "SearchCriteria": [
                {
                    "CriterionName": "ParentOrganization",
                    "CriterionValue": list(DIVISION_IDS),
                },
                {
                    "CriterionName": "PublicationChannel.Code",
                    "CriterionValue": ["12"],
                },
            ],
        }

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        page: int,
    ) -> tuple[list[dict[str, Any]], int]:
        payload = self.build_search_payload(page=page)
        response = client.get(
            self.api_url,
            params={"data": json.dumps(payload, separators=(",", ":"))},
        )
        response.raise_for_status()
        return parse_api_page(
            response.json(),
            page=page,
            page_size=self.page_size,
            expected_base_url=self.base_url,
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, total = self.fetch_listing_page(client, page=1)
            pages_fetched += 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise LufthansaGroupSwitzerlandParseError(
                    "Lufthansa Group catalog changed its result count during pagination"
                )

            required_pages = max(1, ceil(total / self.page_size))
            if required_pages > self.max_pages:
                raise LufthansaGroupSwitzerlandParseError(
                    f"Lufthansa Group exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            page_results = [first_records]
            for page in range(2, required_pages + 1):
                page_records, page_total = self.fetch_listing_page(client, page=page)
                pages_fetched += 1
                if page_total != expected_total:
                    raise LufthansaGroupSwitzerlandParseError(
                        "Lufthansa Group catalog changed its result count during pagination"
                    )
                page_results.append(page_records)

            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise LufthansaGroupSwitzerlandParseError(
                    "Lufthansa Group catalog changed while pages were collected"
                )

        raise LufthansaGroupSwitzerlandParseError(
            f"Lufthansa Group returned {len(records_by_id)} unique vacancies but "
            f"declared {expected_total or 0}"
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
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_record=record,
                )
            except (
                httpx.HTTPError,
                LufthansaGroupSwitzerlandParseError,
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

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=(optional_text(detail.get("company")) or optional_text(record.get("company"))),
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=optional_text(record.get("url")),
            apply_url=(
                optional_text(detail.get("apply_url")) or fallback_apply_url(record, self.base_url)
            ),
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
            ),
            employment_type=format_employment_type(record),
            seniority=join_values(record.get("career_levels")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_api_page(
    payload: Any,
    *,
    page: int,
    page_size: int,
    expected_base_url: str,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or payload.get("LanguageCode") != "EN":
        raise LufthansaGroupSwitzerlandParseError("Lufthansa Group API payload is malformed")
    result = payload.get("SearchResult")
    if not isinstance(result, dict):
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group API payload is missing its search result"
        )
    total = strict_non_negative_int(result.get("SearchResultCountAll"))
    page_count = strict_non_negative_int(result.get("SearchResultCount"))
    items = result.get("SearchResultItems")
    if total is None or page_count is None or not isinstance(items, list):
        raise LufthansaGroupSwitzerlandParseError("Lufthansa Group API search result is malformed")
    if page_count != len(items) or len(items) > page_size:
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group API returned an inconsistent page size"
        )
    expected_count = min(page_size, max(0, total - ((page - 1) * page_size)))
    if len(items) != expected_count:
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group API returned an incomplete catalog page"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        record = parse_api_item(item, expected_base_url=expected_base_url)
        if record["id"] in seen_ids:
            raise LufthansaGroupSwitzerlandParseError(
                "Lufthansa Group API page contains duplicate vacancy IDs"
            )
        seen_ids.add(record["id"])
        records.append(record)
    return records, total


def parse_api_item(item: Any, *, expected_base_url: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group API contains a malformed vacancy"
        )
    descriptor = item.get("MatchedObjectDescriptor")
    if not isinstance(descriptor, dict):
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group API contains a malformed vacancy descriptor"
        )
    job_id = optional_text(descriptor.get("ID"))
    matched_id = optional_text(item.get("MatchedObjectId"))
    position_id = optional_text(descriptor.get("PositionID"))
    title = optional_text(descriptor.get("PositionTitle"))
    company = optional_text(descriptor.get("ParentOrganizationName"))
    url = canonical_job_url(descriptor.get("PositionURI"), expected_base_url)
    posted_at = normalize_date(descriptor.get("PublicationStartDate"))
    valid_through = normalize_date(descriptor.get("PublicationEndDate"))
    location, is_swiss, raw_locations = normalize_api_locations(descriptor.get("PositionLocation"))
    if (
        not job_id
        or not job_id.isdigit()
        or matched_id != job_id
        or not position_id
        or not title
        or company not in EXPECTED_COMPANIES
        or not url
        or not posted_at
        or not valid_through
        or not raw_locations
    ):
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group API contains an incomplete or unexpected vacancy"
        )
    return {
        "id": job_id,
        "position_id": position_id,
        "title": title,
        "company": company,
        "location": location,
        "locations": raw_locations,
        "is_swiss": is_swiss,
        "url": url,
        "posted_at": posted_at,
        "valid_through": valid_through,
        "categories": extract_names(descriptor.get("JobCategory")),
        "career_levels": extract_names(descriptor.get("CareerLevel")),
        "offering_types": extract_names(descriptor.get("PositionOfferingType")),
        "schedules": extract_names(descriptor.get("PositionSchedule")),
        "publication_code": optional_text(descriptor.get("PublicationCode")),
    }


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    if canonical_job_url(page_url, expected_url) != canonical_job_url(expected_url, expected_url):
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group detail page returned a different vacancy"
        )
    page = Selector(page_html)
    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    if canonical_job_url(canonical, expected_url) != canonical_job_url(expected_url, expected_url):
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group detail page has a mismatched canonical URL"
        )

    schemas = [
        candidate
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        for candidate in parse_json_objects(raw)
        if candidate.get("@type") == "JobPosting"
    ]
    if len(schemas) != 1:
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group detail page is missing its JobPosting data"
        )
    schema = schemas[0]
    job_id = optional_text(expected_record.get("id"))
    position_id = optional_text(expected_record.get("position_id"))
    title = optional_text(schema.get("title"))
    company = optional_text(nested_value(schema, "hiringOrganization", "name"))
    identifier = optional_text(nested_value(schema, "identifier", "value"))
    posted_at = normalize_date(schema.get("datePosted"))
    valid_through = normalize_date(schema.get("validThrough"))
    description = html_to_text(schema.get("description"))
    location = normalize_schema_locations(schema.get("jobLocation"))
    apply_urls = {
        normalized
        for value in page.css('#jobad-container a[class*="apply"]::attr(href)').getall()
        if (
            normalized := normalize_apply_url(
                str(value),
                expected_url=expected_url,
                expected_job_id=job_id,
                expected_company=company,
            )
        )
    }
    if (
        not job_id
        or not position_id
        or identifier != position_id
        or not titles_match(title, expected_record.get("title"))
        or company != expected_record.get("company")
        or company not in EXPECTED_COMPANIES
        or posted_at != expected_record.get("posted_at")
        or not valid_through
        or not description
        or comparable_text(location) != comparable_text(expected_record.get("location"))
        or len(apply_urls) != 1
    ):
        raise LufthansaGroupSwitzerlandParseError(
            "Lufthansa Group detail page contains an incomplete or mismatched vacancy"
        )
    return {
        "id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "apply_url": apply_urls.pop(),
        "posted_at": posted_at,
        "valid_through": valid_through,
        "description": description,
        "schema": schema,
    }


def normalize_api_locations(value: Any) -> tuple[str | None, bool, list[dict[str, Any]]]:
    if not isinstance(value, list) or not value:
        return None, False, []
    swiss_locations: list[str] = []
    raw_locations: list[dict[str, Any]] = []
    for location in value:
        if not isinstance(location, dict):
            return None, False, []
        country_code = optional_text(location.get("CountryCode"))
        country_name = optional_text(location.get("CountryName"))
        city = optional_text(location.get("CityName"))
        postal_code = optional_text(location.get("PostalCode"))
        if not country_code or not country_name or not city:
            return None, False, []
        raw_locations.append(dict(location))
        if country_code == "CH" and country_name == "Switzerland":
            label = " ".join(value for value in (postal_code, city) if value)
            swiss_locations.append(f"{label}, Switzerland")
    unique = list(dict.fromkeys(swiss_locations))
    return ("; ".join(unique) if unique else None), bool(unique), raw_locations


def normalize_schema_locations(value: Any) -> str | None:
    locations = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            return None
        address = location.get("address")
        if not isinstance(address, dict):
            return None
        country = optional_text(address.get("addressCountry"))
        city = optional_text(address.get("addressLocality"))
        postal_code = optional_text(address.get("postalCode"))
        if country != "CH" or not city:
            continue
        label = " ".join(value for value in (postal_code, city) if value)
        normalized.append(f"{label}, Switzerland")
    unique = list(dict.fromkeys(normalized))
    return "; ".join(unique) if unique else None


def canonical_job_url(value: Any, expected_base_url: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(expected_base_url)
    query = parse_qs(parts.query)
    job_ids = query.get("id")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected.netloc.casefold()
        or ("/" + parts.path.lstrip("/")) != "/index.php"
        or query.get("ac") != ["jobad"]
        or not job_ids
        or len(job_ids) != 1
        or not job_ids[0].isdigit()
    ):
        return None
    return urlunsplit(
        (
            "https",
            parts.netloc.casefold(),
            "/index.php",
            urlencode({"ac": "jobad", "id": job_ids[0]}),
            "",
        )
    )


def normalize_apply_url(
    value: str,
    *,
    expected_url: str,
    expected_job_id: str | None,
    expected_company: str | None,
) -> str | None:
    parts = urlsplit(value)
    expected = urlsplit(expected_url)
    query = parse_qs(parts.query)
    if not expected_job_id or parts.scheme != "https":
        return None
    if (
        parts.netloc.casefold() == expected.netloc.casefold()
        and ("/" + parts.path.lstrip("/")) == "/index.php"
        and query.get("ac") == ["application"]
        and query.get("jobad_id") == [expected_job_id]
    ):
        return build_apply_url(expected_url, expected_job_id)
    if (
        expected_company == "Swiss AviationSoftware Ltd."
        and parts.netloc.casefold() == "swissas.teamtailor.com"
        and re.fullmatch(r"/jobs/\d+(?:-[a-z0-9-]+)?/?", parts.path)
        and not parts.query
    ):
        return urlunsplit(("https", "swissas.teamtailor.com", parts.path, "", ""))
    return None


def fallback_apply_url(record: dict[str, Any], base_url: str) -> str | None:
    if record.get("company") == "Swiss AviationSoftware Ltd.":
        return optional_text(record.get("url"))
    return build_apply_url(base_url, optional_text(record.get("id")))


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id or not job_id.isdigit():
        return None
    parts = urlsplit(base_url)
    return urlunsplit(
        (
            "https",
            parts.netloc.casefold(),
            "/index.php",
            urlencode({"ac": "application", "jobad_id": job_id}),
            "",
        )
    )


def parse_json_objects(value: Any) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return
    yield from walk_json(payload)


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def extract_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names = [
        name
        for item in value
        if isinstance(item, dict)
        if (name := optional_text(item.get("Name")))
    ]
    return list(dict.fromkeys(names))


def format_employment_type(record: dict[str, Any]) -> str | None:
    values = [
        *extract_string_list(record.get("offering_types")),
        *extract_string_list(record.get("schedules")),
    ]
    title = optional_text(record.get("title"))
    workload_match = WORKLOAD_PATTERN.search(title or "")
    if workload_match:
        workload = re.sub(r"\s*[–-]\s*", "-", workload_match.group(1)) + "%"
        values.append(workload)
    unique = list(dict.fromkeys(values))
    return " · ".join(unique) if unique else None


def extract_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := optional_text(item))]


def join_values(value: Any) -> str | None:
    values = extract_string_list(value)
    return ", ".join(dict.fromkeys(values)) if values else None


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def strict_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"(?is)<(script|style|picture|figure)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def comparable_text(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+", "", optional_text(value).casefold() if optional_text(value) else ""
    )


def titles_match(detail_title: Any, listing_title: Any) -> bool:
    detail = optional_text(detail_title)
    listing = optional_text(listing_title)
    if not detail or not listing:
        return False
    if comparable_text(detail) == comparable_text(listing):
        return True
    return bool(
        re.fullmatch(
            rf"{re.escape(listing)}\s+[–—-]\s+.+",
            detail,
            re.IGNORECASE,
        )
    )


def deduplicate_lufthansa_group_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line) or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or None
