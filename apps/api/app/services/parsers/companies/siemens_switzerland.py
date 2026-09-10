from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

SIEMENS_SWITZERLAND_JOBS_BASE_URL = (
    "https://jobs.siemens.com/de_DE/externaljobs/SearchJobs/"
    "?42386=%5B812129%5D&42386_format=17546&listFilterMode=1"
    "&folderRecordsPerPage=6"
)
SIEMENS_SWITZERLAND_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
RESULT_RANGE_PATTERN = re.compile(
    r"(\d+)\s*-\s*(\d+)\s*(?:von|of)\s*(\d+)\s*(?:Ergebnisse|results)",
    re.IGNORECASE,
)
TOTAL_PATTERN = re.compile(r"(\d+)\s*(?:Ergebnisse|results)", re.IGNORECASE)
JOB_DETAIL_PATTERN = re.compile(r"/JobDetail/(\d+)/?$", re.IGNORECASE)
EMPLOYMENT_RANGE_PATTERN = re.compile(r"\b(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%")
EMPLOYMENT_PERCENT_PATTERN = re.compile(r"\b(\d{1,3})\s*%")


class SiemensSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SiemensSwitzerlandJobsParser:
    """Collect the complete Siemens Switzerland Avature catalog."""

    parser_id = "siemens_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SIEMENS_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
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
        try:
            with CareerHttpClient(
                headers={**SIEMENS_SWITZERLAND_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SiemensSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Siemens Schweiz vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Siemens Schweiz vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_siemens_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Siemens Schweiz vacancies from {total} "
                f"catalog records across {pages_fetched} page requests"
            ),
        )

    def listing_url(self, *, offset: int) -> str:
        params = {"folderOffset": str(offset)} if offset else {}
        return str(httpx.URL(self.base_url).copy_merge_params(params))

    def fetch_listing_page(
        self,
        client: CareerHttpClient,
        *,
        offset: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        response = client.get(self.listing_url(offset=offset))
        response.raise_for_status()
        records, metadata = parse_listing_html(response.text, page_url=str(response.url))
        expected_start = offset + 1 if metadata["total"] else 0
        if metadata["start"] != expected_start:
            raise SiemensSwitzerlandParseError(
                "Siemens Schweiz pagination returned an unexpected result range"
            )
        return records, metadata

    def collect_listing_records(
        self,
        client: CareerHttpClient,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # Offset pages can move while requisitions are published. Repeat the walk
        # and union stable Avature job IDs when one pass contains overlap.
        for catalog_pass in range(self.max_catalog_passes):
            first_records, first_metadata = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            total = first_metadata["total"]
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise SiemensSwitzerlandParseError(
                    "Siemens Schweiz catalog changed its result count during pagination"
                )
            if total == 0:
                return [], pages_fetched, 0

            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if page_size <= 0:
                raise SiemensSwitzerlandParseError(
                    "Siemens Schweiz listing is missing its page size"
                )
            required_pages = ceil(total / page_size)
            if required_pages > self.max_pages:
                raise SiemensSwitzerlandParseError(
                    f"Siemens Schweiz exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            page_results = [(0, first_records)]
            for offset in range(page_size, total, page_size):
                records, metadata = self.fetch_listing_page(client, offset=offset)
                pages_fetched += 1
                if metadata["total"] != expected_total:
                    raise SiemensSwitzerlandParseError(
                        "Siemens Schweiz catalog changed its result count during pagination"
                    )
                expected_end = min(offset + page_size, total)
                if metadata["end"] != expected_end:
                    raise SiemensSwitzerlandParseError(
                        "Siemens Schweiz pagination returned an unexpected result range"
                    )
                page_results.append((offset, records))

            for offset, page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise SiemensSwitzerlandParseError(
                    "Siemens Schweiz catalog changed while pages were collected"
                )

        raise SiemensSwitzerlandParseError(
            f"Siemens Schweiz returned {len(records_by_id)} unique vacancies but "
            f"declared {expected_total or 0}"
        )

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
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, SiemensSwitzerlandParseError, ValueError) as exc:
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
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company=optional_text(detail.get("company")) or "Siemens Schweiz AG",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=optional_text(record.get("url")),
            apply_url=optional_text(detail.get("apply_url")),
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(
                extract_employment_type(title)
                or optional_text(detail.get("employment_type"))
            ),
            seniority=optional_text(detail.get("seniority")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    page = Selector(page_html)
    legend = page.css(".list-controls--top .list-controls__text__legend")
    if not legend.get():
        raise SiemensSwitzerlandParseError(
            "Siemens Schweiz listing page is missing its search results"
        )
    legend_html = legend.get()
    legend_text = html_to_text(legend_html) if legend_html else None
    match = RESULT_RANGE_PATTERN.search(legend_text or "")
    if match:
        start, end, total = (int(value) for value in match.groups())
    else:
        aria_label = optional_text(legend.attrib.get("aria-label"))
        total_match = TOTAL_PATTERN.search(aria_label or "")
        if not total_match or int(total_match.group(1)) != 0:
            raise SiemensSwitzerlandParseError(
                "Siemens Schweiz listing page is missing its result range"
            )
        start = end = total = 0

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("article.article--result"):
        path = optional_text(card.css('h3 a[href*="/JobDetail/"]::attr(href)').get())
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        title = selector_text(card, 'h3 a[href*="/JobDetail/"]')
        location = selector_text(card, ".list-item-location")
        family = selector_text(card, ".list-item-family")
        listed_id = extract_numeric_text(selector_text(card, ".list-item-jobId"))
        if not detail_url or not job_id or not title or not location or not family:
            raise SiemensSwitzerlandParseError(
                "Siemens Schweiz listing contains an incomplete vacancy"
            )
        if listed_id and listed_id != job_id:
            raise SiemensSwitzerlandParseError(
                "Siemens Schweiz listing contains mismatched vacancy IDs"
            )
        if job_id in seen_ids:
            raise SiemensSwitzerlandParseError(
                "Siemens Schweiz listing contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": location,
                "family": family,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    expected_count = max(0, end - start + 1) if total else 0
    if len(records) != expected_count:
        raise SiemensSwitzerlandParseError(
            f"Siemens Schweiz listed {len(records)} vacancies for a range of "
            f"{expected_count} records"
        )
    return records, {"start": start, "end": end, "total": total}


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    title = selector_text(page, ".section__header__text__title")
    details_articles = page.css("article.article--details")
    if not title or len(details_articles) < 2:
        raise SiemensSwitzerlandParseError(
            "Siemens Schweiz detail page is missing its vacancy content"
        )

    fields: dict[str, str] = {}
    for field in details_articles[0].css(".article__content__view__field"):
        label = selector_text(field, ".article__content__view__field__label")
        value = selector_text(field, ".article__content__view__field__value")
        if label and value:
            location_items = normalized_texts(
                field.css(".list--locations .list__item::text").getall()
            )
            if location_items:
                value = "; ".join(location_items)
            fields[label.casefold().rstrip(":")] = value

    description_html = details_articles[1].css(".job-section#youtube_link").get()
    if not description_html:
        description_html = details_articles[1].css(".article__content").get()
    description = html_to_text(description_html) if description_html else None
    apply_path = optional_text(
        page.css(
            'article.article--actions a.button--hero[href*="ApplicationMethods"]::attr(href)'
        ).get()
    )
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    detail_job_id = (
        extract_numeric_text(fields.get("job id"))
        or extract_job_id(page_url)
        or extract_job_id(apply_url)
    )
    if not description or not apply_url or not detail_job_id:
        raise SiemensSwitzerlandParseError(
            "Siemens Schweiz detail page contains an incomplete vacancy"
        )
    if expected_job_id and detail_job_id != expected_job_id:
        raise SiemensSwitzerlandParseError(
            "Siemens Schweiz detail page returned a different vacancy"
        )

    return {
        "id": detail_job_id,
        "title": title,
        "company": fields.get("unternehmen") or fields.get("company"),
        "location": fields.get("standort(e)") or fields.get("location(s)"),
        "apply_url": apply_url,
        "posted_at": normalize_date(
            fields.get("veröffentlicht seit") or fields.get("published since")
        ),
        "organization": fields.get("organization"),
        "family": fields.get("tätigkeitsbereich") or fields.get("job family"),
        "seniority": fields.get("erfahrungsniveau") or fields.get("experience level"),
        "employment_type": fields.get("beschäftigungsart") or fields.get("employment type"),
        "work_model": fields.get("arbeitsmodell") or fields.get("work model"),
        "contract_type": fields.get("vertragsart") or fields.get("contract type"),
        "description": description,
    }


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_DETAIL_PATTERN.search(parts.path)
    if match:
        return match.group(1)
    values = parse_qs(parts.query).get("folderId")
    return extract_numeric_text(values[0]) if values else None


def extract_numeric_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = re.search(r"\b(\d+)\b", text)
    return match.group(1) if match else None


def extract_employment_type(title: str | None) -> str | None:
    if not title:
        return None
    range_match = EMPLOYMENT_RANGE_PATTERN.search(title)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}%"
    percent_match = EMPLOYMENT_PERCENT_PATTERN.search(title)
    return f"{percent_match.group(1)}%" if percent_match else None


def deduplicate_siemens_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or extract_job_id(job.apply_url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    for date_format in ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def selector_text(node: Any, selector: str) -> str | None:
    selected_html = node.css(selector).get()
    return html_to_text(selected_html) if selected_html else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def normalized_texts(values: Iterable[Any]) -> list[str]:
    return [text for value in values if (text := optional_text(value))]
