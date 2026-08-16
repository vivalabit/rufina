from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

TAKEDA_SWITZERLAND_JOBS_BASE_URL = "https://jobs.takeda.com/search-jobs"
TAKEDA_ORGANIZATION_ID = "1113"
TAKEDA_SWITZERLAND_FACET_ID = 2658434
TAKEDA_SWITZERLAND_COUNTRY = "Switzerland"
TAKEDA_RESULTS_PER_PAGE = 5
TAKEDA_HEADERS = {
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8",
    "Content-Type": "application/json; charset=utf-8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
JOB_ID_PATTERN = re.compile(r"^[1-9]\d*$")


class TakedaSwitzerlandParseError(DirectCompanyRequestError):
    pass


class TakedaSwitzerlandJobsParser:
    """Collect Takeda's complete official country facet for Switzerland."""

    parser_id = "takeda_switzerland"

    def __init__(
        self,
        *,
        base_url: str = TAKEDA_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        page_workers: int = 10,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.page_workers = min(12, max(1, page_workers))
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    @property
    def site_origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def listing_endpoint(self) -> str:
        return f"{self.site_origin}/search-jobs/resultspost"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **TAKEDA_HEADERS,
                    "Origin": self.site_origin,
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, total, pages_fetched, catalog_passes = (
                    self.collect_listing_records(client)
                )
                self.enrich_records(client, records)
        except TakedaSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Takeda Switzerland vacancy request failed"
            ) from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Takeda Switzerland vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_takeda_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Takeda Switzerland vacancies from "
                f"{total} Radancy country records across {pages_fetched} page "
                f"requests in {catalog_passes} catalog pass(es)"
            ),
        )

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        page: int,
        known_total: int = 0,
        known_pages: int = 0,
    ) -> tuple[int, int, int, list[dict[str, Any]]]:
        response = client.post(
            self.listing_endpoint,
            json=listing_payload(
                page=page,
                known_total=known_total,
                known_pages=known_pages,
            ),
        )
        response.raise_for_status()
        total, total_pages, records = parse_listing_response(
            response.json(),
            expected_page=page,
        )
        return page, total, total_pages, records

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        pages_fetched = 0
        last_unique_count = 0
        last_total = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_listing_page(client, page=1)
            pages_fetched += 1
            total = first_page[1]
            total_pages = first_page[2]
            last_total = total
            if total_pages > self.max_pages:
                raise TakedaSwitzerlandParseError(
                    f"Takeda Switzerland exposes {total_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
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
                            client,
                            page=page,
                            known_total=total,
                            known_pages=total_pages,
                        )
                        for page in remaining_pages
                    ]
                    page_results.extend(
                        future.result() for future in as_completed(futures)
                    )
                pages_fetched += len(remaining_pages)

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            for page, page_total, page_count, records in sorted(page_results):
                if page_total != total or page_count != total_pages:
                    catalog_changed = True
                for record in records:
                    job_id = extract_job_id(record)
                    normalized = dict(record)
                    normalized["listing_page"] = page
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = total
                    if job_id in records_by_id:
                        catalog_changed = True
                    records_by_id.setdefault(job_id, normalized)

            last_unique_count = len(records_by_id)
            if not catalog_changed and last_unique_count == total:
                return list(records_by_id.values()), total, pages_fetched, catalog_pass

        raise TakedaSwitzerlandParseError(
            f"Takeda Switzerland yielded {last_unique_count} unique vacancies of "
            f"{last_total} country records"
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
                    expected_job_id=extract_job_id(record),
                )
            except (httpx.HTTPError, TakedaSwitzerlandParseError, ValueError) as exc:
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
        public_url = optional_text(detail.get("url")) or record["url"]
        description_html = optional_text(detail.get("description"))
        raw = dict(record)
        raw["detail"] = detail
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or record["title"],
            company="Takeda Pharmaceutical",
            location=(
                optional_text(detail.get("location"))
                or fallback_swiss_location(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("datePosted")),
            employment_type=(
                optional_text(detail.get("employmentType"))
                or optional_text(record.get("category"))
            ),
            description=html_to_text(description_html) if description_html else None,
            raw=raw,
        )


def listing_payload(
    *,
    page: int,
    known_total: int = 0,
    known_pages: int = 0,
) -> dict[str, Any]:
    return {
        "ActiveFacetID": TAKEDA_SWITZERLAND_FACET_ID,
        "CurrentPage": page,
        "RecordsPerPage": TAKEDA_RESULTS_PER_PAGE,
        "TotalPages": known_pages,
        "TotalResults": known_total,
        "Distance": 50,
        "RadiusUnitType": 0,
        "Keywords": "",
        "Location": "",
        "Latitude": None,
        "Longitude": None,
        "ShowRadius": False,
        "IsPagination": "True" if page > 1 else "False",
        "CustomFacetName": "",
        "FacetTerm": "",
        "FacetType": 0,
        "FacetFilters": [
            {
                "ID": TAKEDA_SWITZERLAND_FACET_ID,
                "FacetType": 2,
                "Count": known_total,
                "Display": TAKEDA_SWITZERLAND_COUNTRY,
                "IsApplied": True,
                "FieldName": "",
            }
        ],
        "SearchResultsModuleName": "Search Results",
        "SearchFiltersModuleName": "Search Filters",
        "SortCriteria": 0,
        "SortDirection": 1,
        "SearchType": 5,
        "KeywordType": "",
        "LocationType": "",
        "LocationPath": "",
        "OrganizationIds": "",
        "RefinedKeywords": [],
        "PostalCode": "",
        "ResultsType": 0,
    }


def parse_listing_response(
    payload: Any,
    *,
    expected_page: int,
) -> tuple[int, int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise TakedaSwitzerlandParseError("Takeda listing response must be an object")
    results_html = payload.get("results")
    filters_html = payload.get("filters")
    if not isinstance(results_html, str) or not results_html.strip():
        raise TakedaSwitzerlandParseError("Takeda listing response is missing results HTML")
    if not isinstance(filters_html, str) or not filters_html.strip():
        raise TakedaSwitzerlandParseError("Takeda listing response is missing filters HTML")

    document = Selector(results_html)
    sections = document.css("section#search-results")
    if len(sections) != 1:
        raise TakedaSwitzerlandParseError("Takeda listing has an invalid results section")
    section = sections[0]
    total = integer_attribute(section, "data-total-results")
    total_jobs = integer_attribute(section, "data-total-job-results")
    total_pages = integer_attribute(section, "data-total-pages")
    current_page = integer_attribute(section, "data-current-page")
    page_size = integer_attribute(section, "data-records-per-page")
    active_facet = integer_attribute(section, "data-active-facet-id")
    organization = optional_text(section.css("::attr(data-organization-ids)").get())
    sort_direction = integer_attribute(section, "data-sort-direction")
    search_type = integer_attribute(section, "data-search-type")
    if (
        total < 0
        or total_jobs != total
        or current_page != expected_page
        or page_size != TAKEDA_RESULTS_PER_PAGE
        or active_facet != TAKEDA_SWITZERLAND_FACET_ID
        or organization is not None
        or sort_direction != 1
        or search_type != 5
    ):
        raise TakedaSwitzerlandParseError("Takeda listing has invalid catalog metadata")
    expected_pages = ceil(total / TAKEDA_RESULTS_PER_PAGE)
    if total_pages != expected_pages:
        raise TakedaSwitzerlandParseError("Takeda listing has invalid pagination metadata")

    validate_switzerland_filter(filters_html, expected_total=total)
    applied_filters = section.css(
        f'.filter-button[data-id="{TAKEDA_SWITZERLAND_FACET_ID}"]'
        '[data-facet-type="2"]'
    )
    if total and len(applied_filters) != 1:
        raise TakedaSwitzerlandParseError(
            "Takeda listing is missing its applied Switzerland filter"
        )

    records: list[dict[str, Any]] = []
    for card in section.css("#search-results-list > ul > li"):
        links = card.css("a[data-job-id]")
        if len(links) != 1:
            raise TakedaSwitzerlandParseError("Takeda listing contains an invalid job card")
        link = links[0]
        job_id = optional_text(link.css("::attr(data-job-id)").get()) or ""
        path = optional_text(link.css("::attr(href)").get())
        title = node_text(link, "h2.title")
        location = node_text(link, "span.location")
        category = labeled_text(link, "span.category", "Category:")
        button_ids = {
            value
            for raw in card.css("button.js-save-job-btn::attr(data-job-id)").getall()
            if (value := optional_text(raw))
        }
        organization_ids = {
            value
            for raw in card.css("button.js-save-job-btn::attr(data-org-id)").getall()
            if (value := optional_text(raw))
        }
        if (
            not JOB_ID_PATTERN.fullmatch(job_id)
            or not path
            or not path.startswith("/job/")
            or not path.endswith(f"/{TAKEDA_ORGANIZATION_ID}/{job_id}")
            or not title
            or not location
            or button_ids != {job_id}
            or organization_ids != {TAKEDA_ORGANIZATION_ID}
        ):
            raise TakedaSwitzerlandParseError(
                "Takeda listing contains an incomplete vacancy"
            )
        records.append(
            {
                "job_id": job_id,
                "title": html.unescape(title),
                "location": html.unescape(location),
                "category": html.unescape(category) if category else None,
                "url": urljoin("https://jobs.takeda.com", path),
            }
        )

    expected_count = min(
        TAKEDA_RESULTS_PER_PAGE,
        max(0, total - ((expected_page - 1) * TAKEDA_RESULTS_PER_PAGE)),
    )
    if len(records) != expected_count:
        raise TakedaSwitzerlandParseError(
            f"Takeda listing page {expected_page} returned {len(records)} of "
            f"{expected_count} expected vacancies"
        )
    has_jobs = payload.get("hasJobs")
    if not isinstance(has_jobs, bool) or has_jobs is not (total > 0):
        raise TakedaSwitzerlandParseError("Takeda listing has invalid hasJobs metadata")
    return total, total_pages, records


def validate_switzerland_filter(filters_html: str, *, expected_total: int) -> None:
    filters = Selector(filters_html)
    matches = filters.css(
        'input.filter-checkbox[data-facet-type="2"]'
        f'[data-id="{TAKEDA_SWITZERLAND_FACET_ID}"]'
        f'[data-display="{TAKEDA_SWITZERLAND_COUNTRY}"]'
    )
    if len(matches) != 1:
        raise TakedaSwitzerlandParseError("Takeda response is missing its Switzerland facet")
    checkbox = matches[0]
    count = integer_attribute(checkbox, "data-count")
    checked = checkbox.css("::attr(checked)").get()
    if count != expected_total or checked is None:
        raise TakedaSwitzerlandParseError(
            "Takeda response did not preserve its Switzerland country facet"
        )


def parse_detail_html(page_html: str, *, expected_job_id: str) -> dict[str, Any]:
    page = Selector(page_html)
    current_job_id = optional_text(
        page.css('meta[name="search-analytics-currentJobId"]::attr(content)').get()
    )
    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    apply_url = optional_text(
        page.css('meta[name="search-job-apply-url"]::attr(content)').get()
    )
    if current_job_id != expected_job_id:
        raise TakedaSwitzerlandParseError("Takeda detail page has invalid job identity")
    if not valid_workday_apply_url(apply_url):
        raise TakedaSwitzerlandParseError("Takeda detail page has an invalid apply URL")

    postings: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            value = json.loads(str(raw))
        except json.JSONDecodeError as exc:
            raise TakedaSwitzerlandParseError(
                "Takeda detail page contains invalid JobPosting JSON"
            ) from exc
        postings.extend(job_postings(value))
    if len(postings) != 1:
        raise TakedaSwitzerlandParseError(
            "Takeda detail page must contain one JobPosting"
        )
    posting = postings[0]
    organization = posting.get("hiringOrganization")
    organization_name = (
        optional_text(organization.get("name")) if isinstance(organization, dict) else None
    )
    title = optional_text(posting.get("title"))
    description = optional_text(posting.get("description"))
    posting_url = optional_text(posting.get("url"))
    locations = swiss_job_locations(posting.get("jobLocation"))
    if (
        organization_name != "Takeda Pharmaceutical"
        or not title
        or not description
        or not valid_public_job_url(posting_url, expected_job_id=expected_job_id)
        or (canonical is not None and canonical != posting_url)
        or not locations
    ):
        raise TakedaSwitzerlandParseError(
            "Takeda detail page contains an incomplete or non-Swiss JobPosting"
        )
    detail = dict(posting)
    detail["url"] = posting_url
    detail["apply_url"] = apply_url
    detail["location"] = "; ".join(locations)
    return detail


def job_postings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and value.get("@type") == "JobPosting":
        return [value]
    graph = value.get("@graph") if isinstance(value, dict) else None
    if isinstance(graph, list):
        return [
            item
            for item in graph
            if isinstance(item, dict) and item.get("@type") == "JobPosting"
        ]
    return []


def swiss_job_locations(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    locations: list[str] = []
    for item in values:
        address = item.get("address") if isinstance(item, dict) else None
        if not isinstance(address, dict):
            continue
        country = optional_text(address.get("addressCountry"))
        if not country or country.casefold() != TAKEDA_SWITZERLAND_COUNTRY.casefold():
            continue
        parts = [
            optional_text(address.get("addressLocality")),
            optional_text(address.get("addressRegion")),
            country,
        ]
        locations.append(", ".join(part for part in parts if part))
    return list(dict.fromkeys(locations))


def valid_public_job_url(value: Any, *, expected_job_id: str) -> bool:
    url = optional_text(value)
    if not url:
        return False
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.takeda.com"
        and parts.path.startswith("/job/")
        and parts.path.endswith(f"/{TAKEDA_ORGANIZATION_ID}/{expected_job_id}")
        and not parts.query
        and not parts.fragment
    )


def valid_workday_apply_url(value: Any) -> bool:
    url = optional_text(value)
    if not url:
        return False
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold().endswith(".myworkdayjobs.com")
        and parts.netloc.casefold().startswith("takeda.")
        and parts.path.endswith("/apply")
        and not parts.query
        and not parts.fragment
    )


def fallback_swiss_location(value: Any) -> str:
    location = optional_text(value)
    if not location or location.casefold() == "multiple locations":
        return TAKEDA_SWITZERLAND_COUNTRY
    if TAKEDA_SWITZERLAND_COUNTRY.casefold() not in location.casefold():
        return f"{location}, {TAKEDA_SWITZERLAND_COUNTRY}"
    return location


def integer_attribute(node: Any, name: str) -> int:
    value = optional_text(node.css(f"::attr({name})").get())
    if not value or not re.fullmatch(r"\d+", value):
        raise TakedaSwitzerlandParseError(f"Takeda response has invalid {name}")
    return int(value)


def node_text(node: Any, selector: str) -> str | None:
    value = optional_text(" ".join(node.css(f"{selector} ::text").getall()))
    return value or optional_text(" ".join(node.css(f"{selector}::text").getall()))


def labeled_text(node: Any, selector: str, label: str) -> str | None:
    value = node_text(node, selector)
    if value and value.casefold().startswith(label.casefold()):
        value = optional_text(value[len(label) :])
    return value


def extract_job_id(record: dict[str, Any]) -> str:
    return optional_text(record.get("job_id")) or ""


def deduplicate_takeda_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(html.unescape(text)).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
