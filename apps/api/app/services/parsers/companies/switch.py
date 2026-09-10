from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SWITCH_JOBS_BASE_URL = "https://recruitingapp-2563.umantis.com/Jobs/1?lang=ger"
SWITCH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
RESULT_COUNT_PATTERN = re.compile(r"(\d[\d'’.,]*)\s+Stellen\s+gefunden", re.IGNORECASE)
VACANCY_PATH_PATTERN = re.compile(r"/Vacancies/(\d+)/Description/\d+", re.IGNORECASE)
LOCATION_SUFFIX_PATTERN = re.compile(r"\s+in\s+([^()]+?)\s*$", re.IGNORECASE)
WORKLOAD_PATTERN = re.compile(r"\b(\d{1,3}(?:\s*[-–]\s*\d{1,3})?)\s*%")


class SwitchParseError(DirectCompanyRequestError):
    pass


class SwitchJobsParser:
    """Collect Switch vacancies from its server-rendered Umantis catalog."""

    parser_id = "switch"

    def __init__(
        self,
        *,
        base_url: str = SWITCH_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport
        self.language = first_query_value(base_url, "lang")

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=SWITCH_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SwitchParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Switch Umantis request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Switch vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_switch_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Switch vacancies from {total} catalog "
                f"records across {pages_fetched} Umantis page requests"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()
        page_url: str | None = self.base_url
        expected_total: int | None = None
        pages_fetched = 0

        while page_url is not None:
            canonical_page_url = page_url.split("#", 1)[0]
            if canonical_page_url in seen_pages:
                raise SwitchParseError("Switch Umantis pagination contains a cycle")
            if pages_fetched >= self.max_pages:
                raise SwitchParseError(
                    f"Switch Umantis catalog exceeds the configured limit of {self.max_pages} pages"
                )
            seen_pages.add(canonical_page_url)

            response = client.get(page_url)
            response.raise_for_status()
            pages_fetched += 1
            page_records, page_total, next_path = parse_listing_html(
                response.text,
                page_url=str(response.url),
                page_number=pages_fetched,
                language=self.language,
            )
            if expected_total is None:
                expected_total = page_total
            elif page_total != expected_total:
                raise SwitchParseError("Switch changed its vacancy total during pagination")

            for record in page_records:
                job_id = str(record["id"])
                if job_id in seen_ids:
                    raise SwitchParseError(f"Switch Umantis catalog repeats vacancy {job_id}")
                seen_ids.add(job_id)
                records.append(record)

            page_url = urljoin(str(response.url), next_path) if next_path else None

        if len(records) != (expected_total or 0):
            raise SwitchParseError(
                f"Switch listed {len(records)} vacancies but declared "
                f"{expected_total or 0} open positions"
            )
        return records, pages_fetched, expected_total or 0

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
                    language=self.language,
                )
            except (httpx.HTTPError, SwitchParseError, ValueError) as exc:
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
        job_type = optional_text(record.get("job_type"))
        contract_type = optional_text(record.get("contract_type"))
        workload = extract_workload(title)

        return ParsedJob(
            source=self.parser_id,
            title=title,
            company="Switch",
            location=extract_location(title),
            url=optional_text(record.get("url")),
            apply_url=optional_text(detail.get("apply_url")),
            employment_type=join_unique(job_type, workload, contract_type),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    page_number: int,
    language: str | None,
) -> tuple[list[dict[str, Any]], int, str | None]:
    page = Selector(page_html)
    expected_total = extract_result_count(page)
    cards = page.css('a.HSTableLinkSubTitle[href*="/Vacancies/"]')
    if expected_total > 0 and not cards:
        raise SwitchParseError("Switch Umantis page is missing its vacancy catalog")

    records: list[dict[str, Any]] = []
    for link in cards:
        path = optional_text(link.attrib.get("href"))
        title = optional_text(" ".join(link.css("::text").getall()))
        job_id = extract_job_id(path)
        row = link.xpath("ancestor::tr[1]")
        if not path or not title or not job_id or not row.get():
            raise SwitchParseError("Switch Umantis listing contains an incomplete vacancy")

        metadata: dict[str, str] = {}
        for item in row.css("li.form_content_paragraph"):
            label = optional_text(" ".join(item.css("span.visually-hidden::text").getall()))
            value = optional_text(" ".join(item.css("span.column-value::text").getall()))
            if label and value:
                metadata[label.casefold()] = value

        records.append(
            {
                "id": job_id,
                "title": title,
                "url": add_query_value(urljoin(page_url, path), "lang", language),
                "job_type": metadata.get("art"),
                "contract_type": metadata.get("befristung"),
                "department": metadata.get("unternehmensbereich"),
                "listing_page": page_number,
                "listing_page_url": page_url,
                "total_available": expected_total,
            }
        )

    next_path = enabled_next_path(page)
    return records, expected_total, next_path


def extract_result_count(page: Selector) -> int:
    candidates = page.css("h3.jobs-counter *::text").getall()
    text = " ".join(str(item) for item in candidates)
    match = RESULT_COUNT_PATTERN.search(optional_text(text) or "")
    if match:
        digits = re.sub(r"\D", "", match.group(1))
        if digits:
            return int(digits)

    # Umantis initially renders the total in a web-component attribute and
    # copies it into the visible counter only after its JavaScript runs.
    initial_data = optional_text(page.css("table-navigation::attr(initial-data-string)").get())
    if initial_data:
        try:
            payload = json.loads(html.unescape(initial_data))
        except json.JSONDecodeError as exc:
            raise SwitchParseError("Switch Umantis page has an invalid vacancy count") from exc
        total = payload.get("TableTotalLines") if isinstance(payload, dict) else None
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            return total
        if isinstance(total, str) and total.isdigit():
            return int(total)

    if (
        optional_text(page.css("title::text").get()) == "Switch Bewerbermanagement Stellen"
        and optional_text(" ".join(page.css("#connectortable_1 .color-grey-m::text").getall()))
        == "Es wurden noch keine Einträge erfasst, die hier angezeigt werden könnten."
        and not page.css('a.HSTableLinkSubTitle[href*="/Vacancies/"]')
    ):
        return 0
    raise SwitchParseError("Switch Umantis page is missing its vacancy count")


def enabled_next_path(page: Selector) -> str | None:
    for link in page.css('a.load-next[aria-label="nächste"]'):
        disabled = optional_text(link.attrib.get("aria-disabled"))
        classes = set(str(link.attrib.get("class", "")).split())
        if disabled == "true" or "disabled" in classes:
            continue
        path = optional_text(link.attrib.get("href"))
        if path:
            return path
    return None


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_title: str | None,
    language: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    content = page.css("#mg_template .content")
    title = optional_text(" ".join(content.css("h1::text").getall()))
    apply_path = optional_text(page.css('a[href*="/Application/CheckLogin/"]::attr(href)').get())
    content_html = content.get()
    if not content_html or not title or not apply_path:
        raise SwitchParseError("Switch Umantis detail page is incomplete")
    if expected_title and title.casefold() != expected_title.casefold():
        raise SwitchParseError("Switch Umantis detail page returned a different vacancy")

    description = html_to_text(content_html)
    description = remove_standalone_line(description, title)
    description = remove_standalone_line(description, "Jetzt bewerben")
    if not description:
        raise SwitchParseError("Switch Umantis detail page has no vacancy description")
    return {
        "title": title,
        "apply_url": add_query_value(
            urljoin(page_url, apply_path),
            "lang",
            language,
        ),
        "description": description,
    }


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = VACANCY_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1) if match else None


def extract_location(title: str | None) -> str | None:
    if not title:
        return None
    match = LOCATION_SUFFIX_PATTERN.search(title)
    return optional_text(match.group(1)) if match else None


def extract_workload(title: str | None) -> str | None:
    if not title:
        return None
    match = WORKLOAD_PATTERN.search(title)
    if not match:
        return None
    return re.sub(r"\s*[-–]\s*", "–", match.group(1)) + "%"


def deduplicate_switch_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def first_query_value(url: str, name: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(name, [])
    return optional_text(values[0]) if values else None


def add_query_value(url: str, name: str, value: str | None) -> str:
    if not value:
        return url
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query.setdefault(name, [value])
    flattened = [(key, item) for key, values in query.items() for item in values]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(flattened), ""))


def join_unique(*values: str | None) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def remove_standalone_line(value: str | None, line: str) -> str | None:
    if not value:
        return None
    lines = value.splitlines()
    target = optional_text(line)
    filtered = [item for item in lines if optional_text(item) != target]
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
