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

ABRAXAS_JOBS_URL = "https://www.abraxas.ch/de/karriere/offene-stellen"
ABRAXAS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Abraxas Informatik AG"
JOB_PATH_PATTERN = re.compile(r"^/de/karriere/offene-stellen/[a-z0-9]+(?:-[a-z0-9]+)*-(\d+)/?$")
APPLY_PATH_PATTERN = re.compile(r"^/215876/(\d+)/index\.html$")
SWISS_LOCATIONS = {
    "Bern",
    "Kloten",
    "Münchenstein",
    "St. Gallen",
    "Zürich-Flughafen",
}


class AbraxasParseError(DirectCompanyRequestError):
    pass


class AbraxasJobsParser:
    """Collect Abraxas' complete server-rendered Swiss vacancy catalog."""

    parser_id = "abraxas"

    def __init__(
        self,
        *,
        base_url: str = ABRAXAS_JOBS_URL,
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
                headers={**ABRAXAS_HEADERS, "Referer": self.base_url},
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
        except AbraxasParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Abraxas vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Abraxas vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_abraxas_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Abraxas Switzerland vacancies from the official catalog"
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
                    expected_location=record["location"],
                )
            except (httpx.HTTPError, AbraxasParseError, ValueError) as exc:
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
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=None,
            employment_type=optional_text(detail.get("employment_type")),
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
        raise AbraxasParseError("Abraxas listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, page_url=page_url, expected_url=expected_url)
    lists = page.css("main .job-list__list")
    cards = lists[0].css(":scope > li.job-list__list-item") if len(lists) == 1 else []
    if not cards:
        raise AbraxasParseError("Abraxas listing is missing its vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        links = card.css("a.job-list__job")
        title = optional_text(selector_text(card, ".job-list__job-title"))
        raw_location = selector_text(card, ".job-list__job-location")
        location = normalize_location(raw_location)
        detail_url = urljoin(
            page_url,
            optional_text(links[0].attrib.get("href")) if len(links) == 1 else "",
        )
        job_id = extract_job_id(detail_url)
        if (
            not job_id
            or not title
            or not location
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise AbraxasParseError("Abraxas listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise AbraxasParseError("Abraxas listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": location,
                "url": detail_url,
                "listing_page_url": page_url,
                "location_ids": optional_text(card.attrib.get("data-locations")),
                "position_ids": optional_text(card.attrib.get("data-positions")),
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
    expected_location: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_job_id:
        raise AbraxasParseError("Abraxas detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, page_url=page_url, expected_url=expected_url)
    title = optional_text(page.css("h1.header__title::text").get())
    definitions = parse_definition_list(page)
    workload = normalize_workload(definitions.get("Pensum"))
    contract = optional_text(definitions.get("Anstellung"))
    location = normalize_location(definitions.get("Standort"))

    sections = page.css("main.r-main > section.u-section")
    description_nodes = (
        sections[0].css(".c-rich-text--default .rich-text-field") if sections else []
    )
    description = html_to_text(description_nodes[0].get()) if len(description_nodes) == 1 else None
    apply_urls = {
        value
        for raw in page.css("a.c-cta--secondary.desktop::attr(href)").getall()
        if (value := normalize_apply_url(raw))
    }
    apply_url = apply_urls.pop() if len(apply_urls) == 1 else None
    if (
        title != expected_title
        or location != expected_location
        or not workload
        or not contract
        or not description
        or not apply_url
    ):
        raise AbraxasParseError("Abraxas detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": location,
        "workload": workload,
        "contract": contract,
        "employment_type": f"{contract} · {workload}",
        "apply_url": apply_url,
        "refline_job_id": extract_apply_job_id(apply_url),
        "description": description,
    }


def validate_page_identity(page: Selector, *, page_url: str, expected_url: str) -> None:
    languages = {
        value for raw in page.css("html::attr(lang)").getall() if (value := optional_text(raw))
    }
    site_names = {
        value
        for raw in page.css('meta[property="og:site_name"]::attr(content)').getall()
        if (value := optional_text(raw))
    }
    og_urls = {
        urljoin(page_url, value)
        for raw in page.css('meta[property="og:url"]::attr(content)').getall()
        if (value := optional_text(raw))
    }
    if (
        languages != {"de"}
        or site_names != {EXPECTED_COMPANY}
        or len(og_urls) != 1
        or not same_url(next(iter(og_urls)), expected_url)
    ):
        raise AbraxasParseError("Abraxas page has an unexpected identity")


def parse_definition_list(page: Selector) -> dict[str, str]:
    values: dict[str, str] = {}
    items = page.css("main .definition-list__list .definition-list__item")
    for item in items:
        term = selector_text(item, ".definition-list__term")
        description = selector_text(item, ".desfinition-list__description")
        if not term or not description or term in values:
            raise AbraxasParseError("Abraxas detail page has an invalid definition list")
        values[term] = description
    if set(values) != {"Pensum", "Anstellung", "Standort"}:
        raise AbraxasParseError("Abraxas detail page has an incomplete definition list")
    return values


def normalize_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    locations = [optional_text(item) for item in text.split(",")]
    if not locations or any(not item or item not in SWISS_LOCATIONS for item in locations):
        return None
    return f"{', '.join(item for item in locations if item)}, Switzerland"


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    range_match = re.fullmatch(r"(\d{1,3})\s*%?\s*[-–]\s*(\d{1,3})\s*%", text)
    if range_match:
        lower, upper = (int(item) for item in range_match.groups())
        return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None
    single_match = re.fullmatch(r"(\d{1,3})\s*%", text)
    if single_match and 1 <= int(single_match.group(1)) <= 100:
        return f"{int(single_match.group(1))}%"
    return None


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    return text if is_apply_url(text) else None


def is_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "apply.refline.ch"
        and bool(APPLY_PATH_PATTERN.fullmatch(parts.path))
        and query == {"lang": ["de"], "cid": ["1"]}
        and not parts.fragment
    )


def extract_apply_job_id(value: Any) -> str | None:
    text = optional_text(value)
    match = APPLY_PATH_PATTERN.fullmatch(urlsplit(text).path) if text else None
    return match.group(1) if match else None


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path) if text else None
    return match.group(1) if match else None


def is_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and bool(JOB_PATH_PATTERN.fullmatch(parts.path))
        and not parts.query
        and not parts.fragment
    )


def same_url(value: str, expected: str) -> bool:
    actual = urlsplit(value)
    target = urlsplit(expected)
    return (
        actual.scheme.casefold() == target.scheme.casefold()
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and actual.query == target.query
    )


def deduplicate_abraxas_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    nodes = selector.css(css)
    return html_to_text(nodes[0].get()) if len(nodes) == 1 else None


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
