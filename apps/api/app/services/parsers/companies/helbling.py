from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

HELBLING_JOBS_URL = "https://helbling.ch/de/karriere/jobs"
HELBLING_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/(?:de|en)/(?:karriere|career)/jobs/[^/]+/?$")
JOB_ID_PATTERN = re.compile(r"^\[(\d+)\]\s*:")
APPLICATION_PATH_PATTERN = re.compile(
    r"^/application-process/[0-9a-f-]{36}/[0-9a-f-]{36}/?$",
    re.IGNORECASE,
)
SWISS_LOCATIONS = {
    "Aarau": "Aarau, Switzerland",
    "Bern": "Bern, Switzerland",
    "Wil": "Wil, Switzerland",
    "Zurich": "Zürich, Switzerland",
}
KNOWN_FOREIGN_LOCATIONS = {"Cambridge", "Dusseldorf"}
EMPLOYMENT_TYPES = {
    "Apprenticeship": "Apprenticeship",
    "Internship": "Internship",
    "PermanentPosition": "Permanent",
}


class HelblingParseError(DirectCompanyRequestError):
    pass


class HelblingJobsParser:
    """Collect the complete Swiss subset of Helbling's official job catalog."""

    parser_id = "helbling"

    def __init__(
        self,
        *,
        base_url: str = HELBLING_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**HELBLING_HEADERS, "Referer": self.base_url},
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
        except HelblingParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Helbling vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Helbling vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_helbling_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Helbling Switzerland vacancies from the official catalog"
            ),
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
                response = client.get(
                    record["url"],
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=record["id"],
                    expected_location=record["location_code"],
                )
            except (httpx.HTTPError, HelblingParseError, ValueError) as exc:
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
            title=optional_text(record.get("title")) or optional_text(detail.get("title")),
            company="Helbling",
            location=(
                optional_text(detail.get("location"))
                or normalize_listing_location(record.get("location_code"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(record.get("posted_at")),
            employment_type=format_employment_type(
                record.get("employment_kind"),
                record.get("workload"),
            ),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> list[dict[str, Any]]:
    page = Selector(page_html)
    cards = page.css(".jobsearch-item")
    visible_count = parse_positive_int(page.css(".js-list-count::text").get())
    total_count = parse_positive_int(page.css('[x-html="itemsTotal"]::text').get())
    if not cards or visible_count is None or total_count is None:
        raise HelblingParseError("Helbling listing is missing its complete job catalog")
    if visible_count != total_count or len(cards) != total_count:
        raise HelblingParseError(
            f"Helbling listed {len(cards)} vacancies but declared {total_count}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        tags = parse_tags(card.attrib.get("data-tags"))
        location_code = optional_text(tags.get("location"))
        if location_code not in {*SWISS_LOCATIONS, *KNOWN_FOREIGN_LOCATIONS}:
            raise HelblingParseError("Helbling listing contains an unknown location")

        job_id = selector_text(card, ".ident")
        title = selector_text(card, ".title")
        area = selector_text(card, ".display-overline")
        workload = selector_text(card, ".pensum")
        posted_at = normalize_listing_date(selector_text(card, ".date"))
        detail_path = optional_text(card.css("a::attr(href)").get())
        detail_url = urljoin(page_url, detail_path) if detail_path else None
        if (
            not job_id
            or not job_id.isdigit()
            or not title
            or not area
            or not workload
            or not posted_at
            or not is_helbling_job_url(detail_url)
        ):
            raise HelblingParseError("Helbling listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise HelblingParseError("Helbling listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)

        if location_code in KNOWN_FOREIGN_LOCATIONS:
            continue
        records.append(
            {
                "id": job_id,
                "title": title,
                "area": area,
                "location_code": location_code,
                "workload": workload,
                "employment_kind": optional_text(tags.get("type")),
                "posted_at": posted_at,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str,
    expected_location: str,
) -> dict[str, Any]:
    if not is_helbling_job_url(page_url):
        raise HelblingParseError("Helbling detail page returned a different vacancy")
    page = Selector(page_html)
    breadcrumb_job_id = extract_breadcrumb_job_id(page)
    if breadcrumb_job_id != expected_job_id:
        raise HelblingParseError("Helbling detail page returned a different vacancy")

    primary_title = selector_text(page, "main .m-hero-level-3 h1")
    subtitle = selector_text(page, "main .m-hero-level-3 h2")
    title = join_title(primary_title, subtitle)
    contact_location = selector_text(page, "main .contact-box strong")
    normalized_location = normalize_detail_location(
        contact_location,
        expected_location=expected_location,
    )
    description_parts: list[str] = []
    for node in page.css("main .two-column-content .c-bodytext"):
        text = html_to_text(str(node.get()))
        if text and text not in description_parts:
            description_parts.append(text)
    job_lead = selector_text(
        page,
        ".nodetype-element--jvmtech-base-content-headline--joblead",
    )
    if job_lead and job_lead not in description_parts:
        description_parts.append(job_lead)
    apply_urls = {
        normalized
        for value in page.css("main .contact-box a.c-button::attr(href)").getall()
        if (normalized := normalize_apply_url(urljoin(page_url, str(value))))
    }
    if len(apply_urls) != 1:
        raise HelblingParseError("Helbling detail page has an ambiguous apply link")
    apply_url = apply_urls.pop()

    if (
        not title
        or not normalized_location
        or not description_parts
        or not is_helbling_apply_url(apply_url)
    ):
        raise HelblingParseError("Helbling detail page contains an incomplete or non-Swiss vacancy")
    return {
        "id": breadcrumb_job_id,
        "title": title,
        "company": "Helbling",
        "location": normalized_location,
        "apply_url": apply_url,
        "description": "\n\n".join(description_parts),
    }


def extract_breadcrumb_job_id(page: Selector) -> str | None:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            if candidate.get("@type") != "BreadcrumbList":
                continue
            items = candidate.get("itemListElement")
            if not isinstance(items, list):
                continue
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                name = optional_text(item.get("name"))
                match = JOB_ID_PATTERN.match(name or "")
                if match:
                    return match.group(1)
    return None


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_tags(value: Any) -> dict[str, Any]:
    text = optional_text(value)
    if not text:
        raise HelblingParseError("Helbling listing card is missing its filter metadata")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HelblingParseError("Helbling listing card has invalid filter metadata") from exc
    if not isinstance(payload, dict):
        raise HelblingParseError("Helbling listing card has invalid filter metadata")
    return payload


def normalize_listing_location(value: Any) -> str | None:
    text = optional_text(value)
    return SWISS_LOCATIONS.get(text or "")


def normalize_detail_location(value: Any, *, expected_location: str) -> str | None:
    text = optional_text(value)
    expected = normalize_listing_location(expected_location)
    if not text or not expected:
        return None
    compact = re.sub(r"[^a-z]", "", text.casefold())
    location_tokens = {
        "Aarau": ("aarau",),
        "Bern": ("bern",),
        "Wil": ("wil",),
        "Zurich": ("zurich", "zürich"),
    }
    if not any(
        token in compact or token in text.casefold() for token in location_tokens[expected_location]
    ):
        return None
    return expected


def normalize_listing_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:]}").isoformat()
    except ValueError:
        return None


def format_employment_type(kind: Any, workload: Any) -> str | None:
    kind_text = optional_text(kind)
    workload_text = optional_text(workload)
    label = EMPLOYMENT_TYPES.get(kind_text or "")
    if label and workload_text:
        return f"{label} · {workload_text}"
    return label or workload_text


def is_helbling_job_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "helbling.ch"
        and JOB_PATH_PATTERN.fullmatch(parts.path) is not None
    )


def is_helbling_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "app.jobportal.abaservices.ch"
        and APPLICATION_PATH_PATTERN.fullmatch(parts.path) is not None
    )


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if is_helbling_apply_url(text):
        return text
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "eur03.safelinks.protection.outlook.com"
    ):
        return None
    nested = optional_text(parse_qs(parts.query).get("url", [None])[0])
    return nested if is_helbling_apply_url(nested) else None


def join_title(primary: str | None, subtitle: str | None) -> str | None:
    if primary and subtitle and subtitle.casefold() not in primary.casefold():
        return f"{primary} / {subtitle}"
    return primary or subtitle


def deduplicate_helbling_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def parse_positive_int(value: Any) -> int | None:
    text = optional_text(value)
    if not text or not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


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
