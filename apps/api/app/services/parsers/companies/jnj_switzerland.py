from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

JNJ_SWITZERLAND_JOBS_BASE_URL = (
    "https://www.careers.jnj.com/en/jobs/?"
    "search=&country=Switzerland&origin=global"
)
JNJ_COMPANY = "Johnson & Johnson"
JNJ_SCHEMA_ORGANIZATION = "Johnson & Johnson Services, Inc."
JNJ_COUNTRY = "Switzerland"
JNJ_RESULTS_PER_PAGE = 20
JNJ_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "Referer": "https://www.google.com/",
}
JOB_ID_PATTERN = re.compile(r"^r-\d+$", re.IGNORECASE)
RESULTS_HEADING_PATTERN = re.compile(
    r"^Displaying\s+(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+matching jobs$",
    re.IGNORECASE,
)


class JnjSwitzerlandParseError(DirectCompanyRequestError):
    pass


class JnjSwitzerlandJobsParser:
    """Collect the complete J&J careers country catalog for Switzerland."""

    parser_id = "jnj_switzerland"

    def __init__(
        self,
        *,
        base_url: str = JNJ_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        page_workers: int = 4,
        detail_workers: int = 8,
        fetch_page: Callable[[str], ScraplingResponse] | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.page_workers = min(8, max(1, page_workers))
        self.detail_workers = min(12, max(1, detail_workers))
        self.fetch_page = fetch_page or self._fetch_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            records, total, pages_fetched, catalog_passes = (
                self.collect_listing_records()
            )
            self.enrich_records(records)
        except JnjSwitzerlandParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError(
                "Johnson & Johnson Switzerland vacancy request failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_jnj_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Johnson & Johnson Switzerland "
                f"vacancies from {total} country records across {pages_fetched} "
                f"page requests in {catalog_passes} catalog pass(es)"
            ),
        )

    def _fetch_with_scrapling(self, url: str) -> ScraplingResponse:
        response = Fetcher.get(
            url,
            headers=JNJ_HEADERS,
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        status = int(getattr(response, "status", 0) or 0)
        if not 200 <= status < 300:
            raise JnjSwitzerlandParseError(
                f"Johnson & Johnson careers returned HTTP {status}"
            )
        return response

    def fetch_listing_page(
        self,
        *,
        page_number: int,
    ) -> tuple[int, int, int, list[dict[str, Any]]]:
        page_url = listing_page_url(self.base_url, page_number=page_number)
        document = self.fetch_page(page_url)
        total, total_pages, records = parse_listing_page(
            document,
            page_url=page_url,
            expected_page=page_number,
        )
        return page_number, total, total_pages, records

    def collect_listing_records(
        self,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        pages_fetched = 0
        last_unique_count = 0
        last_total = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_listing_page(page_number=1)
            pages_fetched += 1
            total = first_page[1]
            total_pages = first_page[2]
            last_total = total
            if total_pages > self.max_pages:
                raise JnjSwitzerlandParseError(
                    f"Johnson & Johnson Switzerland exposes {total_pages} pages, "
                    f"above the configured limit of {self.max_pages}"
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
                            page_number=page_number,
                        )
                        for page_number in remaining_pages
                    ]
                    page_results.extend(
                        future.result() for future in as_completed(futures)
                    )
                pages_fetched += len(remaining_pages)

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            for page_number, page_total, page_count, records in sorted(page_results):
                if page_total != total or page_count != total_pages:
                    catalog_changed = True
                for record in records:
                    job_id = extract_job_id(record)
                    normalized = dict(record)
                    normalized["listing_page"] = page_number
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = total
                    if job_id in records_by_id:
                        catalog_changed = True
                    records_by_id.setdefault(job_id, normalized)

            last_unique_count = len(records_by_id)
            if not catalog_changed and last_unique_count == total:
                return list(records_by_id.values()), total, pages_fetched, catalog_pass

        raise JnjSwitzerlandParseError(
            f"Johnson & Johnson Switzerland yielded {last_unique_count} unique "
            f"vacancies of {last_total} country records"
        )

    def enrich_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                document = self.fetch_page(record["url"])
                detail = parse_detail_page(
                    document,
                    expected_job_id=extract_job_id(record),
                )
                return record, detail
            except (JnjSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None
            except Exception as exc:  # noqa: BLE001 - preserve verified listing records
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
            company=JNJ_COMPANY,
            location=(
                optional_text(detail.get("location"))
                or fallback_swiss_location(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("datePosted")),
            employment_type=(
                normalize_employment_type(detail.get("employmentType"))
                or optional_text(record.get("category"))
            ),
            description=html_to_text(description_html) if description_html else None,
            raw=raw,
        )


def listing_page_url(base_url: str, *, page_number: int) -> str:
    if page_number < 1:
        raise ValueError("page_number must be positive")
    parts = urlsplit(base_url)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.careers.jnj.com"
        or parts.path != "/en/jobs/"
        or parts.fragment
    ):
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson careers URL is outside the expected scope"
        )
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if query.get("country") != JNJ_COUNTRY or query.get("origin") != "global":
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson careers URL is missing its Switzerland filter"
        )
    if page_number == 1:
        query.pop("page", None)
    else:
        query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def parse_listing_page(
    document: ScraplingResponse,
    *,
    page_url: str,
    expected_page: int,
) -> tuple[int, int, list[dict[str, Any]]]:
    if listing_page_url(page_url, page_number=expected_page) != page_url:
        raise JnjSwitzerlandParseError("Johnson & Johnson listing URL is invalid")
    title = selector_text(document, "title")
    expected_title = "Explore current job openings | Johnson & Johnson Careers"
    if expected_page > 1:
        expected_title = f"{expected_title} - Page {expected_page}"
    expected_canonical = "https://www.careers.jnj.com/en/jobs/"
    if expected_page > 1:
        expected_canonical = f"{expected_canonical}?page={expected_page}"
    canonical_urls = {
        optional_text(value)
        for value in document.css('link[rel="canonical"]::attr(href)').getall()
    }
    selected_countries = {
        optional_text(value)
        for value in document.css(
            'select[name="country"] option[selected]::attr(value)'
        ).getall()
    }
    if (
        comparable_text(title) != comparable_text(expected_title)
        or canonical_urls != {expected_canonical}
        or selected_countries != {JNJ_COUNTRY}
    ):
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson listing did not preserve its Switzerland identity"
        )

    headings = [
        value
        for node in document.css("main h2")
        if (value := selector_text(node)) and RESULTS_HEADING_PATTERN.fullmatch(value)
    ]
    empty_messages = {
        optional_text(value)
        for value in document.css("main p.lead::text").getall()
    }
    if not headings and empty_messages == {
        "Sorry, there are no results that match your criteria."
    }:
        if expected_page != 1 or document.css("main .PagePromo-contentWrap"):
            raise JnjSwitzerlandParseError(
                "Johnson & Johnson listing has an inconsistent empty state"
            )
        return 0, 0, []
    if len(headings) != 1:
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson listing is missing its result count"
        )
    match = RESULTS_HEADING_PATTERN.fullmatch(headings[0])
    if match is None:
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson listing has an invalid result count"
        )
    first_result, last_result, total = (int(value) for value in match.groups())
    total_pages = ceil(total / JNJ_RESULTS_PER_PAGE)
    expected_first = ((expected_page - 1) * JNJ_RESULTS_PER_PAGE) + 1
    expected_last = min(expected_page * JNJ_RESULTS_PER_PAGE, total)
    if total < 1 or first_result != expected_first or last_result != expected_last:
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson listing has invalid pagination metadata"
        )

    cards = document.css("main .PagePromo-contentWrap")
    records: list[dict[str, Any]] = []
    for card in cards:
        links = card.css(':scope a.js-view-job[href*="/en/jobs/r-"]')
        if not links:
            continue
        if len(links) != 1:
            raise JnjSwitzerlandParseError(
                "Johnson & Johnson listing contains an invalid vacancy card"
            )
        link = links[0]
        path = optional_text(link.css("::attr(href)").get())
        title_text = selector_text(link)
        location = selector_text(card, ":scope address.PagePromo-location")
        category = selector_text(card, ":scope .PagePromo-category")
        card_ids = {
            optional_text(value)
            for value in card.css(":scope .js-job::attr(data-id)").getall()
        }
        job_id = job_id_from_path(path)
        if (
            not path
            or not job_id
            or card_ids != {job_id}
            or not title_text
            or not location
            or not category
        ):
            raise JnjSwitzerlandParseError(
                "Johnson & Johnson listing contains an incomplete vacancy"
            )
        records.append(
            {
                "job_id": job_id,
                "title": title_text,
                "location": location,
                "category": category,
                "url": urljoin("https://www.careers.jnj.com", path),
            }
        )

    expected_count = last_result - first_result + 1
    if len(records) != expected_count:
        raise JnjSwitzerlandParseError(
            f"Johnson & Johnson listing page {expected_page} returned "
            f"{len(records)} of {expected_count} expected vacancies"
        )
    if len({extract_job_id(record) for record in records}) != len(records):
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson listing contains duplicate vacancy IDs"
        )
    return total, total_pages, records


def parse_detail_page(
    document: ScraplingResponse,
    *,
    expected_job_id: str,
) -> dict[str, Any]:
    raw_scripts = document.css('script[type="application/ld+json"]::text').getall()
    postings: list[dict[str, Any]] = []
    for raw in raw_scripts:
        try:
            value = json.loads(str(raw))
        except json.JSONDecodeError as exc:
            raise JnjSwitzerlandParseError(
                "Johnson & Johnson detail contains invalid JobPosting JSON"
            ) from exc
        postings.extend(job_postings(value))
    if len(postings) != 1:
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson detail must contain one JobPosting"
        )
    posting = postings[0]
    identifier = optional_text(posting.get("identifier"))
    title = optional_text(posting.get("title"))
    description = optional_text(posting.get("description"))
    posting_url = canonical_job_url(posting.get("url"))
    canonical_urls = {
        canonical_job_url(value)
        for value in document.css('link[rel="canonical"]::attr(href)').getall()
    }
    canonical_urls.discard(None)
    organization = posting.get("hiringOrganization")
    organization_name = (
        optional_text(organization.get("name")) if isinstance(organization, dict) else None
    )
    locations = swiss_job_locations(posting.get("jobLocation"))
    apply_urls = {
        canonical_workday_apply_url(value)
        for value in document.css(
            'main a.js-apply-external[href*="myworkdayjobs.com"]::attr(href)'
        ).getall()
    }
    apply_urls.discard(None)
    apply_url = next(iter(apply_urls)) if len(apply_urls) == 1 else None
    if (
        comparable_text(identifier) != comparable_text(expected_job_id)
        or not title
        or not description
        or not posting_url
        or canonical_urls != {posting_url}
        or organization_name != JNJ_SCHEMA_ORGANIZATION
        or not locations
        or not apply_url
    ):
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson detail contains an incomplete or non-Swiss JobPosting"
        )
    if job_id_from_path(urlsplit(posting_url).path) != expected_job_id:
        raise JnjSwitzerlandParseError(
            "Johnson & Johnson detail contains a mismatched vacancy ID"
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
        if not country or comparable_text(country) != comparable_text(JNJ_COUNTRY):
            continue
        parts = [
            optional_text(address.get("addressLocality")),
            optional_text(address.get("addressRegion")),
            country,
        ]
        locations.append(", ".join(part for part in parts if part))
    return list(dict.fromkeys(locations))


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.careers.jnj.com"
        or not job_id_from_path(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.careers.jnj.com", parts.path, "", ""))


def canonical_workday_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "jj.wd5.myworkdayjobs.com"
        or "/JJ/job/" not in parts.path
        or not parts.path.endswith("/apply")
        or parts.query
        or parts.fragment
    ):
        return None
    return text


def job_id_from_path(value: Any) -> str | None:
    path = optional_text(value)
    if not path:
        return None
    match = re.fullmatch(r"/en/jobs/(r-\d+)/[^/]+/", path, re.IGNORECASE)
    return match.group(1).casefold() if match else None


def fallback_swiss_location(value: Any) -> str:
    location = optional_text(value)
    if not location:
        return JNJ_COUNTRY
    return f"{location}, {JNJ_COUNTRY}"


def normalize_employment_type(value: Any) -> str | None:
    text = optional_text(value)
    return text.replace("_", " ").title() if text else None


def extract_job_id(record: dict[str, Any]) -> str:
    return optional_text(record.get("job_id")) or ""


def deduplicate_jnj_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    if not selected:
        return None
    return optional_text(" ".join(selected[0].css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", html.unescape(str(value))).strip() or None
