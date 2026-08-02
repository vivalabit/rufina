from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

DIE_POST_JOBS_BASE_URL = "https://job.post.ch/search?locale=en_US"
DIE_POST_LOCALES = ("en_US", "de_DE", "fr_FR", "it_IT")
DIE_POST_RESULTS_PER_PAGE = 10
DIE_POST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8,fr;q=0.7,it;q=0.6",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class DiePostParseError(DirectCompanyRequestError):
    pass


class DiePostJobsParser:
    """Collect the complete multilingual catalog from Swiss Post's public API."""

    parser_id = "die_post"

    def __init__(
        self,
        *,
        base_url: str = DIE_POST_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 6,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.origin}/services/recruiting/v1/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        records_by_locale: dict[str, list[dict[str, Any]]] = {}
        listing_pages = 0

        try:
            with httpx.Client(
                headers={
                    **DIE_POST_HEADERS,
                    "Origin": self.origin,
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                for locale in DIE_POST_LOCALES:
                    records, pages = self.collect_locale_records(client, locale=locale)
                    records_by_locale[locale] = records
                    listing_pages += pages

                records = merge_localized_records(records_by_locale)
                self.enrich_records(client, records)
        except DiePostParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Die Post vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Die Post vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_die_post_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Die Post vacancies across {listing_pages} "
                f"API pages in {len(DIE_POST_LOCALES)} locales"
            ),
        )

    def collect_locale_records(
        self,
        client: httpx.Client,
        *,
        locale: str,
    ) -> tuple[list[dict[str, Any]], int]:
        unique_records: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # The API sorts many vacancies by the same date without a stable secondary
        # key. Records can therefore move between its ten-item pages while a scan is
        # running. Repeat the page walk and union stable job IDs until totalJobs is met.
        for catalog_pass in range(self.max_catalog_passes):
            pass_records: list[dict[str, Any]] = []
            page_number = 0

            while True:
                response = client.post(
                    self.listing_api_url,
                    json={
                        "locale": locale,
                        "pageNumber": page_number,
                        "sortBy": "date",
                    },
                )
                pages_fetched += 1
                response.raise_for_status()
                page_total, page_records = parse_listing_payload(response.json())

                if expected_total is None:
                    expected_total = page_total
                    required_pages = max(
                        1,
                        ceil(expected_total / DIE_POST_RESULTS_PER_PAGE),
                    )
                    if required_pages > self.max_pages:
                        raise DiePostParseError(
                            f"Die Post locale {locale} exposes {required_pages} pages, "
                            f"above the configured limit of {self.max_pages}"
                        )
                elif page_total != expected_total:
                    raise DiePostParseError(
                        f"Die Post locale {locale} changed totalJobs during pagination"
                    )

                if not page_records and len(pass_records) < (expected_total or 0):
                    raise DiePostParseError(
                        f"Die Post locale {locale} page {page_number} was unexpectedly "
                        "empty"
                    )

                for record in page_records:
                    localized = dict(record)
                    localized["listing_locale"] = locale
                    localized["listing_page"] = page_number
                    localized["listing_pass"] = catalog_pass
                    localized["total_available_in_locale"] = expected_total
                    pass_records.append(localized)

                if len(pass_records) >= (expected_total or 0):
                    if len(pass_records) != (expected_total or 0):
                        raise DiePostParseError(
                            f"Die Post locale {locale} returned more records than totalJobs"
                        )
                    break

                page_number += 1
                if page_number >= self.max_pages:
                    raise DiePostParseError(
                        f"Die Post locale {locale} pagination exceeded the configured "
                        f"limit of {self.max_pages}"
                    )

            for record in pass_records:
                job_id = optional_text(record.get("id"))
                if job_id and job_id not in unique_records:
                    unique_records[job_id] = record

            if len(unique_records) >= (expected_total or 0):
                return list(unique_records.values()), pages_fetched

        raise DiePostParseError(
            f"Die Post locale {locale} yielded only {len(unique_records)} unique vacancies "
            f"of {expected_total or 0} after {self.max_catalog_passes} catalog passes"
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
            detail_url = self.build_job_url(record)
            try:
                response = client.get(detail_url, headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(response.text, page_url=str(response.url))
            except (httpx.HTTPError, DiePostParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def build_job_url(self, record: dict[str, Any]) -> str:
        brand = optional_text(record.get("brandUrl")) or "default"
        title = (
            optional_text(record.get("unifiedUrlTitle"))
            or optional_text(record.get("urlTitle"))
            or "vacancy"
        )
        job_id = optional_text(record.get("id")) or "unknown"
        locale = optional_text(record.get("display_locale")) or "en_US"
        return f"{self.origin}/{brand}/job/{title}/{job_id}-{locale}"

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        listing_url = self.build_job_url(record)
        public_url = optional_text(detail.get("canonical_url")) or listing_url

        raw = dict(record)
        raw["detail"] = detail

        locale = optional_text(record.get("display_locale")) or "en_US"
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("unifiedStandardTitle")),
            company=first_text(record.get("cust_brandCompanyJobSearch")) or "Die Post",
            location=extract_location(record),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=normalize_posted_at(record.get("unifiedStandardStart"), locale),
            employment_type=extract_workload(record),
            seniority=first_text(record.get("filter2")),
            description=optional_multiline_text(detail.get("description")),
            raw=raw,
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise DiePostParseError("Die Post jobs response must be an object")
    total = payload.get("totalJobs")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise DiePostParseError("Die Post jobs response has an invalid totalJobs")
    results = payload.get("jobSearchResult")
    if not isinstance(results, list):
        raise DiePostParseError("Die Post jobs response has invalid jobSearchResult")

    records: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("response"), dict):
            raise DiePostParseError("Die Post jobs response contains an invalid result")
        record = result["response"]
        if not optional_text(record.get("id")) or not optional_text(
            record.get("unifiedStandardTitle")
        ):
            raise DiePostParseError("Die Post jobs response contains an incomplete vacancy")
        records.append(record)
    return total, records


def merge_localized_records(
    records_by_locale: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for locale in DIE_POST_LOCALES:
        for record in records_by_locale.get(locale, []):
            job_id = optional_text(record.get("id"))
            if not job_id:
                continue
            existing = merged.get(job_id)
            if existing is None:
                primary = dict(record)
                primary["display_locale"] = locale
                primary["available_locales"] = [locale]
                merged[job_id] = primary
            elif locale not in existing["available_locales"]:
                existing["available_locales"].append(locale)

    return sorted(
        merged.values(),
        key=lambda record: normalize_posted_at(
            record.get("unifiedStandardStart"),
            optional_text(record.get("display_locale")) or "en_US",
        )
        or "",
        reverse=True,
    )


def parse_detail_html(page_html: str, *, page_url: str) -> dict[str, Any]:
    page = Selector(page_html)
    candidates = [
        *page.css(".jobDisplay .jobColumnTwo span.rtltextaligneligible").getall(),
        *page.css('#search-wrapper span[itemprop="description"]').getall(),
    ]
    if not candidates:
        candidates = page.css(".jobDisplay .job span.rtltextaligneligible").getall()
    descriptions = [text for value in candidates if (text := html_to_text(value))]
    description = max(descriptions, key=len, default=None)
    if not description:
        raise DiePostParseError("Die Post job description was not found")

    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    apply_path = optional_text(page.css("a.unify-apply-now::attr(href)").get())
    return {
        "canonical_url": urljoin(page_url, canonical) if canonical else page_url,
        "apply_url": urljoin(page_url, apply_path) if apply_path else None,
        "description": description,
    }


def extract_location(record: dict[str, Any]) -> str | None:
    raw_locations = record.get("jobLocationShort")
    if not isinstance(raw_locations, Sequence) or isinstance(raw_locations, (str, bytes)):
        return None
    locations: list[str] = []
    for value in raw_locations:
        text = optional_text(value)
        if not text:
            continue
        parts = [part.strip() for part in text.split("|") if part.strip()]
        if not parts:
            continue
        location = parts[0]
        country_code = parts[-1]
        if country_code and country_code != "CHE":
            location = f"{location} {country_code}"
        if location not in locations:
            locations.append(location)
    return ", ".join(locations) or None


def extract_workload(record: dict[str, Any]) -> str | None:
    minimum = first_int(record.get("cust_WorkingTimeMin"))
    maximum = first_int(record.get("cust_WorkingTimeMax"))
    if minimum is None and maximum is None:
        return None
    minimum = minimum or 0
    maximum = maximum if maximum is not None else 100
    if minimum == 0 or minimum == maximum:
        return f"{maximum}%"
    return f"{minimum}–{maximum}%"


def normalize_posted_at(value: Any, locale: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    formats = (
        ("%m/%d/%y", "%m/%d/%Y")
        if locale == "en_US"
        else ("%d.%m.%y", "%d.%m.%Y", "%d/%m/%y", "%d/%m/%Y")
    )
    for date_format in formats:
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def deduplicate_die_post_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def first_text(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return next((text for item in value if (text := optional_text(item))), None)
    return optional_text(value)


def first_int(value: Any) -> int | None:
    text = first_text(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def html_to_text(value: str) -> str | None:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None
