from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

NOVARTIS_SWITZERLAND_JOBS_URL = (
    "https://www.novartis.com/careers/career-search?search_api_fulltext="
    "&country%5B%5D=LOC_CH&field_job_posted_date=All&op=Submit"
)
NOVARTIS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
PAGE_SIZE = 10
JOB_PATH_PATTERN = re.compile(
    r"^/careers/career-search/job/details/(req-\d+)-[a-z0-9][a-z0-9-]*/?$",
    re.IGNORECASE,
)
RESULT_COUNT_PATTERN = re.compile(r"Showing\s+(\d+)\s+results?", re.IGNORECASE)
PAGINATION_PATTERN = re.compile(
    r"page\s+(\d+)\s+active\s+out\s+of\s+(\d+)\s+pages?",
    re.IGNORECASE,
)
SALARY_PATTERN = re.compile(
    r"CHF\s*([\d',]+(?:\.\d+)?)\s*[-–]\s*CHF\s*([\d',]+(?:\.\d+)?)",
    re.IGNORECASE,
)


class NovartisSwitzerlandParseError(DirectCompanyRequestError):
    pass


class NovartisSwitzerlandJobsParser:
    """Collect every Novartis vacancy available in Switzerland."""

    parser_id = "novartis_switzerland"

    def __init__(
        self,
        *,
        base_url: str = NOVARTIS_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = urlunsplit((*urlsplit(base_url)[:3], "", ""))
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**NOVARTIS_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, catalog_passes = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except NovartisSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Novartis vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Novartis vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_novartis_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Novartis Switzerland vacancies across "
                f"{pages_fetched} page requests in {catalog_passes} catalog pass(es)"
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
            first_response = self.fetch_listing_page(client, page_number=1)
            pages_fetched += 1
            records, total, total_pages = parse_listing_html(
                first_response.text,
                page_url=str(first_response.url),
                expected_page=1,
            )
            if total_pages > self.max_pages:
                raise NovartisSwitzerlandParseError(
                    "Novartis Switzerland catalog exceeds the configured limit of "
                    f"{self.max_pages} pages"
                )

            pass_records = list(records)
            pass_ids = {str(record["id"]) for record in records}
            unstable = len(pass_ids) != len(records)
            for page_number in range(2, total_pages + 1):
                response = self.fetch_listing_page(client, page_number=page_number)
                pages_fetched += 1
                page_records, page_total, page_count = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_page=page_number,
                )
                if page_total != total or page_count != total_pages:
                    unstable = True
                for record in page_records:
                    job_id = str(record["id"])
                    if job_id in pass_ids:
                        unstable = True
                        continue
                    pass_ids.add(job_id)
                    pass_records.append(record)

            last_count = len(pass_records)
            last_total = total
            if not unstable and last_count == total:
                return pass_records, pages_fetched, catalog_pass

        raise NovartisSwitzerlandParseError(
            "Novartis Switzerland catalog did not stabilize after "
            f"{self.max_catalog_passes} passes (collected {last_count} of {last_total})"
        )

    def fetch_listing_page(self, client: httpx.Client, *, page_number: int) -> httpx.Response:
        params: list[tuple[str, str]] = [
            ("search_api_fulltext", ""),
            ("country[]", "LOC_CH"),
            ("field_job_posted_date", "All"),
            ("op", "Submit"),
            ("sort", "asc"),
            ("order", "Job Title"),
        ]
        if page_number > 1:
            params.append(("page", str(page_number - 1)))
        response = client.get(self.catalog_url, params=params)
        response.raise_for_status()
        return response

    def enrich_records(self, client: httpx.Client, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(str(record["url"]), headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_id=str(record["id"]),
                    expected_title=str(record["title"]),
                )
            except (httpx.HTTPError, NovartisSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company="Novartis",
            location=optional_text(detail.get("location")) or optional_text(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at")),
            employment_type=optional_text(record.get("employment_type")),
            seniority=extract_seniority(title),
            description=optional_multiline_text(detail.get("description")),
            salary=optional_text(detail.get("salary")),
            salary_min=detail.get("salary_min"),
            salary_max=detail.get("salary_max"),
            salary_currency=optional_text(detail.get("salary_currency")),
            salary_unit=optional_text(detail.get("salary_unit")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_page: int,
) -> tuple[list[dict[str, Any]], int, int]:
    page = Selector(page_html)
    selected_country = page.css(
        'form#search-listing-filter-form select[name="country[]"] option[selected]::attr(value)'
    ).getall()
    all_date_active = page.css(
        '.form-item-field-job-posted-date a.content-type.active[href*="field_job_posted_date=All"]'
    )
    if selected_country != ["LOC_CH"] or not all_date_active.get():
        raise NovartisSwitzerlandParseError(
            "Novartis listing did not retain the official Switzerland and All dates filters"
        )

    count_texts = page.css(".view-header::text").getall()
    count_match = next(
        (match for value in count_texts if (match := RESULT_COUNT_PATTERN.search(value))),
        None,
    )
    if not count_match:
        raise NovartisSwitzerlandParseError("Novartis listing is missing its result count")
    total = int(count_match.group(1))
    expected_pages = max(1, math.ceil(total / PAGE_SIZE))

    active_title = optional_text(
        page.css(
            "nav[aria-label='pagination-heading'] li.active [title]::attr(title)"
        ).get()
    )
    pagination_match = PAGINATION_PATTERN.search(active_title or "")
    if not pagination_match:
        raise NovartisSwitzerlandParseError("Novartis listing is missing its pagination state")
    current_page, total_pages = (int(value) for value in pagination_match.groups())
    if current_page != expected_page or total_pages != expected_pages:
        raise NovartisSwitzerlandParseError(
            "Novartis listing returned an inconsistent pagination state"
        )

    rows = page.css(".view-id-career_search table.views-table tbody tr")
    expected_rows = PAGE_SIZE if expected_page < total_pages else total - PAGE_SIZE * (total_pages - 1)
    if len(rows) != expected_rows:
        raise NovartisSwitzerlandParseError("Novartis listing is missing vacancy rows")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        href = optional_text(row.css(".views-field-field-job-title a::attr(href)").get())
        detail_url = urljoin(page_url, href) if href else None
        job_id = extract_job_id(detail_url)
        title = selector_text(row, ".views-field-field-job-title a")
        title_cell = selector_text(row, ".views-field-field-job-title")
        employment_type = optional_text(title_cell.removeprefix(title).strip()) if title and title_cell else None
        business = selector_text(row, ".views-field-field-job-business-unit")
        country = optional_text(row.css(".views-field-field-job-country::text").get())
        alternative = selector_text(row, ".views-field-field-job-country .alternative-locations")
        site = selector_text(row, ".views-field-field-job-work-location")
        posted_at = selector_text(row, ".views-field-field-job-posted-date")
        has_swiss_location = comparable_text(country) == "switzerland" or bool(alternative)
        if (
            not detail_url
            or not job_id
            or not title
            or not employment_type
            or not business
            or not country
            or not site
            or not posted_at
            or not has_swiss_location
        ):
            raise NovartisSwitzerlandParseError(
                "Novartis listing contains an incomplete or non-Swiss vacancy"
            )
        if job_id in seen_ids:
            raise NovartisSwitzerlandParseError(
                "Novartis listing page contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        location = (
            f"{site}, Switzerland"
            if comparable_text(country) == "switzerland"
            else "Switzerland (alternative location)"
        )
        records.append(
            {
                "id": job_id,
                "title": title,
                "employment_type": employment_type,
                "business": business,
                "country": country,
                "site": site,
                "has_alternative_locations": bool(alternative),
                "location": location,
                "posted_at": posted_at,
                "url": detail_url,
                "listing_page_url": page_url,
                "total_available": total,
            }
        )
    return records, total, total_pages


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_id: str,
    expected_title: str,
) -> dict[str, Any]:
    if extract_job_id(page_url) != expected_id:
        raise NovartisSwitzerlandParseError("Novartis detail page returned a different vacancy")
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page_html), {})
    title = optional_text(schema.get("title"))
    identifier = comparable_text(schema.get("identifier"))
    apply_url = optional_text(page.css('a[title="Apply to Job"]::attr(href)').get())
    if (
        not title
        or comparable_text(title) != comparable_text(expected_title)
        or identifier != expected_id
        or not valid_apply_url(apply_url, expected_id=expected_id)
    ):
        raise NovartisSwitzerlandParseError(
            "Novartis detail page is missing required vacancy data"
        )

    primary_country = selector_text(
        page, ".job_details_content_bottom .field_job_country div.element_items"
    )
    primary_site = selector_text(
        page, ".job_details_content_bottom .field_job_work_location div.element_items"
    )
    alternatives = [
        value
        for item in page.css(".job_details_content_bottom .field_alternative_country")
        if (value := selector_text(item, "div.element_items"))
    ]
    location = swiss_detail_location(primary_country, primary_site, alternatives)
    if not location:
        raise NovartisSwitzerlandParseError(
            "Novartis detail page does not contain a Swiss primary or alternative location"
        )

    sections = [
        value
        for item in page.css(".job_details_content_center .job_description")
        if (value := html_to_text(item.get()))
    ]
    description = "\n\n".join(dict.fromkeys(sections))
    if not description:
        raise NovartisSwitzerlandParseError("Novartis detail page is missing its description")

    salary = selector_text(
        page, ".job_details_content_bottom .field_pay_range div.element_items"
    )
    salary_data = parse_salary(salary)
    return {
        "title": title,
        "location": location,
        "apply_url": apply_url,
        "posted_at": optional_text(schema.get("datePosted")),
        "description": description,
        "salary": salary_data.get("salary"),
        "salary_min": salary_data.get("salary_min"),
        "salary_max": salary_data.get("salary_max"),
        "salary_currency": salary_data.get("salary_currency"),
        "salary_unit": salary_data.get("salary_unit"),
        "primary_country": primary_country,
        "primary_site": primary_site,
        "alternative_locations": alternatives,
        "schema": schema,
    }


def extract_job_posting_schemas(page_html: str) -> Iterator[dict[str, Any]]:
    page = Selector(page_html)
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
            continue
        for candidate in walk_json(payload):
            if candidate.get("@type") == "JobPosting":
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def swiss_detail_location(
    primary_country: Any,
    primary_site: Any,
    alternatives: list[str],
) -> str | None:
    if comparable_text(primary_country) == "switzerland" and optional_text(primary_site):
        return f"{optional_text(primary_site)}, Switzerland"
    for location in alternatives:
        if comparable_text(location).endswith(", switzerland"):
            return location
    return None


def parse_salary(value: Any) -> dict[str, Any]:
    text = optional_text(value)
    match = SALARY_PATTERN.search(text or "")
    if not match:
        return {}
    minimum, maximum = (float(number.replace(",", "").replace("'", "")) for number in match.groups())
    return {
        "salary": text,
        "salary_min": minimum,
        "salary_max": maximum,
        "salary_currency": "CHF",
        "salary_unit": "year",
    }


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text or urlsplit(text).hostname != "www.novartis.com":
        return None
    match = JOB_PATH_PATTERN.match(urlsplit(text).path)
    return match.group(1).lower() if match else None


def valid_apply_url(value: Any, *, expected_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return parts.hostname == "novartis.wd3.myworkdayjobs.com" and expected_id in parts.path.casefold()


def deduplicate_novartis_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = extract_job_id(job.url)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job)
    return unique


def extract_seniority(title: Any) -> str | None:
    text = comparable_text(title)
    if re.search(r"\b(executive director|head|lead|principal)\b", text):
        return "Lead"
    if re.search(r"\b(senior|sr\.)\b", text):
        return "Senior"
    if re.search(r"\b(junior|jr\.)\b", text):
        return "Junior"
    return None


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|ul|ol)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+|[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def selector_text(node: Any, selector: str) -> str | None:
    selected = node.css(selector).get()
    return optional_text(html_to_text(selected)) if selected else None


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    return re.sub(r"\n{3,}", "\n\n", text).strip() if text else None


def comparable_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip().casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = html.unescape(str(value)).strip()
    return normalized or None
