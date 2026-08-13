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

COMERGE_JOBS_URL = "https://www.comerge.net/en/career#"
COMERGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/en/career/([a-z0-9]+(?:-[a-z0-9]+)*)$")
WORKLOAD_PATTERN = re.compile(r"^\(m/f/d\)\s*(\d{1,3})%\s*[-–]\s*(\d{1,3})%$")
EXPECTED_COMPANY = "Comerge AG"
EXPECTED_LOCATION = "Zurich, Switzerland"
EXPECTED_EMAIL = "jobs@comerge.net"
EXPECTED_LANGUAGE = "en-CH"
EXPECTED_STREET = "Bubenbergstrasse 1"
EXPECTED_CITY = "8045 Zurich"


class ComergeParseError(DirectCompanyRequestError):
    pass


class ComergeJobsParser:
    """Collect Comerge AG's complete server-rendered Zurich vacancy catalog."""

    parser_id = "comerge"

    def __init__(
        self,
        *,
        base_url: str = COMERGE_JOBS_URL,
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
                headers={**COMERGE_HEADERS, "Referer": self.base_url},
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
        except ComergeParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Comerge vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Comerge vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_comerge_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Comerge Switzerland vacancies from the official catalog"
            ),
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
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
            except (httpx.HTTPError, ComergeParseError, ValueError) as exc:
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
            location=EXPECTED_LOCATION,
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=None,
            employment_type=optional_text(record.get("workload")),
            seniority=None,
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("summary"))
            ),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise ComergeParseError("Comerge listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, page_url=page_url, expected_url=expected_url)
    validate_swiss_footer(page)
    containers = page.css(".collection-list-wrapper-3 > .w-dyn-items")
    cards = containers.css(":scope > .collection-item-4")
    if len(containers) != 1 or not cards:
        raise ComergeParseError("Comerge listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        links = card.css("a.link-block-5")
        titles = unique_selector_texts(card, "h1.heading-6.english")
        workload_labels = unique_selector_texts(card, ".bold-text.english")
        summaries = unique_selector_texts(card, ".text-block.english")
        detail_url = urljoin(
            page_url,
            optional_text(links[0].attrib.get("href")) if len(links) == 1 else "",
        )
        job_id = extract_job_id(detail_url)
        if (
            len(titles) != 1
            or len(workload_labels) != 1
            or len(summaries) != 1
            or not job_id
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise ComergeParseError("Comerge listing contains an incomplete vacancy")
        title = next(iter(titles))
        workload_label = next(iter(workload_labels))
        workload = normalize_workload(workload_label)
        if not workload:
            raise ComergeParseError("Comerge listing contains an invalid workload")
        if job_id in seen_ids:
            raise ComergeParseError("Comerge listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "workload": workload,
                "workload_label": workload_label,
                "summary": next(iter(summaries)),
                "location": EXPECTED_LOCATION,
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
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_job_id:
        raise ComergeParseError("Comerge detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, page_url=page_url, expected_url=expected_url)
    validate_swiss_footer(page)
    headings = unique_selector_texts(page, ".container-with-background > h1.heading-huge.red")
    description_containers = page.css(".container-with-background .rich-text-block-3.w-richtext")
    description_nodes = (
        description_containers[0].css(":scope > :not(.job-application)")
        if len(description_containers) == 1
        else []
    )
    description = optional_multiline_text(
        "\n\n".join(value for node in description_nodes if (value := html_to_text(node.get())))
    )
    intro = unique_selector_texts(page, ".container-with-background .bold-text-6")
    apply_links = page.css(".job-application-link a.bold-text")
    apply_url = optional_text(apply_links[0].attrib.get("href")) if len(apply_links) == 1 else None
    addresses = unique_selector_texts(page, ".job-application-address")
    expected_headings = {expected_title, workload_label(expected_workload)}
    if (
        headings != expected_headings
        or len(intro) != 1
        or not next(iter(intro)).startswith("We are Comerge,")
        or len(description_containers) != 1
        or not description
        or not is_apply_url(apply_url, expected_title=expected_title)
        or len(addresses) != 1
        or not valid_application_address(next(iter(addresses)))
    ):
        raise ComergeParseError("Comerge detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "workload": expected_workload,
        "apply_url": apply_url,
        "description": description,
    }


def validate_page_identity(page: Selector, *, page_url: str, expected_url: str) -> None:
    canonicals = {
        urljoin(page_url, value)
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    languages = {
        value
        for raw in page.css('meta[http-equiv="content-language"]::attr(content)').getall()
        if (value := optional_text(raw))
    }
    expected_canonical = without_fragment(expected_url)
    if canonicals != {expected_canonical} or languages != {EXPECTED_LANGUAGE}:
        raise ComergeParseError("Comerge page has an unexpected identity")


def validate_swiss_footer(page: Selector) -> None:
    companies = unique_selector_texts(page, ".footer .column-29 h3 .white")
    addresses = unique_selector_texts(page, ".footer .column-29 .paragraph.inverted")
    if (
        companies != {EXPECTED_COMPANY}
        or len(addresses) != 1
        or EXPECTED_STREET not in next(iter(addresses))
        or EXPECTED_CITY not in next(iter(addresses))
    ):
        raise ComergeParseError("Comerge page is missing its Swiss company identity")


def valid_application_address(value: str) -> bool:
    return (
        EXPECTED_COMPANY in value
        and "HR Department" in value
        and EXPECTED_EMAIL in value
        and "+41 44 552 52 62" in value
    )


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := WORKLOAD_PATTERN.fullmatch(text)):
        return None
    lower, upper = (int(item) for item in match.groups())
    if not 1 <= lower <= upper <= 100:
        return None
    return f"{lower}–{upper}%"


def workload_label(value: Any) -> str | None:
    text = optional_text(value)
    match = re.fullmatch(r"(\d{1,3})–(\d{1,3})%", text or "")
    return f"(m/f/d) {match.group(1)}%-{match.group(2)}%" if match else None


def is_apply_url(value: Any, *, expected_title: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    return (
        parts.scheme == "mailto"
        and parts.path.casefold() == EXPECTED_EMAIL
        and query == {"subject": [f"Application: {expected_title}"]}
        and not parts.fragment
    )


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
        and JOB_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.query
        and not parts.fragment
    )


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == "https"
        and actual.scheme == target.scheme
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and actual.query == target.query
    )


def without_fragment(value: str) -> str:
    parts = urlsplit(value)
    return parts._replace(fragment="").geturl()


def deduplicate_comerge_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {value for node in selector.css(css) if (value := html_to_text(node.get()))}


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|strong)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = optional_multiline_text(html.unescape(text).replace("\xa0", " "))
    return re.sub(r"(?m)(^- .*)\n\n(?=- )", r"\1\n", normalized) if normalized else None


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
