from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

RUAG_SWITZERLAND_JOBS_URL = "https://www.ruag.ch/en/working-us/job-portal"
RUAG_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
PAGE_SIZE = 20
JOB_PATH_PATTERN = re.compile(
    r"/offene-stellen/[^/]+/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    r"/apply/ats/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
RESULT_COUNT_PATTERN = re.compile(
    r"(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+results",
    re.IGNORECASE,
)
HEADING_COUNT_PATTERN = re.compile(r"(\d+)\s+results\s+found", re.IGNORECASE)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%")
GENDER_SUFFIX_PATTERN = re.compile(
    r"\s*(?:\([a-z](?:\s*[/|·-]\s*[a-z])+\)|[a-z](?:\s*[/|·-]\s*[a-z])+)$",
    re.IGNORECASE,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
SWISS_COUNTRIES = {"ch", "schweiz", "switzerland", "suisse", "svizzera"}


class RuagSwitzerlandParseError(DirectCompanyRequestError):
    pass


class RuagSwitzerlandJobsParser:
    """Collect RUAG's complete Swiss catalog from its paginated Drupal view."""

    parser_id = "ruag_switzerland"

    def __init__(
        self,
        *,
        base_url: str = RUAG_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(2, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        validate_catalog_url(self.base_url)
        try:
            with CareerHttpClient(
                headers=RUAG_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, catalog_passes = self.collect_listing_records(
                    client
                )
                self.enrich_records(client, records)
        except RuagSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(f"RUAG Switzerland vacancy request failed: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("RUAG Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ruag_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} RUAG Switzerland vacancies across "
                f"{pages_fetched} catalog pages in {catalog_passes} catalog pass(es)"
            ),
        )

    def collect_listing_records(
        self,
        client: CareerHttpClient,
    ) -> tuple[list[dict[str, Any]], int, int]:
        pages_fetched = 0
        last_count = 0
        last_total = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            records_by_id: dict[str, dict[str, Any]] = {}
            first_response = self.fetch_listing_page(client, page=0)
            pages_fetched += 1
            first_records, total, total_pages = parse_listing_html(
                first_response.text,
                page_url=str(first_response.url),
                expected_page=0,
            )
            if total_pages > self.max_pages:
                raise RuagSwitzerlandParseError(
                    "RUAG Switzerland catalog exceeds the configured limit of "
                    f"{self.max_pages} pages"
                )
            for record in first_records:
                records_by_id[str(record["id"])] = record

            stable_total = True
            for page in range(1, total_pages):
                response = self.fetch_listing_page(client, page=page)
                pages_fetched += 1
                page_records, page_total, page_count = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_page=page,
                )
                if page_total != total or page_count != total_pages:
                    stable_total = False
                    break
                for record in page_records:
                    records_by_id[str(record["id"])] = record

            last_count = len(records_by_id)
            last_total = total
            if stable_total and last_count == total:
                return list(records_by_id.values()), pages_fetched, catalog_pass

        raise RuagSwitzerlandParseError(
            "RUAG Switzerland catalog changed during pagination: "
            f"collected {last_count} of {last_total} vacancies"
        )

    def fetch_listing_page(self, client: CareerHttpClient, *, page: int) -> httpx.Response:
        response = client.get(
            self.base_url,
            params={"page": page} if page else None,
            headers={"Referer": self.base_url},
        )
        response.raise_for_status()
        if not valid_catalog_response_url(response.url, expected_page=page):
            raise RuagSwitzerlandParseError(
                "RUAG Switzerland catalog redirected outside its official listing"
            )
        return response

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
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_title=optional_text(record.get("title")),
                    expected_job_id=optional_text(record.get("id")),
                )
                return record, detail
            except (httpx.HTTPError, RuagSwitzerlandParseError, ValueError) as exc:
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
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(detail.get("hiring_organization")) or "RUAG AG",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=join_unique(
                optional_text(record.get("workload")),
                normalize_employment_type(detail.get("employment_type")),
            ),
            seniority=optional_text(record.get("experience")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def validate_catalog_url(catalog_url: str) -> None:
    parsed = urlsplit(catalog_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.ruag.ch"
        or parsed.path.rstrip("/") != "/en/working-us/job-portal"
        or parsed.query
    ):
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland catalog URL is not the official unfiltered listing"
        )


def valid_catalog_response_url(value: Any, *, expected_page: int) -> bool:
    parsed = urlsplit(str(value))
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.ruag.ch"
        or parsed.path.rstrip("/") != "/en/working-us/job-portal"
    ):
        return False
    query = httpx.QueryParams(parsed.query)
    return query.get("page") == str(expected_page) if expected_page else not query


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_page: int,
) -> tuple[list[dict[str, Any]], int, int]:
    page = Selector(page_html)
    if (
        not page.css("#job-results .ruag-c-filtered-view")
        or not page.css("#views-exposed-form-jobfilter-block-1")
    ):
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland listing page is missing its catalog contract"
        )

    heading = selector_text(page, "#job-results .ruag-c-filtered-view__view > h3")
    count_text = selector_text(page, "#job-results .ruag-o-pagination__count")
    heading_match = HEADING_COUNT_PATTERN.fullmatch(heading or "")
    count_match = RESULT_COUNT_PATTERN.fullmatch(count_text or "")
    if not heading_match or not count_match:
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland listing page is missing its result count"
        )

    start, end, total = (int(value) for value in count_match.groups())
    if int(heading_match.group(1)) != total or total < 1:
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland listing result counters disagree"
        )
    total_pages = math.ceil(total / PAGE_SIZE)
    expected_start = expected_page * PAGE_SIZE + 1
    expected_end = min(total, expected_start + PAGE_SIZE - 1)
    active_page = selector_text(page, "#job-results .pager__item.is-active")
    if (
        start != expected_start
        or end != expected_end
        or active_page != str(expected_page + 1)
    ):
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland listing returned an unexpected catalog page"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    cards = page.css("#job-results a.ruag-c-result-list-item")
    for card in cards:
        detail_path = optional_text(card.attrib.get("href"))
        detail_url = urljoin(page_url, detail_path) if detail_path else None
        job_id = extract_job_id(detail_url)
        title_parts = [optional_text(value) for value in card.css("h3 span::text").getall()]
        title_parts = [value for value in title_parts if value]
        facts = [
            optional_text(value)
            for value in card.css("p.ruag-c-result-list-item__fact::text").getall()
        ]
        facts = [value for value in facts if value]
        if len(title_parts) != 2 or len(facts) != 4:
            raise RuagSwitzerlandParseError(
                "RUAG Switzerland listing contains an incomplete vacancy"
            )
        title, gender_suffix = title_parts
        experience, city, country, workload = facts
        if (
            not job_id
            or job_id in seen_ids
            or not valid_detail_url(detail_url)
            or country.casefold() not in SWISS_COUNTRIES
            or not WORKLOAD_PATTERN.fullmatch(workload)
        ):
            raise RuagSwitzerlandParseError(
                "RUAG Switzerland listing contains an invalid vacancy"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "gender_suffix": gender_suffix,
                "experience": experience,
                "location": join_unique(city, country),
                "country": country,
                "workload": workload,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    if len(records) != end - start + 1:
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland listing count does not match its vacancy cards"
        )
    return records, total, total_pages


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_title: str | None,
    expected_job_id: str | None,
) -> dict[str, Any]:
    if expected_job_id and extract_job_id(page_url) != expected_job_id:
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland detail page changed its vacancy ID"
        )
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    # Prospective emits JobPosting after </html>, which lxml may discard.
    if not schema:
        schema = next(extract_job_posting_schemas_from_html(page_html), {})

    title = selector_text(page, "#jobTitle h1")
    schema_title = optional_text(html.unescape(str(schema.get("title", ""))))
    description_html = optional_text(schema.get("description"))
    apply_path = optional_text(
        page.css('a[href^="https://jobs.ruag.ch/apply/ats/"]::attr(href)').get()
    )
    location = extract_swiss_schema_location(schema)
    organization = extract_hiring_organization(schema)
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    if (
        not title
        or not schema_title
        or not description_html
        or not apply_url
        or not valid_apply_url(apply_url, expected_job_id=expected_job_id)
        or not location
        or not organization
    ):
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland detail page is missing required vacancy data"
        )
    if expected_title and comparable_title(title) != comparable_title(expected_title):
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland detail page returned a different vacancy"
        )
    if comparable_title(schema_title) != comparable_title(title):
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland JobPosting title does not match the vacancy"
        )

    description = html_to_text(description_html)
    if not description:
        raise RuagSwitzerlandParseError(
            "RUAG Switzerland detail page has no vacancy description"
        )
    return {
        "title": title,
        "location": location,
        "apply_url": apply_url,
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "employment_type": schema.get("employmentType"),
        "description": description,
        "hiring_organization": organization,
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


def extract_hiring_organization(schema: dict[str, Any]) -> str:
    organization = schema.get("hiringOrganization")
    if not isinstance(organization, dict):
        return ""
    return optional_text(organization.get("name")) or ""


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1).lower() if match else None


def valid_detail_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parsed = urlsplit(text)
    return parsed.scheme == "https" and parsed.hostname == "jobs.ruag.ch" and bool(
        extract_job_id(text)
    )


def valid_apply_url(value: Any, *, expected_job_id: str | None) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parsed = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parsed.path)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == "jobs.ruag.ch"
        and match
        and (not expected_job_id or match.group(1).lower() == expected_job_id)
    )


def comparable_title(value: str) -> str:
    return optional_text(GENDER_SUFFIX_PATTERN.sub("", value)) or ""


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


def deduplicate_ruag_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, selector: str) -> str | None:
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
