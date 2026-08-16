from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

GSK_SWITZERLAND_JOBS_BASE_URL = (
    "https://jobs.gsk.com/gb/en/search-results?"
    "keywords=&location=Switzerland&lang=en-gb"
)
GSK_RESULTS_PER_PAGE = 10
GSK_COUNTRY = "Switzerland"
GSK_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
DDO_PATTERN = re.compile(
    r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.experimentData",
    re.DOTALL,
)
CSRF_PATTERN = re.compile(r'"csrfToken"\s*:\s*"([^"]+)"')
GSK_SEARCH_FACETS = [
    "category",
    "country",
    "state",
    "city",
    "phLocSlider",
    "remoteType",
]


class GskSwitzerlandParseError(DirectCompanyRequestError):
    pass


class GskSwitzerlandJobsParser:
    """Collect the complete GSK Phenom country facet for Switzerland."""

    parser_id = "gsk_switzerland"

    def __init__(
        self,
        *,
        base_url: str = GSK_SWITZERLAND_JOBS_BASE_URL,
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
    def listing_endpoint(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/widgets"

    @property
    def job_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        prefix = parts.path.rsplit("/search-results", maxsplit=1)[0].rstrip("/")
        return f"{parts.scheme}://{parts.netloc}{prefix}/job"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**GSK_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                csrf_token = self.initialize_session(client)
                records, pages_fetched, total, catalog_passes = (
                    self.collect_listing_records(client, csrf_token=csrf_token)
                )
                self.enrich_records(client, records)
        except GskSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "GSK Switzerland vacancy request failed"
            ) from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "GSK Switzerland vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_gsk_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified GSK Switzerland vacancies from "
                f"{total} Phenom country records across {pages_fetched} page "
                f"requests in {catalog_passes} catalog pass(es)"
            ),
        )

    def initialize_session(self, client: httpx.Client) -> str:
        response = client.get(self.base_url)
        response.raise_for_status()
        match = CSRF_PATTERN.search(response.text)
        if not match:
            raise GskSwitzerlandParseError(
                "GSK Switzerland page is missing its CSRF token"
            )
        return match.group(1)

    def listing_payload(self, *, offset: int) -> dict[str, Any]:
        return {
            "lang": "en_gb",
            "deviceType": "desktop",
            "country": "gb",
            "pageName": "search-results",
            "pageId": "page23",
            "ddoKey": "refineSearch",
            "all_fields": GSK_SEARCH_FACETS,
            "pageType": "default",
            "from": offset,
            "size": GSK_RESULTS_PER_PAGE,
            "jobs": True,
            "counts": True,
            "clearAll": False,
            "jdsource": "facets",
            "isSliderEnable": False,
            "siteType": "external",
            "forceSpellCheck": True,
            "selected_fields": {"country": [GSK_COUNTRY]},
            "sortBy": "Most relevant",
            "keywords": "",
        }

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
        csrf_token: str,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.post(
            self.listing_endpoint,
            json=self.listing_payload(offset=offset),
            headers={
                "X-CSRF-TOKEN": csrf_token,
                "Referer": self.base_url,
            },
        )
        response.raise_for_status()
        total, records = parse_listing_payload(response.json())
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
        *,
        csrf_token: str,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_listing_page(
                client,
                offset=0,
                csrf_token=csrf_token,
            )
            pages_fetched += 1
            total = first_page[1]
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise GskSwitzerlandParseError(
                    "GSK Switzerland changed its vacancy total during pagination"
                )

            required_pages = max(1, ceil(total / GSK_RESULTS_PER_PAGE))
            if required_pages > self.max_pages:
                raise GskSwitzerlandParseError(
                    f"GSK Switzerland exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            offsets = list(range(GSK_RESULTS_PER_PAGE, total, GSK_RESULTS_PER_PAGE))
            page_results = [first_page]
            if offsets:
                with ThreadPoolExecutor(
                    max_workers=min(self.page_workers, len(offsets))
                ) as executor:
                    futures = [
                        executor.submit(
                            self.fetch_listing_page,
                            client,
                            offset=offset,
                            csrf_token=csrf_token,
                        )
                        for offset in offsets
                    ]
                    page_results.extend(
                        future.result() for future in as_completed(futures)
                    )
                pages_fetched += len(offsets)

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            for offset, page_total, records in sorted(page_results):
                expected_size = min(GSK_RESULTS_PER_PAGE, max(0, total - offset))
                if page_total != total or len(records) != expected_size:
                    catalog_changed = True
                for record in records:
                    if not is_swiss_vacancy(record):
                        raise GskSwitzerlandParseError(
                            "GSK country facet returned a vacancy without a Swiss location"
                        )
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = total
                    records_by_id.setdefault(extract_job_id(record), normalized)

            if not catalog_changed and len(records_by_id) == total:
                return (
                    list(records_by_id.values()),
                    pages_fetched,
                    total,
                    catalog_pass,
                )

        raise GskSwitzerlandParseError(
            f"GSK Switzerland yielded {len(records_by_id)} unique vacancies of "
            f"{expected_total or 0} catalog records"
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
            job_id = extract_job_id(record)
            try:
                response = client.get(
                    self.build_job_url(record),
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    expected_job_id=job_id,
                )
                if not is_swiss_vacancy(detail):
                    raise GskSwitzerlandParseError(
                        "GSK detail page is missing its Swiss location"
                    )
                return record, detail
            except (httpx.HTTPError, GskSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def build_job_url(self, record: dict[str, Any]) -> str:
        sequence = optional_text(record.get("jobSeqNo"))
        return f"{self.job_base_url}/{sequence or extract_job_id(record)}"

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        structure_data = detail.get("structureData")
        structure_data = structure_data if isinstance(structure_data, dict) else {}
        public_url = safe_canonical_url(
            detail.get("canonical_url"),
            expected_host=urlsplit(self.base_url).netloc,
        ) or self.build_job_url(record)
        description_html = optional_text(detail.get("description")) or optional_text(
            structure_data.get("description")
        )
        raw = dict(record)
        raw["detail"] = detail
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="GSK",
            location=extract_swiss_location(detail, record) or GSK_COUNTRY,
            url=public_url,
            apply_url=(
                optional_text(detail.get("applyUrl"))
                or optional_text(record.get("applyUrl"))
                or public_url
            ),
            posted_at=(
                optional_text(detail.get("postedDate"))
                or optional_text(structure_data.get("datePosted"))
                or optional_text(record.get("postedDate"))
            ),
            employment_type=(
                optional_text(detail.get("type"))
                or optional_text(detail.get("timeType"))
                or optional_text(record.get("type"))
            ),
            seniority=(
                optional_text(detail.get("workExperience"))
                or optional_text(detail.get("jobProfile"))
                or optional_text(record.get("workExperience"))
            ),
            description=(
                html_to_text(description_html)
                if description_html
                else optional_text(record.get("descriptionTeaser"))
            ),
            raw=raw,
        )


def parse_listing_payload(response_payload: Any) -> tuple[int, list[dict[str, Any]]]:
    payload = (
        response_payload.get("refineSearch")
        if isinstance(response_payload, dict)
        else None
    )
    if not isinstance(payload, dict):
        raise GskSwitzerlandParseError(
            "GSK Switzerland response is missing its vacancy catalog"
        )
    if payload.get("status") != 200:
        raise GskSwitzerlandParseError(
            "GSK Switzerland vacancy catalog has an invalid status"
        )
    total = payload.get("totalHits")
    hits = payload.get("hits")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise GskSwitzerlandParseError(
            "GSK Switzerland vacancy catalog has an invalid totalHits"
        )
    if isinstance(hits, bool) or not isinstance(hits, int) or hits < 0:
        raise GskSwitzerlandParseError(
            "GSK Switzerland vacancy catalog has invalid hits"
        )

    data = payload.get("data")
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list) or hits != len(jobs):
        raise GskSwitzerlandParseError(
            "GSK Switzerland vacancy catalog has invalid jobs"
        )
    validate_country_selection(data, expected_total=total)

    records: list[dict[str, Any]] = []
    for item in jobs:
        if (
            not isinstance(item, dict)
            or not extract_job_id(item)
            or not optional_text(item.get("jobSeqNo"))
            or not optional_text(item.get("title"))
        ):
            raise GskSwitzerlandParseError(
                "GSK Switzerland catalog contains an incomplete vacancy"
            )
        records.append(item)
    return total, records


def validate_country_selection(data: Any, *, expected_total: int) -> None:
    if not isinstance(data, dict):
        raise GskSwitzerlandParseError(
            "GSK Switzerland catalog has invalid country metadata"
        )
    selections = data.get("ui_selections")
    if not isinstance(selections, dict) or selections.get("country") != [GSK_COUNTRY]:
        raise GskSwitzerlandParseError(
            "GSK Switzerland catalog did not preserve its country selection"
        )
    aggregations = data.get("aggregations")
    if not isinstance(aggregations, list):
        raise GskSwitzerlandParseError(
            "GSK Switzerland catalog is missing its country aggregation"
        )
    country_values: dict[str, Any] | None = None
    for aggregation in aggregations:
        if isinstance(aggregation, dict) and aggregation.get("field") == "country":
            values = aggregation.get("value")
            country_values = values if isinstance(values, dict) else None
            break
    if country_values is None:
        raise GskSwitzerlandParseError(
            "GSK Switzerland catalog is missing its country aggregation"
        )
    if expected_total == 0 and GSK_COUNTRY not in country_values:
        return
    if country_values.get(GSK_COUNTRY) != expected_total:
        raise GskSwitzerlandParseError(
            "GSK Switzerland catalog has an invalid country count"
        )


def parse_detail_html(
    page_html: str,
    *,
    expected_job_id: str,
) -> dict[str, Any]:
    ddo = parse_ddo(page_html)
    payload = ddo.get("jobDetail")
    if not isinstance(payload, dict):
        raise GskSwitzerlandParseError("GSK detail page is missing jobDetail")
    if payload.get("status") != 200:
        raise GskSwitzerlandParseError("GSK detail page has an invalid status")
    data = payload.get("data")
    job = data.get("job") if isinstance(data, dict) else None
    if (
        not isinstance(job, dict)
        or not extract_job_id(job)
        or extract_job_id(job) != expected_job_id
    ):
        raise GskSwitzerlandParseError(
            "GSK detail page contains an invalid vacancy"
        )
    detail = dict(job)
    canonical_url = Selector(page_html).css('link[rel="canonical"]::attr(href)').get()
    if canonical_url:
        detail["canonical_url"] = html.unescape(canonical_url)
    return detail


def parse_ddo(page_html: str) -> dict[str, Any]:
    match = DDO_PATTERN.search(page_html)
    if not match:
        raise GskSwitzerlandParseError("GSK page is missing phApp.ddo data")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GskSwitzerlandParseError("GSK page contains invalid phApp.ddo JSON") from exc
    if not isinstance(payload, dict):
        raise GskSwitzerlandParseError("GSK phApp.ddo data must be an object")
    return payload


def extract_job_id(record: dict[str, Any]) -> str:
    return (
        optional_text(record.get("jobId"))
        or optional_text(record.get("reqId"))
        or optional_text(record.get("jobSeqNo"))
        or ""
    )


def extract_multi_locations(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("multi_location", "multi_location_array"):
        locations = record.get(key)
        if not isinstance(locations, Sequence) or isinstance(locations, (str, bytes)):
            continue
        for item in locations:
            if isinstance(item, dict):
                value = (
                    optional_text(item.get("cityStateCountry"))
                    or optional_text(item.get("location"))
                    or optional_text(item.get("address"))
                    or optional_text(item.get("country"))
                )
            else:
                value = optional_text(item)
            if value:
                values.append(value)
    return list(dict.fromkeys(values))


def record_locations(record: dict[str, Any]) -> list[str]:
    values = [
        value
        for key in ("cityStateCountry", "location", "address", "country")
        if (value := optional_text(record.get(key)))
    ]
    values.extend(extract_multi_locations(record))
    structure_data = record.get("structureData")
    if isinstance(structure_data, dict):
        job_location = structure_data.get("jobLocation")
        address = job_location.get("address") if isinstance(job_location, dict) else None
        if isinstance(address, dict):
            parts = [
                optional_text(address.get("addressLocality")),
                optional_text(address.get("addressRegion")),
                optional_text(address.get("addressCountry")),
            ]
            structured_location = ", ".join(part for part in parts if part)
            if structured_location:
                values.append(structured_location)
    return list(dict.fromkeys(values))


def is_swiss_vacancy(record: dict[str, Any]) -> bool:
    return any("switzerland" in value.casefold() for value in record_locations(record))


def extract_swiss_location(
    detail: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    for record in (detail, listing):
        primary = optional_text(record.get("cityStateCountry")) or optional_text(
            record.get("location")
        )
        country = optional_text(record.get("country"))
        if primary and (
            "switzerland" in primary.casefold()
            or (country and country.casefold() == "switzerland")
        ):
            return primary
        multi_locations = [
            value
            for value in extract_multi_locations(record)
            if "switzerland" in value.casefold()
        ]
        if multi_locations:
            return ", ".join(dict.fromkeys(multi_locations))
        structure_data = record.get("structureData")
        job_location = (
            structure_data.get("jobLocation")
            if isinstance(structure_data, dict)
            else None
        )
        address = job_location.get("address") if isinstance(job_location, dict) else None
        if isinstance(address, dict):
            structured_country = optional_text(address.get("addressCountry"))
            if structured_country and structured_country.casefold() == "switzerland":
                parts = [
                    optional_text(address.get("addressLocality")),
                    optional_text(address.get("addressRegion")),
                    structured_country,
                ]
                return ", ".join(part for part in parts if part)
    return None


def safe_canonical_url(value: Any, *, expected_host: str) -> str | None:
    url = optional_text(value)
    if not url:
        return None
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host.casefold()
        or "/job/" not in parts.path
        or parts.query
        or parts.fragment
    ):
        return None
    return url


def deduplicate_gsk_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
