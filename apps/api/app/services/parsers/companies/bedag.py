from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BEDAG_JOBS_URL = "https://www.bedag.ch/de/jobs-und-karriere/offene-stellen/"
BEDAG_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/de/aktuelles/offene-stellen/job_(\d+)\.php$")
APPLY_PATH_PATTERN = re.compile(
    r"^/Vacancies/(\d+)/Application/CheckLogin/1$",
    re.IGNORECASE,
)
EXPECTED_COMPANY = "Bedag Informatik AG"
EXPECTED_COUNTRY = "Switzerland"


class BedagParseError(DirectCompanyRequestError):
    pass


class BedagJobsParser:
    """Collect Bedag's complete server-rendered vacancy catalog."""

    parser_id = "bedag"

    def __init__(
        self,
        *,
        base_url: str = BEDAG_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**BEDAG_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                )
                self.enrich_records(client, records)
        except BedagParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Bedag vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Bedag vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bedag_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Bedag Switzerland vacancies from the official catalog"),
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
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                    expected_workload=record["workload"],
                )
            except (httpx.HTTPError, BedagParseError, ValueError) as exc:
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
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=optional_text(detail.get("location")) or EXPECTED_COUNTRY,
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=None,
            employment_type=optional_text(record.get("workload")),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise BedagParseError("Bedag listing returned an unexpected page")

    page = Selector(page_html)
    cards = page.css("li.listEntryObject-job")
    if not cards:
        raise BedagParseError("Bedag listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        title = selector_text(card, ".listEntryTitle")
        workload = normalize_workload(selector_text(card, ".listEntryPensum"))
        data_path = optional_text(card.attrib.get("data-url"))
        link_paths = {
            optional_text(value)
            for value in card.css("a::attr(href)").getall()
            if optional_text(value)
        }
        if len(link_paths) != 1 or data_path not in link_paths:
            raise BedagParseError("Bedag listing contains an ambiguous vacancy link")
        detail_url = urljoin(page_url, data_path or "")
        job_id = extract_job_id(detail_url)
        if (
            not title
            or not workload
            or not job_id
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise BedagParseError("Bedag listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise BedagParseError("Bedag listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "workload": workload,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_workload: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise BedagParseError("Bedag detail page returned a different vacancy")

    page = Selector(page_html)
    if not page.css("html.object-job.project-de").get():
        raise BedagParseError("Bedag detail page is missing its vacancy marker")

    alternate_urls = {
        optional_text(value)
        for value in page.css('link[rel="alternate"][hreflang="de"]::attr(href)').getall()
        if optional_text(value)
    }
    title = optional_text(
        html.unescape(str(page.css('meta[property="og:title"]::attr(content)').get() or ""))
    )
    visible_titles = unique_selector_texts(page, ".jobTitle h1::text")
    workloads = {
        value
        for raw in page.css(".jobPercentage").getall()
        if (value := normalize_workload(html_to_text(str(raw))))
    }
    detail_ids = extract_labeled_values(page, "Stellen ID")
    locations = extract_labeled_values(page, "Standort")
    description_columns = page.css(
        "section.elementSection_var2 .elementContainerStandardColumns_var36 > .col2"
    )
    descriptions = {
        value for node in description_columns if (value := html_to_text(str(node.get())))
    }
    apply_urls = {
        normalized
        for value in page.css("main a::attr(href)").getall()
        if (
            normalized := normalize_apply_url(
                urljoin(page_url, str(value)),
                expected_job_id=expected_job_id,
            )
        )
    }

    if (
        alternate_urls != {expected_url}
        or title != optional_text(expected_title)
        or visible_titles != {title}
        or workloads != {optional_text(expected_workload)}
        or detail_ids != {expected_job_id}
        or len(locations) != 1
        or len(descriptions) != 1
        or len(apply_urls) != 1
        or extract_job_id(page_url) != expected_job_id
    ):
        raise BedagParseError("Bedag detail page contains an incomplete vacancy")

    location = next(iter(locations))
    return {
        "id": expected_job_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": f"{location}, {EXPECTED_COUNTRY}",
        "workload": next(iter(workloads)),
        "apply_url": next(iter(apply_urls)),
        "description": next(iter(descriptions)),
    }


def extract_labeled_values(page: Selector, label: str) -> set[str]:
    values: set[str] = set()
    for node in page.css("section.elementSection_var2 .elementText_var10 p"):
        text = html_to_text(str(node.get()))
        if not text:
            continue
        lines = [line for line in text.splitlines() if line]
        if lines and lines[0] == label and len(lines) > 1:
            value = optional_text(" ".join(lines[1:]))
            if value:
                values.add(value)
    return values


def unique_selector_texts(page: Selector, css: str) -> set[str]:
    return {value for raw in page.css(css).getall() if (value := html_to_text(str(raw)))}


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    return re.sub(r"\s*([–-])\s*", r"\1", text)


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1) if match else None


def is_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and extract_job_id(text) is not None
        and not parts.query
        and not parts.fragment
    )


def normalize_apply_url(value: Any, *, expected_job_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "recruitingapp-2898.umantis.com"
        or not match
        or match.group(1) != expected_job_id
        or parse_qs(parts.query, keep_blank_values=True) != {"lang": ["ger"]}
        or parts.fragment
    ):
        return None
    return text


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and not actual.query
        and not actual.fragment
        and not target.query
        and not target.fragment
    )


def deduplicate_bedag_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    value = selector.css(css).get()
    return html_to_text(str(value)) if value else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
