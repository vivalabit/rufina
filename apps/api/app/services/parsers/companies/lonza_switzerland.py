from __future__ import annotations

import html
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

LONZA_SWITZERLAND_JOBS_BASE_URL = "https://www.lonza.com/careers/job-search"
LONZA_COMPANY = "Lonza"
LONZA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "Referer": LONZA_SWITZERLAND_JOBS_BASE_URL,
}
RESULT_RANGE_PATTERN = re.compile(
    r"Showing\s+(\d[\d,]*)\s*[\-\u2010-\u2014]\s*(\d[\d,]*)\s+of\s+(\d[\d,]*)",
    re.IGNORECASE,
)
JOB_PATH_PATTERN = re.compile(r"^/jobs/(R\d+)$", re.IGNORECASE)
LISTING_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
REFERENCE_PATTERN = re.compile(r"^Reference:\s*(R\d+)$", re.IGNORECASE)
SWISS_LOCATION_PREFIX = "switzerland, "

GetPageFetcher = Callable[[str], ScraplingResponse]
PostPageFetcher = Callable[[str, list[tuple[str, str]]], ScraplingResponse]


class LonzaSwitzerlandParseError(DirectCompanyRequestError):
    pass


class LonzaSwitzerlandJobsParser:
    """Collect Lonza's complete location-filtered Swiss vacancy catalog."""

    parser_id = "lonza_switzerland"

    def __init__(
        self,
        *,
        base_url: str = LONZA_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        fetch_get: GetPageFetcher | None = None,
        fetch_post: PostPageFetcher | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.fetch_get = fetch_get or self._get_with_scrapling
        self.fetch_post = fetch_post or self._post_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            discovery_page = self.fetch_get(self.base_url)
            listing_id, swiss_locations = parse_listing_context(discovery_page)
            records, pages_fetched, total = self.collect_listing_records(
                listing_id=listing_id,
                swiss_locations=swiss_locations,
            )
            self.enrich_records(records)
        except LonzaSwitzerlandParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError("Lonza vacancy request failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_lonza_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Lonza Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} filtered page {request_label}"
            ),
        )

    def _get_with_scrapling(self, url: str) -> ScraplingResponse:
        response = Fetcher.get(
            url,
            headers={**LONZA_HEADERS, "Referer": self.base_url},
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        validate_response_status(response)
        return response

    def _post_with_scrapling(
        self,
        url: str,
        data: list[tuple[str, str]],
    ) -> ScraplingResponse:
        response = Fetcher.post(
            url,
            data=data,
            headers={
                **LONZA_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self.base_url,
            },
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        validate_response_status(response)
        return response

    def listing_form_data(
        self,
        *,
        page: int,
        listing_id: str,
        swiss_locations: tuple[str, ...],
    ) -> list[tuple[str, str]]:
        return [
            ("q", ""),
            ("pg", str(page)),
            ("lid", listing_id),
            *(("job_location_facet_sm", location) for location in swiss_locations),
        ]

    def fetch_listing_page(
        self,
        *,
        page: int,
        listing_id: str,
        swiss_locations: tuple[str, ...],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        response = self.fetch_post(
            self.base_url,
            self.listing_form_data(
                page=page,
                listing_id=listing_id,
                swiss_locations=swiss_locations,
            ),
        )
        return parse_listing_page(
            response,
            page_url=self.base_url,
            expected_page=page,
            expected_listing_id=listing_id,
            expected_swiss_locations=swiss_locations,
        )

    def collect_listing_records(
        self,
        *,
        listing_id: str,
        swiss_locations: tuple[str, ...],
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, first_metadata = self.fetch_listing_page(
                page=1,
                listing_id=listing_id,
                swiss_locations=swiss_locations,
            )
            pages_fetched += 1
            total = first_metadata["total"]
            if total == 0:
                return [], pages_fetched, 0
            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if first_metadata["start"] != 1 or page_size <= 0:
                raise LonzaSwitzerlandParseError(
                    "Lonza pagination returned an invalid first page"
                )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise LonzaSwitzerlandParseError(
                    "Lonza catalog changed its result count during pagination"
                )

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise LonzaSwitzerlandParseError(
                    f"Lonza exposes {required_pages} pages, above the configured limit of "
                    f"{self.max_pages}"
                )

            page_results = [first_records]
            for page in range(2, required_pages + 1):
                records, metadata = self.fetch_listing_page(
                    page=page,
                    listing_id=listing_id,
                    swiss_locations=swiss_locations,
                )
                pages_fetched += 1
                expected_start = (page - 1) * page_size + 1
                expected_end = min(page * page_size, total)
                if (
                    metadata["total"] != expected_total
                    or metadata["start"] != expected_start
                    or metadata["end"] != expected_end
                ):
                    raise LonzaSwitzerlandParseError(
                        "Lonza pagination returned an unexpected result range"
                    )
                page_results.append(records)

            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise LonzaSwitzerlandParseError(
                    "Lonza catalog changed while pages were collected"
                )

        raise LonzaSwitzerlandParseError(
            f"Lonza returned {len(records_by_id)} unique vacancies but declared "
            f"{expected_total or 0}"
        )

    def enrich_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                detail_page = self.fetch_get(record["url"])
                detail = parse_detail_page(
                    detail_page,
                    page_url=record["url"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                )
                return record, detail
            except Exception as exc:  # noqa: BLE001
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(
            max_workers=min(self.detail_workers, len(records))
        ) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
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
            company=LONZA_COMPANY,
            location=(
                optional_text(detail.get("location"))
                or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            employment_type=extract_workload(title),
            seniority=(
                "Senior"
                if title and re.search(r"\bsenior\b", title, re.IGNORECASE)
                else None
            ),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def validate_response_status(response: ScraplingResponse) -> None:
    status = int(getattr(response, "status", 0) or 0)
    if status >= 400:
        raise LonzaSwitzerlandParseError(f"Lonza returned HTTP {status}")


def parse_listing_context(page: ScraplingResponse) -> tuple[str, tuple[str, ...]]:
    forms = page.css("form#link-form")
    if len(forms) != 1 or comparable_text(forms[0].css("::attr(method)").get()) != "post":
        raise LonzaSwitzerlandParseError(
            "Lonza careers page is missing its official search form"
        )
    listing_ids = {
        optional_text(value)
        for value in forms[0].css('input[name="lid"]::attr(value)').getall()
    }
    listing_ids.discard(None)
    listing_id = next(iter(listing_ids)) if len(listing_ids) == 1 else None
    if not listing_id or not LISTING_ID_PATTERN.fullmatch(listing_id):
        raise LonzaSwitzerlandParseError("Lonza careers page has an invalid listing ID")

    swiss_locations = sorted(
        {
            value
            for value in (
                optional_text(item)
                for item in page.css(
                    'input[name="job_location_facet_sm"]::attr(value)'
                ).getall()
            )
            if value and is_swiss_location(value)
        }
    )
    if not swiss_locations:
        raise LonzaSwitzerlandParseError(
            "Lonza careers page is missing its Swiss location facets"
        )
    return listing_id, tuple(swiss_locations)


def parse_listing_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    expected_page: int,
    expected_listing_id: str,
    expected_swiss_locations: tuple[str, ...],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    forms = page.css("form#link-form")
    if len(forms) != 1:
        raise LonzaSwitzerlandParseError("Lonza listing page is missing its search form")
    form = forms[0]
    listing_id = optional_text(form.css('input[name="lid"]::attr(value)').get())
    page_number = optional_text(form.css('input[name="pg"]::attr(value)').get())
    query = optional_text(form.css('input[name="q"]::attr(value)').get())
    checked_locations = {
        optional_text(value)
        for value in page.css(
            'input[name="job_location_facet_sm"][checked]::attr(value)'
        ).getall()
    }
    checked_locations.discard(None)
    if (
        listing_id != expected_listing_id
        or page_number != str(expected_page)
        or query is not None
        or checked_locations != set(expected_swiss_locations)
    ):
        raise LonzaSwitzerlandParseError(
            "Lonza listing page did not preserve the Swiss catalog filter"
        )

    range_text = selector_text(page, ".page-count")
    range_match = RESULT_RANGE_PATTERN.fullmatch(range_text or "")
    if not range_match:
        raise LonzaSwitzerlandParseError(
            "Lonza listing page is missing its result range"
        )
    metadata = {
        "start": parse_count(range_match.group(1)),
        "end": parse_count(range_match.group(2)),
        "total": parse_count(range_match.group(3)),
    }
    cards = page.css('a.search-result[href^="/jobs/"]')
    if metadata["total"] == 0:
        if metadata["start"] != 0 or metadata["end"] != 0 or cards:
            raise LonzaSwitzerlandParseError(
                "Lonza listing returned inconsistent empty-result metadata"
            )
        return [], metadata
    if (
        metadata["start"] < 1
        or metadata["end"] < metadata["start"]
        or metadata["total"] < metadata["end"]
        or len(cards) != metadata["end"] - metadata["start"] + 1
    ):
        raise LonzaSwitzerlandParseError(
            "Lonza listing returned inconsistent result metadata"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        path = optional_text(card.css("::attr(href)").get())
        detail_url = (
            canonical_job_url(urljoin(LONZA_SWITZERLAND_JOBS_BASE_URL, path))
            if path
            else None
        )
        job_id = extract_job_id(detail_url)
        title = selector_text(card, ".search-result-title")
        location = selector_text(card, ".search-result-content")
        if (
            not detail_url
            or not job_id
            or not title
            or not location
            or not contains_swiss_location(location)
        ):
            raise LonzaSwitzerlandParseError(
                "Lonza listing contains an incomplete or non-Swiss vacancy"
            )
        if job_id in seen_ids:
            raise LonzaSwitzerlandParseError(
                "Lonza listing page contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": LONZA_COMPANY,
                "location": location,
                "url": detail_url,
                "listing_page_url": page_url,
                "listing_page": expected_page,
            }
        )
    return records, metadata


def parse_detail_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    expected_job_id: str,
    expected_title: str,
) -> dict[str, Any]:
    canonical_values = {
        canonical_job_url(value)
        for value in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    canonical_values.discard(None)
    title_values = {
        selector_text(node)
        for node in page.css(".cmp-job-posting .detail-page-hero .h1")
    }
    title_values.discard(None)
    location_values = [
        optional_text(value)
        for value in page.css(".cmp-job-posting .job-posting-location span::text").getall()
    ]
    location_values = [value for value in location_values if value]
    reference_values = {
        optional_text(value)
        for value in page.css(".cmp-job-posting .job-posting .h6::text").getall()
    }
    reference_values.discard(None)
    apply_values = {
        canonical_apply_url(value, expected_job_id=expected_job_id)
        for value in page.css(".cmp-job-posting a.btn.apply::attr(href)").getall()
    }
    apply_values.discard(None)
    # Workday descriptions may wrap whole sections in divs rather than expose
    # paragraphs directly. Select the outer blocks once to avoid duplicate text.
    description_parts = page.css(
        ".cmp-job-posting .job-posting > .row > .col-md-8"
    ).xpath("./p | ./ul | ./ol | ./h2 | ./h3 | ./div[.//p or .//ul or .//ol]").getall()
    description = html_to_text("".join(str(value) for value in description_parts))
    location = "; ".join(location_values)
    expected_url = canonical_job_url(page_url)
    reference_ids = {
        match.group(1).upper()
        for value in reference_values
        if (match := REFERENCE_PATTERN.fullmatch(value))
    }
    if (
        not expected_url
        or canonical_values != {expected_url}
        or title_values != {expected_title}
        or reference_ids != {expected_job_id.upper()}
        or len(apply_values) != 1
        or not location
        or not contains_swiss_location(location)
        or not description
        or len(description) < 100
    ):
        raise LonzaSwitzerlandParseError(
            "Lonza detail page is missing required Swiss vacancy data"
        )
    return {
        "id": expected_job_id.upper(),
        "title": expected_title,
        "company": LONZA_COMPANY,
        "location": location,
        "apply_url": next(iter(apply_values)),
        "description": description,
    }


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path.rstrip("/"))
    if (
        parts.scheme != "https"
        or parts.hostname != "www.lonza.com"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://www.lonza.com/jobs/{match.group(1).upper()}"


def canonical_apply_url(value: Any, *, expected_job_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(html.unescape(text))
    if (
        parts.scheme == "https"
        and parts.netloc == "lonza.wd3.myworkdayjobs.com"
        and re.fullmatch(
            rf"/Lonza_Careers/job/[^/]+/[^/]+_{re.escape(expected_job_id.upper())}/apply/?",
            parts.path,
        )
        and not parts.query
        and not parts.fragment
    ):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    expected_path = f"/projects/ext/{expected_job_id.upper()}/apply"
    params = parse_qsl(parts.query, keep_blank_values=True)
    allowed_params = {
        ("utm_source", "careersite"),
        ("utm_medium", "referral"),
    }
    if (
        parts.scheme != "https"
        or parts.hostname != "lonza.talent-community.com"
        or parts.path != expected_path
        or set(params) != allowed_params
        or len(params) != len(allowed_params)
        or parts.fragment
    ):
        return None
    return urlunsplit(
        (
            "https",
            "lonza.talent-community.com",
            expected_path,
            urlencode(sorted(params)),
            "",
        )
    )


def extract_job_id(value: Any) -> str | None:
    url = canonical_job_url(value)
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1).upper() if match else None


def contains_swiss_location(value: str) -> bool:
    return any(is_swiss_location(part) for part in value.split(";"))


def is_swiss_location(value: str) -> bool:
    return comparable_text(value).startswith(SWISS_LOCATION_PREFIX)


def extract_workload(title: str | None) -> str | None:
    if not title:
        return None
    match = re.search(r"\b(\d{1,3})\s*(?:[-\u2010-\u2014]\s*(\d{1,3})\s*)?%", title)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}%" if match.group(2) else f"{match.group(1)}%"


def deduplicate_lonza_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def parse_count(value: str) -> int:
    return int(value.replace(",", ""))


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    if not selected:
        return None
    values = selected[0].css("::text").getall()
    return optional_text(" ".join(str(value) for value in values if value))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    return optional_multiline_text(html.unescape(re.sub(r"<[^>]+>", "", text)))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = (
        str(value)
        .replace("\u200b", "")
        .replace("\xa0", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", html.unescape(str(value))).strip() or None
