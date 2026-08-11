from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

STADLER_IT_SWITZERLAND_JOBS_URL = (
    "https://www.stadlerrail.com/de/karriere/offene-stellen?10=1077445&25=1098730&"
)
STADLER_CAREERCENTER_URL = "https://ohws.prospective.ch/public/v1/careercenter/1000470/"
STADLER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
IT_FILTER_ID = "1077445"
SWITZERLAND_FILTER_ID = "1098730"
JOB_ID_PATTERN = re.compile(r"^job-(\d+)$", re.IGNORECASE)
PAGE_COUNT_PATTERN = re.compile(r"(\d+)\s+von\s+(\d+)", re.IGNORECASE)
RECORD_COUNT_PATTERN = re.compile(r"Offene\s+Stellen:\s*(\d+)", re.IGNORECASE)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%")
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
SWISS_COUNTRIES = {"ch", "schweiz", "switzerland", "suisse", "svizzera"}


class StadlerItSwitzerlandParseError(DirectCompanyRequestError):
    pass


class StadlerItSwitzerlandJobsParser:
    """Collect Stadler vacancies selected by its official Swiss IT filters."""

    parser_id = "stadler_it_switzerland"

    def __init__(
        self,
        *,
        base_url: str = STADLER_IT_SWITZERLAND_JOBS_URL,
        catalog_url: str = STADLER_CAREERCENTER_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        page_size: int = 200,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(8, max(1, detail_workers))
        self.page_size = max(1, page_size)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**STADLER_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, catalog_passes = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except StadlerItSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Stadler vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Stadler vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_stadler_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Stadler IT Switzerland vacancies across "
                f"{pages_fetched} Prospective pages in {catalog_passes} catalog pass(es)"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        pages_fetched = 0
        last_count = 0
        last_total = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_response = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            records, total, total_pages = parse_listing_html(
                first_response.text,
                page_url=str(first_response.url),
                expected_page=1,
                page_size=self.page_size,
            )
            if total_pages > self.max_pages:
                raise StadlerItSwitzerlandParseError(
                    "Stadler IT Switzerland catalog exceeds the configured limit of "
                    f"{self.max_pages} pages"
                )

            pass_records = list(records)
            pass_ids = {str(record["id"]) for record in records}
            duplicate_found = len(pass_ids) != len(records)

            for page_number in range(2, total_pages + 1):
                response = self.fetch_listing_page(
                    client,
                    offset=(page_number - 1) * self.page_size,
                )
                pages_fetched += 1
                page_records, page_total, page_count = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_page=page_number,
                    page_size=self.page_size,
                )
                if page_total != total or page_count != total_pages:
                    duplicate_found = True
                for record in page_records:
                    job_id = str(record["id"])
                    if job_id in pass_ids:
                        duplicate_found = True
                        continue
                    pass_ids.add(job_id)
                    pass_records.append(record)

            last_count = len(pass_records)
            last_total = total
            if not duplicate_found and last_count == total:
                return pass_records, pages_fetched, catalog_pass

        raise StadlerItSwitzerlandParseError(
            "Stadler IT Switzerland catalog did not stabilize after "
            f"{self.max_catalog_passes} passes (collected {last_count} of {last_total})"
        )

    def fetch_listing_page(self, client: httpx.Client, *, offset: int) -> httpx.Response:
        response = client.post(
            self.catalog_url,
            data={
                "offset": str(offset),
                "limit": str(self.page_size),
                "lang": "de",
                "filter_10": IT_FILTER_ID,
                "filter_25": SWITZERLAND_FILTER_ID,
            },
        )
        response.raise_for_status()
        return response

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
                    str(record["url"]),
                    headers={"Referer": self.catalog_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_title=optional_text(record.get("title")),
                )
            except (
                httpx.HTTPError,
                StadlerItSwitzerlandParseError,
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
        apply_url = (
            optional_text(detail.get("apply_url"))
            or secure_url(record.get("apply_url"))
            or optional_text(record.get("url"))
        )
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="Stadler",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=optional_text(record.get("url")),
            apply_url=apply_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=join_unique(
                optional_text(detail.get("workload")),
                optional_text(detail.get("contract_type")),
                normalize_employment_type(detail.get("employment_type")),
            ),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int, int]:
    page = Selector(page_html)
    if (
        not page.css("form#oh-form")
        or not selected_option(page, "filter_10", IT_FILTER_ID)
        or not selected_option(page, "filter_25", SWITZERLAND_FILTER_ID)
    ):
        raise StadlerItSwitzerlandParseError(
            "Stadler listing did not retain the official IT and Switzerland filters"
        )

    record_count_text = selector_text(page, "#recordcount")
    record_count_match = RECORD_COUNT_PATTERN.search(record_count_text or "")
    if not record_count_match:
        raise StadlerItSwitzerlandParseError("Stadler listing is missing its vacancy count")
    total = int(record_count_match.group(1))
    expected_total_pages = max(1, math.ceil(total / page_size))

    pagination_text = selector_text(page, "#pagination strong")
    pagination_match = PAGE_COUNT_PATTERN.search(pagination_text or "")
    if not pagination_match:
        raise StadlerItSwitzerlandParseError("Stadler listing is missing its pagination state")
    current_page, total_pages = (int(value) for value in pagination_match.groups())
    if (
        current_page != expected_page
        or total_pages != expected_total_pages
        or current_page > total_pages
    ):
        raise StadlerItSwitzerlandParseError(
            "Stadler listing returned an inconsistent pagination state"
        )

    cards = page.css("#itemlist .platform-item")
    if len(cards) > page_size or (total > 0 and not cards):
        raise StadlerItSwitzerlandParseError("Stadler listing is missing its vacancy catalog")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        id_match = JOB_ID_PATTERN.match(optional_text(card.attrib.get("id")) or "")
        job_id = id_match.group(1) if id_match else None
        title = optional_text(card.attrib.get("title"))
        detail_url = optional_text(card.attrib.get("job-href"))
        apply_url = optional_text(card.attrib.get("data-href"))
        displayed_title = selector_text(card, ".itemlist_jobtitle a")
        categories = [
            value
            for item in card.css(".itemlist_text .item")
            if (value := selector_text(item, "::self"))
        ]
        if not categories:
            categories = [
                value
                for value in (
                    optional_text(item) for item in card.css(".itemlist_text .item::text").getall()
                )
                if value
            ]
        if (
            not job_id
            or job_id in seen_ids
            or not title
            or not detail_url
            or not valid_detail_url(detail_url)
            or not apply_url
            or not displayed_title
            or "informatik" not in {item.casefold() for item in categories}
        ):
            raise StadlerItSwitzerlandParseError(
                "Stadler listing contains an incomplete or non-IT vacancy"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": extract_listing_location(displayed_title, title),
                "categories": categories,
                "url": detail_url,
                "apply_url": secure_url(apply_url),
                "listing_page": expected_page,
                "listing_page_url": page_url,
            }
        )
    return records, total, total_pages


def selected_option(page: Selector, field: str, value: str) -> bool:
    option = page.css(f'select[name="{field}"] option[value="{value}"]').first
    return bool(option and "selected" in {key.casefold() for key in option.attrib})


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_title: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    # Prospective emits the schema after </html>, which lxml may discard.
    if not schema:
        schema = next(extract_job_posting_schemas_from_html(page_html), {})

    title = optional_text(html.unescape(str(schema.get("title", ""))))
    description_html = optional_text(schema.get("description"))
    apply_path = optional_text(page.css("a.button.apply::attr(href)").get())
    location = extract_swiss_schema_location(schema)
    if not title or not description_html or not apply_path or not location:
        raise StadlerItSwitzerlandParseError("Stadler detail page is missing required vacancy data")
    if expected_title and title.casefold() != expected_title.casefold():
        raise StadlerItSwitzerlandParseError("Stadler detail page returned a different vacancy")

    metadata = [
        value
        for value in (
            optional_text(item) for item in page.css("#introduction ul.meta li span::text").getall()
        )
        if value
    ]
    workload = next((item for item in metadata if WORKLOAD_PATTERN.search(item)), None)
    contract_type = next(
        (
            item
            for item in metadata
            if item != workload
            and not is_swiss_location_text(item)
            and item.casefold() not in {"m/w/d", "f/m/d", "w/m/d"}
        ),
        None,
    )
    description = html_to_text(description_html)
    if not description:
        raise StadlerItSwitzerlandParseError("Stadler detail page has no vacancy description")

    hiring_organization = schema.get("hiringOrganization")
    organization = hiring_organization if isinstance(hiring_organization, dict) else {}
    return {
        "title": title,
        "location": location,
        "apply_url": urljoin(page_url, apply_path),
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "workload": workload,
        "contract_type": contract_type,
        "employment_type": schema.get("employmentType"),
        "description": description,
        "hiring_organization": optional_text(organization.get("name")),
        "schema": schema,
    }


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        yield from parse_job_posting_payload(raw_script)


def extract_job_posting_schemas_from_html(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        yield from parse_job_posting_payload(match.group(1))


def parse_job_posting_payload(raw_json: Any) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(str(raw_json))
    except (json.JSONDecodeError, TypeError, ValueError):
        return
    for candidate in walk_json(payload):
        job_type = candidate.get("@type")
        if job_type == "JobPosting" or (isinstance(job_type, list) and "JobPosting" in job_type):
            yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_swiss_schema_location(schema: dict[str, Any]) -> str | None:
    locations = schema.get("jobLocation")
    if isinstance(locations, Sequence) and not isinstance(locations, (str, bytes)):
        candidates = locations
    else:
        candidates = [locations]

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


def extract_listing_location(displayed_title: str, title: str) -> str | None:
    if displayed_title.casefold() == title.casefold():
        return None
    if displayed_title.casefold().startswith(title.casefold()):
        suffix = displayed_title[len(title) :]
        return optional_text(re.sub(r"^[\s\-–—:|]+", "", suffix))
    return None


def is_swiss_location_text(value: str) -> bool:
    normalized = value.casefold()
    return any(country in normalized for country in SWISS_COUNTRIES)


def valid_detail_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.hostname == "jobs.stadlerrail.ch"


def secure_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme == "http":
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return text


def normalize_employment_type(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        normalized = [normalize_employment_type(item) for item in value]
        return join_unique(*(item for item in normalized if item))
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


def deduplicate_stadler_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        raw_id = optional_text(job.raw.get("id"))
        key = raw_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, selector: str) -> str | None:
    if selector == "::self":
        return optional_text(" ".join(node.css("::text").getall()))
    return optional_text(" ".join(node.css(f"{selector} ::text").getall())) or optional_text(
        " ".join(node.css(f"{selector}::text").getall())
    )


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
