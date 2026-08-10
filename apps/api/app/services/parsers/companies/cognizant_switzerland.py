from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

COGNIZANT_SWITZERLAND_JOBS_BASE_URL = (
    "https://careers.cognizant.com/global-en/jobs/?keyword=&location=Switzerland"
    "&lat=&lng=&cname=Switzerland&ccode=CH&origin=global"
)
COGNIZANT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7,fr;q=0.6",
}
RESULT_RANGE_PATTERN = re.compile(
    r"Displaying\s+(\d[\d,]*)\s+to\s+(\d[\d,]*)\s+of\s+"
    r"(\d[\d,]*)\s+matching\s+jobs",
    re.IGNORECASE,
)
JOB_PATH_PATTERN = re.compile(
    r"/(?:global-en|emea-en)/jobs/([A-Za-z0-9]+)/[^/?#]+/?$",
    re.IGNORECASE,
)
SWITZERLAND_PATTERN = re.compile(r"\bSwitzerland\b", re.IGNORECASE)

PageFetcher = Callable[[str], ScraplingResponse]


class CognizantSwitzerlandParseError(DirectCompanyRequestError):
    pass


class CognizantSwitzerlandJobsParser:
    """Collect Cognizant vacancies from the official Switzerland search."""

    parser_id = "cognizant_switzerland"

    def __init__(
        self,
        *,
        base_url: str = COGNIZANT_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        fetch_page: PageFetcher | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(8, max(1, detail_workers))
        self.fetch_page = fetch_page or self._fetch_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            records, pages_fetched, total = self.collect_listing_records()
            self.enrich_records(records)
        except CognizantSwitzerlandParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError("Cognizant Switzerland vacancy request failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_cognizant_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Cognizant Switzerland vacancies from "
                f"{total} catalog records across {pages_fetched} page requests"
            ),
        )

    def _fetch_with_scrapling(self, url: str) -> ScraplingResponse:
        response = Fetcher.get(
            url,
            headers={**COGNIZANT_HEADERS, "Referer": self.base_url},
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        status = int(getattr(response, "status", 0) or 0)
        if status >= 400:
            raise CognizantSwitzerlandParseError(f"Cognizant Careers returned HTTP {status}")
        return response

    def listing_url(self, *, page_number: int) -> str:
        if page_number <= 1:
            return self.base_url
        return str(httpx.URL(self.base_url).copy_merge_params({"page": str(page_number)}))

    def collect_listing_records(
        self,
    ) -> tuple[list[dict[str, Any]], int, int]:
        pages_fetched = 0
        last_unique = 0
        last_total = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_url = self.listing_url(page_number=1)
            first_records, first_metadata = parse_listing_page(
                self.fetch_page(first_url),
                page_url=first_url,
            )
            pages_fetched += 1
            expected_total = first_metadata["total"]
            last_total = expected_total
            if expected_total == 0:
                return [], pages_fetched, 0

            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if page_size <= 0 or first_metadata["start"] != 1:
                raise CognizantSwitzerlandParseError("Cognizant listing is missing its page size")
            required_pages = ceil(expected_total / page_size)
            if required_pages > self.max_pages:
                raise CognizantSwitzerlandParseError(
                    f"Cognizant Switzerland exposes {required_pages} pages, "
                    f"above the configured limit of {self.max_pages}"
                )

            page_results = [(1, first_records)]
            catalog_changed = False
            for page_number in range(2, required_pages + 1):
                page_url = self.listing_url(page_number=page_number)
                records, metadata = parse_listing_page(
                    self.fetch_page(page_url),
                    page_url=page_url,
                )
                pages_fetched += 1
                expected_start = ((page_number - 1) * page_size) + 1
                expected_end = min(page_number * page_size, expected_total)
                if (
                    metadata["total"] != expected_total
                    or metadata["start"] != expected_start
                    or metadata["end"] != expected_end
                ):
                    catalog_changed = True
                    break
                page_results.append((page_number, records))

            records_by_id: dict[str, dict[str, Any]] = {}
            if not catalog_changed:
                for page_number, page_records in page_results:
                    for record in page_records:
                        if record["id"] in records_by_id:
                            catalog_changed = True
                            break
                        normalized = dict(record)
                        normalized["listing_page"] = page_number
                        normalized["listing_pass"] = catalog_pass
                        normalized["total_available"] = expected_total
                        records_by_id[record["id"]] = normalized
                    if catalog_changed:
                        break

            last_unique = len(records_by_id)
            if not catalog_changed and last_unique == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total

        raise CognizantSwitzerlandParseError(
            f"Cognizant Switzerland yielded only {last_unique} unique vacancies "
            f"of {last_total} after {self.max_catalog_passes} catalog passes"
        )

    def enrich_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                return record, parse_detail_page(
                    self.fetch_page(record["url"]),
                    page_url=record["url"],
                    expected_job_id=record["id"],
                )
            except Exception as exc:  # noqa: BLE001
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
            title=(optional_text(detail.get("title")) or optional_text(record.get("title"))),
            company=(optional_text(detail.get("company")) or "Cognizant Technology Solutions AG"),
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=optional_text(detail.get("employment_type")),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_page(
    page: ScraplingResponse,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    range_text = selector_text(page, "main p.job-count")
    match = RESULT_RANGE_PATTERN.search(range_text or "")
    if not match:
        raise CognizantSwitzerlandParseError("Cognizant listing page is missing its result range")
    start, end, total = (int(value.replace(",", "")) for value in match.groups())

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("main .card-job[data-id]"):
        card_id = optional_text(card.css("::attr(data-id)").get())
        path = optional_text(card.css("h2.card-title a::attr(href)").get())
        title = selector_text(card, "h2.card-title")
        metadata = normalized_unique_texts(card.css("ul.job-meta li::text").getall())
        detail_url = urljoin(page_url, path) if path else None
        path_id = extract_job_id(detail_url)
        location = metadata[0] if metadata else None
        category = metadata[1] if len(metadata) > 1 else None
        if (
            not card_id
            or card_id != path_id
            or not title
            or not detail_url
            or not location
            or not SWITZERLAND_PATTERN.search(location)
        ):
            raise CognizantSwitzerlandParseError(
                "Cognizant listing contains an incomplete or non-Swiss vacancy"
            )
        if card_id in seen_ids:
            raise CognizantSwitzerlandParseError("Cognizant listing contains duplicate vacancy IDs")
        seen_ids.add(card_id)
        records.append(
            {
                "id": card_id,
                "title": title,
                "location": location,
                "category": category,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    expected_count = 0 if total == 0 else end - start + 1
    if len(records) != expected_count:
        raise CognizantSwitzerlandParseError(
            f"Cognizant listed {len(records)} vacancies for a range of {expected_count} records"
        )
    return records, {"start": start, "end": end, "total": total}


def parse_detail_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    schemas = list(extract_job_posting_schemas(page))
    if len(schemas) != 1:
        raise CognizantSwitzerlandParseError("Cognizant detail page is missing its JobPosting data")
    schema = schemas[0]
    schema_id = optional_text(schema.get("identifier"))
    schema_url = optional_text(schema.get("url")) or optional_text(schema.get("mainEntityOfPage"))
    url_id = extract_job_id(schema_url)
    page_id = extract_job_id(page_url)
    if (
        not schema_id
        or schema_id != url_id
        or schema_id != page_id
        or (expected_job_id and schema_id != expected_job_id)
    ):
        raise CognizantSwitzerlandParseError("Cognizant detail page returned a different vacancy")

    title = optional_text(schema.get("title"))
    description = html_to_text(optional_text(schema.get("description")) or "")
    swiss_locations = extract_swiss_locations(schema.get("jobLocation"))
    if not title or not description or not swiss_locations:
        raise CognizantSwitzerlandParseError(
            "Cognizant detail page contains an incomplete or non-Swiss vacancy"
        )

    apply_url = optional_text(page.css('a[href*="jobapply.ftl"]::attr(href)').get())
    if apply_url:
        apply_id = optional_text(parse_qs(urlsplit(apply_url).query).get("job", [None])[0])
        if apply_id != schema_id:
            raise CognizantSwitzerlandParseError(
                "Cognizant detail page contains a mismatched apply link"
            )

    organization = schema.get("hiringOrganization")
    organization = organization if isinstance(organization, dict) else {}
    return {
        "id": schema_id,
        "title": title,
        "company": optional_text(organization.get("name")) or "Cognizant",
        "location": "; ".join(swiss_locations),
        "apply_url": apply_url,
        "posted_at": optional_text(schema.get("datePosted")),
        "employment_type": normalize_employment_type(schema.get("employmentType")),
        "description": description,
        "industry": optional_text(schema.get("industry")),
        "schema": schema,
    }


def extract_job_posting_schemas(
    page: ScraplingResponse,
) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            if candidate.get("@type") == "JobPosting":
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_swiss_locations(value: Any) -> list[str]:
    locations = value if isinstance(value, list) else [value]
    labels: list[str] = []
    for item in locations:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        address = address if isinstance(address, dict) else {}
        country = optional_text(address.get("addressCountry"))
        if country not in {"Switzerland", "CH", "CHE"}:
            continue
        parts: list[str] = []
        for part in (
            item.get("name"),
            address.get("addressRegion"),
            "Switzerland",
        ):
            text = optional_text(part)
            if text and text not in parts:
                parts.append(text)
        label = ", ".join(parts)
        if label and label not in labels:
            labels.append(label)
    return labels


def normalize_employment_type(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    return text.replace("_", "-").capitalize()


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1) if match else None


def deduplicate_cognizant_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = extract_job_id(job.url)
        key = job_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


def normalized_unique_texts(values: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        text = optional_text(value)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None
