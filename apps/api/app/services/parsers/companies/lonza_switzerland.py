from __future__ import annotations

import html
import re
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from threading import Lock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)
from app.services.parsers.companies.http import (
    RETRYABLE_STATUSES,
    CareerHttpClient,
    fetch_with_retry,
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
        detail_workers: int = 2,
        fetch_get: GetPageFetcher | None = None,
        fetch_post: PostPageFetcher | None = None,
        workday_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(2, max(1, detail_workers))
        self._request_lock = Lock()
        self._next_request_at = 0.0
        self.fetch_get = fetch_get or self._get_with_scrapling
        self.fetch_post = fetch_post or self._post_with_scrapling
        self.workday_transport = workday_transport
        self._use_workday_reconciliation = workday_transport is not None or (
            fetch_get is None and fetch_post is None
        )

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            discovery_page = self.fetch_get(self.base_url)
            listing_id, swiss_locations = parse_listing_context(discovery_page)
            records, pages_fetched, total = self.collect_listing_records(
                listing_id=listing_id,
                swiss_locations=swiss_locations,
            )
            self.enrich_records(records)
            if self._use_workday_reconciliation and any(
                record.get("detail_error") == "Lonza returned HTTP 404" for record in records
            ):
                self.reconcile_workday_catalog(records)
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
        def fetch() -> ScraplingResponse:
            # Bound request rate as well as concurrency for the public detail host.
            with self._request_lock:
                time.sleep(max(0.0, self._next_request_at - time.monotonic()))
                self._next_request_at = time.monotonic() + 0.5
            return Fetcher.get(
                url,
                headers={**LONZA_HEADERS, "Referer": self.base_url},
                impersonate="chrome",
                timeout=self.timeout_seconds,
            )

        response = fetch_with_retry(
            fetch,
            retryable_statuses=RETRYABLE_STATUSES | {403},
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
                raise LonzaSwitzerlandParseError("Lonza pagination returned an invalid first page")
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
                raise LonzaSwitzerlandParseError("Lonza catalog changed while pages were collected")

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

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def reconcile_workday_catalog(self, records: list[dict[str, Any]]) -> None:
        """Resolve stale CMS links against a complete, country-verified ATS scan.

        A 404 alone never removes a vacancy. Only a reconciled full Workday
        catalog can confirm it absent; new ATS postings are also retained.
        """
        country_id = "187134fccb084a0ea9b4b95f23890dbe"
        origin = "https://lonza.wd3.myworkdayjobs.com"
        api = origin + "/wday/cxs/lonza/Lonza_Careers"
        paths: dict[str, dict[str, Any]] = {}
        total: int | None = None
        offset = 0
        try:
            with CareerHttpClient(
                timeout=self.timeout_seconds, transport=self.workday_transport
            ) as client:
                while total is None or offset < total:
                    response = client.post_catalog(
                        api + "/jobs",
                        json={
                            "appliedFacets": {"locationCountry": [country_id]},
                            "limit": 20,
                            "offset": offset,
                            "searchText": "",
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or type(payload.get("total")) is not int:
                        raise LonzaSwitzerlandParseError("Lonza Workday catalog has no valid total")
                    page_total = payload["total"]
                    postings = payload.get("jobPostings")
                    # Workday returns aggregate metadata only at offset zero;
                    # later pages use total=0 and facets=[] alongside postings.
                    metadata_omitted = (
                        offset > 0 and page_total == 0 and payload.get("facets") == []
                    )
                    if metadata_omitted:
                        page_total = total
                    if total is None:
                        total = page_total
                    if (
                        total < 0
                        or page_total != total
                        or total > self.max_pages * 20
                        or not isinstance(postings, list)
                        or len(postings) != min(20, total - offset)
                    ):
                        raise LonzaSwitzerlandParseError(
                            "Lonza Workday catalog is incomplete or changed"
                        )
                    facets = list(workday_country_facets(payload.get("facets")))
                    if not metadata_omitted and (
                        (total and facets != [(country_id, total)])
                        or (not total and facets not in ([], [(country_id, 0)]))
                    ):
                        raise LonzaSwitzerlandParseError(
                            "Lonza Workday Switzerland facet is unverified"
                        )
                    for posting in postings:
                        path = posting.get("externalPath") if isinstance(posting, dict) else None
                        match = re.fullmatch(r"/job/[^/?#]+/[^/?#]+_(R\d+)(?:-\d+)?", path or "")
                        if (
                            not match
                            or not optional_text(posting.get("title"))
                            or match[1] in paths
                        ):
                            raise LonzaSwitzerlandParseError(
                                "Lonza Workday vacancy identity is invalid or duplicated"
                            )
                        paths[match[1]] = posting
                    offset += 20
                existing_ids = {record["id"] for record in records}
                # Delay removals until every page and country facet was validated.
                reconciled = [
                    record
                    for record in records
                    if not (
                        record.get("detail_error") == "Lonza returned HTTP 404"
                        and record["id"] not in paths
                    )
                ]
                for job_id, posting in paths.items():
                    if job_id not in existing_ids:
                        reconciled.append(
                            {
                                "id": job_id,
                                "title": posting["title"],
                                "company": LONZA_COMPANY,
                                "location": "Switzerland",
                                "url": origin + "/Lonza_Careers" + posting["externalPath"],
                                "listing_source": "official_workday_catalog",
                                "total_available": total,
                            }
                        )
                for record in reconciled:
                    if record.get("detail") or record["id"] not in paths:
                        continue
                    posting = paths[record["id"]]
                    try:
                        response = client.get(api + posting["externalPath"])
                        response.raise_for_status()
                        payload = response.json()
                        detail = (
                            payload.get("jobPostingInfo") if isinstance(payload, dict) else None
                        )
                        country = detail.get("country") if isinstance(detail, dict) else None
                        expected_url = origin + "/Lonza_Careers" + posting["externalPath"]
                        if (
                            not isinstance(detail, dict)
                            or detail.get("jobReqId") != record["id"]
                            or comparable_text(detail.get("title"))
                            != comparable_text(posting["title"])
                            or detail.get("externalUrl") != expected_url
                            or not isinstance(country, dict)
                            or country.get("id") != country_id
                            or not html_to_text(detail.get("jobDescription"))
                        ):
                            raise LonzaSwitzerlandParseError(
                                "Lonza Workday detail has an invalid identity or country"
                            )
                        record["title"] = detail["title"]
                        record["detail"] = {
                            "title": detail["title"],
                            "location": f"{detail.get('location') or ''}, Switzerland".lstrip(", "),
                            "description": html_to_text(detail["jobDescription"]),
                            "apply_url": expected_url + "/apply",
                            "workday": detail,
                        }
                        record.pop("detail_error", None)
                    except (httpx.HTTPError, ValueError, LonzaSwitzerlandParseError) as exc:
                        record["detail_error"] = str(exc)
                records[:] = reconciled
        except (httpx.HTTPError, ValueError, LonzaSwitzerlandParseError) as exc:
            for record in records:
                if record.get("detail_error") == "Lonza returned HTTP 404":
                    record["detail_error"] += f"; Workday reconciliation unavailable: {exc}"

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
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            employment_type=extract_workload(title),
            seniority=(
                "Senior" if title and re.search(r"\bsenior\b", title, re.IGNORECASE) else None
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
        raise LonzaSwitzerlandParseError("Lonza careers page is missing its official search form")
    listing_ids = {
        optional_text(value) for value in forms[0].css('input[name="lid"]::attr(value)').getall()
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
                for item in page.css('input[name="job_location_facet_sm"]::attr(value)').getall()
            )
            if value and is_swiss_location(value)
        }
    )
    if not swiss_locations:
        raise LonzaSwitzerlandParseError("Lonza careers page is missing its Swiss location facets")
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
        for value in page.css('input[name="job_location_facet_sm"][checked]::attr(value)').getall()
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
        raise LonzaSwitzerlandParseError("Lonza listing page is missing its result range")
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
        raise LonzaSwitzerlandParseError("Lonza listing returned inconsistent result metadata")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        path = optional_text(card.css("::attr(href)").get())
        detail_url = (
            canonical_job_url(urljoin(LONZA_SWITZERLAND_JOBS_BASE_URL, path)) if path else None
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
            raise LonzaSwitzerlandParseError("Lonza listing page contains duplicate vacancy IDs")
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
        canonical_job_url(value) for value in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    canonical_values.discard(None)
    title_values = {
        selector_text(node) for node in page.css(".cmp-job-posting .detail-page-hero .h1")
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
    description_parts = (
        page.css(".cmp-job-posting .job-posting > .row > .col-md-8")
        .xpath("./p | ./ul | ./ol | ./h2 | ./h3 | ./div[.//p or .//ul or .//ol]")
        .getall()
    )
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
        raise LonzaSwitzerlandParseError("Lonza detail page is missing required Swiss vacancy data")
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


def workday_country_facets(nodes: Any) -> Iterable[tuple[str, int]]:
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("facetParameter") == "locationCountry":
            for value in node.get("values", []):
                if (
                    isinstance(value, dict)
                    and value.get("id") == "187134fccb084a0ea9b4b95f23890dbe"
                ):
                    yield value["id"], value.get("count")
        yield from workday_country_facets(node.get("values"))
