from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

HUBER_SUHNER_JOBS_URL = "https://recruiting.hubersuhner.com/Jobs/All"
HUBER_SUHNER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
VACANCY_PATH_PATTERN = re.compile(r"/Vacancies/(\d+)/Description/\d+", re.IGNORECASE)
POSTED_AT_PATTERN = re.compile(
    r"Online\s+seit:\s*(\d{2})([./])(\d{2})\2(\d{4})",
    re.IGNORECASE,
)
JOB_NUMBER_PATTERN = re.compile(r"Stellennummer:\s*(\d+)", re.IGNORECASE)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%")


class HuberSuhnerSwitzerlandParseError(DirectCompanyRequestError):
    pass


class HuberSuhnerSwitzerlandJobsParser:
    """Collect the complete Swiss subset of Huber+Suhner's Umantis catalog."""

    parser_id = "huber_suhner_switzerland"

    def __init__(
        self,
        *,
        base_url: str = HUBER_SUHNER_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=HUBER_SUHNER_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, catalog_count = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except HuberSuhnerSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Huber+Suhner Umantis request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Huber+Suhner vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_huber_suhner_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Huber+Suhner Switzerland vacancies from "
                f"{catalog_count} global catalog records across {pages_fetched} "
                "Umantis pages"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        swiss_records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()
        expected_swiss_locations: set[str] | None = None
        page_url: str | None = self.base_url
        pages_fetched = 0
        catalog_count = 0

        while page_url is not None:
            canonical_page_url = page_url.split("#", 1)[0]
            if canonical_page_url in seen_pages:
                raise HuberSuhnerSwitzerlandParseError(
                    "Huber+Suhner Umantis pagination contains a cycle"
                )
            if pages_fetched >= self.max_pages:
                raise HuberSuhnerSwitzerlandParseError(
                    "Huber+Suhner Umantis catalog exceeds the configured limit of "
                    f"{self.max_pages} pages"
                )
            seen_pages.add(canonical_page_url)

            response = client.get(page_url)
            response.raise_for_status()
            pages_fetched += 1
            page_records, next_path, swiss_locations = parse_listing_html(
                response.text,
                page_url=str(response.url),
                page_number=pages_fetched,
            )
            if expected_swiss_locations is None:
                expected_swiss_locations = swiss_locations
            elif swiss_locations != expected_swiss_locations:
                raise HuberSuhnerSwitzerlandParseError(
                    "Huber+Suhner changed its Swiss location catalog during pagination"
                )

            for record in page_records:
                job_id = str(record["id"])
                if job_id in seen_ids:
                    raise HuberSuhnerSwitzerlandParseError(
                        f"Huber+Suhner Umantis catalog repeats vacancy {job_id}"
                    )
                seen_ids.add(job_id)
                catalog_count += 1
                if is_swiss_location(record.get("location"), swiss_locations):
                    record["swiss_location_catalog"] = sorted(swiss_locations)
                    swiss_records.append(record)

            page_url = urljoin(str(response.url), next_path) if next_path else None

        return swiss_records, pages_fetched, catalog_count

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
                response = client.get(
                    str(record["url"]),
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_title=optional_text(record.get("title")),
                    swiss_locations=set(record["swiss_location_catalog"]),
                )
            except (
                httpx.HTTPError,
                HuberSuhnerSwitzerlandParseError,
                ValueError,
            ) as exc:
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
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="Huber+Suhner",
            location=(
                optional_text(detail.get("location"))
                or optional_text(record.get("location"))
            ),
            url=optional_text(record.get("url")),
            apply_url=optional_text(detail.get("apply_url")),
            posted_at=optional_text(record.get("posted_at")),
            employment_type=join_unique(
                optional_text(detail.get("workload")),
                optional_text(detail.get("contract_type")),
            ),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], str | None, set[str]]:
    page = Selector(page_html)
    swiss_locations = extract_swiss_locations(page)
    page_size_text = optional_text(
        page.css("[data-one-item-chunk]::attr(data-one-item-chunk)").get()
    )
    if not page_size_text or not page_size_text.isdigit() or int(page_size_text) < 1:
        raise HuberSuhnerSwitzerlandParseError(
            "Huber+Suhner Umantis page is missing its catalog page size"
        )
    page_size = int(page_size_text)
    next_path = optional_text(
        page.css("[data-pagination-next-href]::attr(data-pagination-next-href)").get()
    )
    table = page.css("table.tableaslist").get()
    cards = page.css('a.HSTableLinkSubTitle[href*="/Vacancies/"]')
    if not table or len(cards) > page_size or (next_path and not cards):
        raise HuberSuhnerSwitzerlandParseError(
            "Huber+Suhner Umantis page is missing its vacancy catalog"
        )
    # On the last page Umantis may emit a stale "next" link that points back
    # to page one. A short page is the authoritative end-of-catalog signal.
    if len(cards) < page_size:
        next_path = None

    records: list[dict[str, Any]] = []
    for link in cards:
        path = optional_text(link.attrib.get("href"))
        title = optional_text(" ".join(link.css("::text").getall()))
        job_id = extract_job_id(path)
        row = link.xpath("ancestor::tr[1]")
        row_text = optional_text(" ".join(row.css("::text").getall()))
        location = selector_text(row, "span.tableaslist_element_1152495")
        posted_at = extract_posted_at(row_text)
        listed_job_id = extract_listed_job_id(row_text)
        if (
            not path
            or not title
            or not job_id
            or not row.get()
            or not location
            or not posted_at
            or listed_job_id != job_id
        ):
            raise HuberSuhnerSwitzerlandParseError(
                "Huber+Suhner Umantis listing contains an incomplete vacancy"
            )

        records.append(
            {
                "id": job_id,
                "title": title,
                "location": strip_pipe_prefix(location),
                "posted_at": posted_at,
                "url": urljoin(page_url, path),
                "listing_page": page_number,
                "listing_page_url": page_url,
            }
        )
    return records, next_path, swiss_locations


def extract_swiss_locations(page: Selector) -> set[str]:
    locations: set[str] = set()
    in_switzerland = False
    for option in page.css('select[name="searchSkill1004"] option'):
        label = optional_text(" ".join(option.css("::text").getall()))
        if not label:
            continue
        if label.startswith(">"):
            if in_switzerland:
                location = optional_text(label.removeprefix(">"))
                if location:
                    locations.add(location)
            continue
        if in_switzerland:
            break
        in_switzerland = label.casefold() in {"schweiz", "switzerland", "suisse"}
    if not locations:
        raise HuberSuhnerSwitzerlandParseError(
            "Huber+Suhner Umantis page is missing its Swiss location filter"
        )
    return locations


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_title: str | None,
    swiss_locations: set[str],
) -> dict[str, Any]:
    page = Selector(page_html)
    title = selector_text(page, "section.section article h1")
    apply_path = optional_text(
        page.css('a[href*="/Application/CheckLogin/"]::attr(href)').get()
    ) or external_apply_path(page)
    description_html = page.css("main.section__main").get()
    if not title or not apply_path or not description_html:
        raise HuberSuhnerSwitzerlandParseError(
            "Huber+Suhner Umantis detail page is incomplete"
        )
    if expected_title and title.casefold() != expected_title.casefold():
        raise HuberSuhnerSwitzerlandParseError(
            "Huber+Suhner Umantis detail page returned a different vacancy"
        )

    metadata = [
        value
        for value in (
            optional_text(item)
            for item in page.css("p.section__header__subtitle span::text").getall()
        )
        if value
    ]
    location = next(
        (value for value in metadata if is_swiss_location(value, swiss_locations)),
        None,
    )
    workload = next((value for value in metadata if WORKLOAD_PATTERN.search(value)), None)
    contract_type = next(
        (
            value
            for value in metadata
            if value != location
            and value != workload
            and value.casefold() not in {"m/w/d", "f/m/d", "w/m/d"}
        ),
        None,
    )
    if not location:
        raise HuberSuhnerSwitzerlandParseError(
            "Huber+Suhner Umantis detail page has no Swiss location"
        )

    description = remove_standalone_line(html_to_text(description_html), "Jetzt bewerben")
    if not description:
        raise HuberSuhnerSwitzerlandParseError(
            "Huber+Suhner Umantis detail page has no vacancy description"
        )
    return {
        "title": title,
        "location": location,
        "workload": workload,
        "contract_type": contract_type,
        "apply_url": urljoin(page_url, apply_path),
        "description": description,
    }


def external_apply_path(page: Selector) -> str | None:
    for link in page.css("main.section__main a[href]"):
        label = optional_text(" ".join(link.css("::text").getall()))
        path = optional_text(link.attrib.get("href"))
        if label and label.casefold() == "jetzt bewerben" and path:
            return path
    return None


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = VACANCY_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1) if match else None


def extract_posted_at(value: str | None) -> str | None:
    match = POSTED_AT_PATTERN.search(value or "")
    if not match:
        return None
    first, separator, second, year_text = match.groups()
    if separator == ".":
        day, month = int(first), int(second)
    else:
        month, day = int(first), int(second)
    year = int(year_text)
    return date(year, month, day).isoformat()


def extract_listed_job_id(value: str | None) -> str | None:
    match = JOB_NUMBER_PATTERN.search(value or "")
    return match.group(1) if match else None


def is_swiss_location(value: Any, swiss_locations: set[str]) -> bool:
    location = optional_text(value)
    if not location:
        return False
    normalized = location.casefold()
    return any(item.casefold() in normalized for item in swiss_locations)


def strip_pipe_prefix(value: str) -> str:
    return value.lstrip("|\xa0 ").strip()


def deduplicate_huber_suhner_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall())) or optional_text(
        " ".join(selector.css(f"{css}::text").getall())
    )


def join_unique(*values: str | None) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def remove_standalone_line(value: str | None, line: str) -> str | None:
    if not value:
        return None
    target = optional_text(line)
    filtered = [item for item in value.splitlines() if optional_text(item) != target]
    return optional_multiline_text("\n".join(filtered))


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
