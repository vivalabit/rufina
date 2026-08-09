from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ETH_ZURICH_JOBS_BASE_URL = "https://jobs.ethz.ch/"
ETH_ZURICH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
RESULT_COUNT_PATTERN = re.compile(
    r"(\d[\d'’.,]*)\s+(?:offene\s+Stellen|open\s+(?:positions|jobs))",
    re.IGNORECASE,
)
JOB_PATH_PATTERN = re.compile(r"/job/view/([^/?#]+)")
EMPLOYMENT_RANGE_PATTERN = re.compile(r"\b(\d{1,3})\s*%?\s*[-–]\s*(\d{1,3})\s*%")
EMPLOYMENT_PERCENT_PATTERN = re.compile(r"(?:^|\s)(\d{1,3})\s*%")


class EthZurichParseError(DirectCompanyRequestError):
    pass


class EthZurichJobsParser:
    """Collect the complete catalog published on the ETH Zürich jobs site."""

    parser_id = "eth_zurich"

    def __init__(
        self,
        *,
        base_url: str = ETH_ZURICH_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=ETH_ZURICH_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                )
                self.enrich_records(client, records)
        except EthZurichParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("ETH Zürich vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("ETH Zürich vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_eth_zurich_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} ETH Zürich vacancies from the full catalog page"),
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
            try:
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    expected_title=optional_text(record.get("title")),
                )
            except (httpx.HTTPError, EthZurichParseError, ValueError) as exc:
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
            company="ETH Zürich",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=optional_text(record.get("url")),
            apply_url=optional_text(detail.get("apply_url")),
            posted_at=normalize_date(record.get("posted_at")),
            employment_type=(
                optional_text(detail.get("workload"))
                or optional_text(record.get("workload"))
                or extract_employment_type(title)
            ),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    if not page.css("ul#w1").get():
        raise EthZurichParseError("ETH Zürich listing page is missing its vacancy catalog")

    expected_count = extract_result_count(page)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("ul#w1 > div[data-key]"):
        path = optional_text(card.css("a.job-ad__item__link::attr(href)").get())
        detail_url = urljoin(page_url, path) if path else None
        job_id = extract_job_id(detail_url)
        title = optional_text(" ".join(card.css("h3.job-ad__item__title::text").getall()))
        details = optional_text(" ".join(card.css("div.job-ad__item__details::text").getall()))
        metadata = optional_text(" ".join(card.css("div.job-ad__item__company::text").getall()))
        if not job_id or not title or not details or not metadata or not detail_url:
            raise EthZurichParseError("ETH Zürich listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise EthZurichParseError("ETH Zürich listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)

        posted_at, separator, department = metadata.partition("|")
        if not separator or not optional_text(posted_at) or not optional_text(department):
            raise EthZurichParseError("ETH Zürich listing contains incomplete vacancy metadata")
        workload, location, contract_type = parse_job_details(details)
        records.append(
            {
                "id": job_id,
                "listing_id": optional_text(card.attrib.get("data-key")),
                "title": title,
                "workload": workload,
                "location": location,
                "contract_type": contract_type,
                "posted_at": optional_text(posted_at),
                "department": optional_text(department),
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )

    if len(records) != expected_count:
        raise EthZurichParseError(
            f"ETH Zürich listed {len(records)} vacancies but declared "
            f"{expected_count} open positions"
        )
    return records


def extract_result_count(page: Selector) -> int:
    candidates = normalized_texts(page.css("section.intro h2::text").getall())
    for candidate in candidates:
        match = RESULT_COUNT_PATTERN.search(candidate)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                return int(digits)
    raise EthZurichParseError("ETH Zürich listing page is missing its vacancy count")


def parse_job_details(value: str) -> tuple[str | None, str | None, str | None]:
    parts = [part for item in value.split(",") if (part := optional_text(item))]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    if len(parts) < 3:
        raise EthZurichParseError("ETH Zürich listing contains invalid vacancy details")
    return parts[0], ", ".join(parts[1:-1]), parts[-1]


def parse_detail_html(
    page_html: str,
    *,
    expected_title: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    section = page.css('section.description[aria-labelledby="job-title"]')
    if not section.get():
        raise EthZurichParseError("ETH Zürich detail page is missing its vacancy content")

    title = optional_text(section.css("h1#job-title::text").get())
    details = optional_text(section.css("h4::attr(aria-label)").get())
    apply_url = optional_text(page.css("a.application__button--link::attr(href)").get())
    if not title or not details or not apply_url:
        raise EthZurichParseError("ETH Zürich detail page contains an incomplete vacancy")
    if expected_title and title.casefold() != expected_title.casefold():
        raise EthZurichParseError("ETH Zürich detail page returned a different vacancy")

    workload, location, contract_type = parse_job_details(details)
    sections: list[str] = []
    for node in section.css('div[role="region"]'):
        section_html = node.get()
        text = html_to_text(section_html) if section_html else None
        if not text:
            continue
        label = optional_text(node.attrib.get("aria-label"))
        if label and not text.casefold().startswith(label.casefold()):
            text = f"{label}\n\n{text}"
        sections.append(text)
    description_parts = list(dict.fromkeys(sections))
    if not description_parts:
        raise EthZurichParseError("ETH Zürich detail page is missing its vacancy description")

    workplace = optional_text(page.css('iframe[title^="Workplace -"]::attr(title)').get())
    return {
        "title": title,
        "workload": workload,
        "location": location,
        "contract_type": contract_type,
        "workplace": strip_prefix(workplace, "Workplace -"),
        "apply_url": apply_url,
        "description": "\n\n".join(description_parts),
    }


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1) if match else None


def extract_employment_type(title: str | None) -> str | None:
    if not title:
        return None
    range_match = EMPLOYMENT_RANGE_PATTERN.search(title)
    if range_match:
        return f"{range_match.group(1)}%-{range_match.group(2)}%"
    percent_match = EMPLOYMENT_PERCENT_PATTERN.search(title)
    return f"{percent_match.group(1)}%" if percent_match else None


def deduplicate_eth_zurich_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    for date_format in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def strip_prefix(value: Any, prefix: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if text.casefold().startswith(prefix.casefold()):
        return optional_text(text[len(prefix) :])
    return text


def normalized_texts(values: Iterable[Any]) -> list[str]:
    return [text for value in values if (text := optional_text(value))]


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
