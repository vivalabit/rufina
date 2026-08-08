from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

DELOITTE_JOBS_BASE_URL = "https://apply.deloitte.ch/CHCareers/"
DELOITTE_RESULTS_PER_PAGE = 6
DELOITTE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,fr-CH;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
RESULT_RANGE_PATTERN = re.compile(
    r"\b(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+results?\b",
    re.IGNORECASE,
)
ZERO_RESULTS_PATTERN = re.compile(r"\b0\s+results?\b", re.IGNORECASE)
JOB_DETAIL_PATTERN = re.compile(r"/JobDetail/[^?#]*/(\d+)/?$", re.IGNORECASE)


class DeloitteParseError(DirectCompanyRequestError):
    pass


class DeloitteJobsParser:
    """Collect the complete Deloitte Switzerland Avature catalog."""

    parser_id = "deloitte"

    def __init__(
        self,
        *,
        base_url: str = DELOITTE_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
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
    def search_url(self) -> str:
        return urljoin(self.base_url, "SearchJobs/")

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=DELOITTE_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, _total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except DeloitteParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Deloitte vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Deloitte vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_deloitte_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Deloitte vacancies across {pages_fetched} catalog pages"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # Offset pages can shift while requisitions are being published. Repeat
        # the walk and union stable Avature job IDs if one pass contains overlap.
        for catalog_pass in range(self.max_catalog_passes):
            offsets = (
                list(range(0, expected_total, DELOITTE_RESULTS_PER_PAGE)) if expected_total else [0]
            )
            pass_records = 0

            for offset in offsets:
                response = client.get(
                    self.search_url,
                    params={
                        "jobRecordsPerPage": DELOITTE_RESULTS_PER_PAGE,
                        "jobOffset": offset,
                    },
                    headers={"Referer": self.base_url},
                )
                pages_fetched += 1
                response.raise_for_status()
                start, end, page_total, records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                )

                if expected_total is None:
                    expected_total = page_total
                    required_pages = max(
                        1,
                        ceil(expected_total / DELOITTE_RESULTS_PER_PAGE),
                    )
                    if required_pages > self.max_pages:
                        raise DeloitteParseError(
                            f"Deloitte exposes {required_pages} pages, above the "
                            f"configured limit of {self.max_pages}"
                        )
                    offsets.extend(
                        range(
                            DELOITTE_RESULTS_PER_PAGE,
                            expected_total,
                            DELOITTE_RESULTS_PER_PAGE,
                        )
                    )
                elif page_total != expected_total:
                    raise DeloitteParseError("Deloitte changed its vacancy total during pagination")

                expected_start = offset + 1 if expected_total else 0
                expected_end = min(offset + DELOITTE_RESULTS_PER_PAGE, expected_total)
                if start != expected_start or end != expected_end:
                    raise DeloitteParseError(
                        f"Deloitte page at offset {offset} declared an unexpected result range"
                    )
                if len(records) != max(0, expected_end - expected_start + 1):
                    raise DeloitteParseError(
                        f"Deloitte page at offset {offset} contains an unexpected vacancy count"
                    )

                pass_records += len(records)
                for record in records:
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(str(record["id"]), normalized)

            if pass_records > (expected_total or 0):
                raise DeloitteParseError("Deloitte returned more vacancies than its declared total")
            if len(records_by_id) == (expected_total or 0):
                return list(records_by_id.values()), pages_fetched, expected_total or 0
            if len(records_by_id) > (expected_total or 0):
                raise DeloitteParseError(
                    "Deloitte returned more unique vacancies than its declared total"
                )

        raise DeloitteParseError(
            f"Deloitte yielded only {len(records_by_id)} unique vacancies of "
            f"{expected_total or 0} after {self.max_catalog_passes} catalog passes"
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
            detail_url = optional_text(record.get("url"))
            if not detail_url:
                return record, None
            try:
                response = client.get(detail_url, headers={"Referer": self.search_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                )
            except (httpx.HTTPError, DeloitteParseError, ValueError) as exc:
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
        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="Deloitte",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=optional_text(detail.get("public_url")) or optional_text(record.get("url")),
            apply_url=(
                optional_text(detail.get("apply_url")) or optional_text(record.get("apply_url"))
            ),
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
            ),
            employment_type=optional_text(detail.get("workload")),
            seniority=optional_text(detail.get("seniority")),
            description=optional_multiline_text(detail.get("description")),
            raw=raw,
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[int, int, int, list[dict[str, Any]]]:
    page = Selector(page_html)
    legend = optional_text(page.css(".list-controls--top .list-controls__text__legend::text").get())
    if not legend:
        raise DeloitteParseError("Deloitte listing page is missing its result range")

    range_match = RESULT_RANGE_PATTERN.search(legend)
    if range_match:
        start, end, total = (int(value) for value in range_match.groups())
    elif ZERO_RESULTS_PATTERN.search(legend):
        start = end = total = 0
    else:
        raise DeloitteParseError("Deloitte listing page has an invalid result range")

    records: list[dict[str, Any]] = []
    for card in page.css("article.article--result"):
        detail_path = optional_text(card.css('h3 a[href*="/JobDetail/"]::attr(href)').get())
        title = selector_text(card, 'h3 a[href*="/JobDetail/"]')
        apply_path = optional_text(
            card.css('a.button--primary[href*="/Login?jobId="]::attr(href)').get()
        )
        detail_url = urljoin(page_url, detail_path) if detail_path else None
        apply_url = urljoin(page_url, apply_path) if apply_path else None
        job_id = extract_job_id(detail_url) or extract_job_id(apply_url)
        if not detail_url or not apply_url or not title or not job_id:
            raise DeloitteParseError("Deloitte listing contains an incomplete vacancy")

        subtitles = normalized_texts(
            card.css(".article__header__text__subtitle span::text").getall()
        )
        posted = subtitles[2] if len(subtitles) > 2 else None
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": subtitles[0] if subtitles else None,
                "business_line": subtitles[1] if len(subtitles) > 1 else None,
                "posted_at": normalize_date(strip_prefix(posted, "Posted:")),
                "url": detail_url,
                "apply_url": apply_url,
                "listing_page_url": page_url,
            }
        )

    return start, end, total, records


def parse_detail_html(page_html: str, *, page_url: str) -> dict[str, Any]:
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    fields: dict[str, str] = {}
    description: str | None = None

    for article in page.css("article.article--details"):
        heading = selector_text(article, "h1, h2, h3")
        normalized_heading = heading.casefold() if heading else ""
        if normalized_heading == "basic information":
            for field in article.css(".article__content__view__field"):
                label = selector_text(field, ".article__content__view__field__label")
                value = selector_text(field, ".article__content__view__field__value")
                if label and value:
                    fields[label.casefold().rstrip(":")] = value
        elif normalized_heading == "job description":
            value = article.css(".article__content__view__field__value").get()
            description = html_to_text(value) if value else None

    apply_path = optional_text(
        page.css(
            'article.article--actions a.button--primary[href*="/Login?jobId="]::attr(href)'
        ).get()
    )
    title = optional_text(schema.get("title"))
    if not title or not apply_path or not description:
        raise DeloitteParseError("Deloitte detail page is missing required vacancy data")

    return {
        "title": title,
        "public_url": page_url,
        "apply_url": urljoin(page_url, apply_path),
        "posted_at": normalize_date(schema.get("datePosted") or fields.get("date published")),
        "business_line": fields.get("business line"),
        "location": fields.get("city"),
        "seniority": fields.get("experience level"),
        "workload": fields.get("working time percentage"),
        "requisition_id": fields.get("req #"),
        "description": description,
    }


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
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


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    detail_match = JOB_DETAIL_PATTERN.search(parts.path)
    if detail_match:
        return detail_match.group(1)
    query_id = parse_qs(parts.query).get("jobId") or parse_qs(parts.query).get("jobid")
    return optional_text(query_id[0]) if query_id else None


def deduplicate_deloitte_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    for date_format in ("%Y-%m-%d", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_prefix(value: Any, prefix: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if text.casefold().startswith(prefix.casefold()):
        return optional_text(text[len(prefix) :])
    return text


def normalized_texts(values: Iterable[Any]) -> list[str]:
    return [text for value in values if (text := optional_text(value))]


def selector_text(node: Any, selector: str) -> str | None:
    selected_html = node.css(selector).get()
    return optional_text(html_to_text(selected_html)) if selected_html else None


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
