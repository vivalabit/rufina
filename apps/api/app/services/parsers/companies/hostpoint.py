from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

HOSTPOINT_JOBS_URL = "https://www.hostpoint.ch/en/jobs/"
HOSTPOINT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Hostpoint AG"
EXPECTED_SITE_NAME = "Hostpoint"
EXPECTED_LANGUAGE = "en"
EXPECTED_LOCATION = "Rapperswil-Jona, Switzerland"
EXPECTED_UNITS = {"devs", "systems", "cc", "diverse", "admin", "lehrstelle"}
DETAIL_PATH_PATTERN = re.compile(r"^/en/jobs/details/([a-z0-9]+(?:-[a-z0-9]+)*)/?$")
INTERNAL_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKLOAD_RANGE_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%(?!\d)")
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*%(?!\d)")


class HostpointParseError(DirectCompanyRequestError):
    pass


class HostpointJobsParser:
    """Collect Hostpoint's complete server-rendered vacancy catalog."""

    parser_id = "hostpoint"

    def __init__(
        self,
        *,
        base_url: str = HOSTPOINT_JOBS_URL,
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
                headers={**HOSTPOINT_HEADERS, "Referer": self.base_url},
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
        except HostpointParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Hostpoint vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Hostpoint vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_hostpoint_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Hostpoint Switzerland vacancies "
                "from the official catalog"
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
                response = client.get(
                    record["url"], headers={"Referer": record["listing_page_url"]}
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_slug=record["id"],
                    expected_title=record["title"],
                    expected_workload=record["listing_workload"],
                )
            except (httpx.HTTPError, HostpointParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise HostpointParseError("Hostpoint listing returned an unexpected page")
    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url, detail_slug=None)
    lists = page.css("#jobs-list_ .area-list ul.jobs-innerlist[data-unit]")
    units = [optional_text(node.attrib.get("data-unit")) for node in lists]
    if (
        len(lists) != len(EXPECTED_UNITS)
        or set(units) != EXPECTED_UNITS
        or len(set(units)) != len(units)
        or any(optional_text(node.attrib.get("data-count")) != "8" for node in lists)
    ):
        raise HostpointParseError("Hostpoint listing is missing its complete vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    ordinary_count = 0
    for job_list in lists:
        unit = optional_text(job_list.attrib.get("data-unit"))
        for card in job_list.css(":scope > li.job"):
            titles = unique_selector_texts(card, ".header h5")
            workloads = unique_selector_texts(card, ".header > p")
            links = card.css(".header h5 a::attr(href)").getall()
            if len(titles) != 1 or len(workloads) != 1 or len(links) != 1:
                raise HostpointParseError("Hostpoint catalog contains an incomplete vacancy")
            public_url = urljoin(page_url, optional_text(links[0]) or "")
            slug = extract_detail_slug(public_url, expected_host=expected_host)
            title = next(iter(titles))
            workload_text = next(iter(workloads))
            spontaneous = "-spontan" in (optional_text(card.attrib.get("class")) or "").split()
            spontaneous_data = card.css(".spontan-data")
            if spontaneous:
                valid_spontaneous = (
                    len(spontaneous_data) == 1
                    and optional_text(spontaneous_data[0].attrib.get("data-slug")) == slug
                    and (optional_text(spontaneous_data[0].attrib.get("data-remarks")) or "").isdigit()
                )
            else:
                ordinary_count += 1
                valid_spontaneous = not spontaneous_data
            if (
                not slug
                or slug in seen_slugs
                or normalize_workload(workload_text) is None and workload_text != "0%"
                or not valid_spontaneous
            ):
                raise HostpointParseError("Hostpoint catalog contains an invalid vacancy")
            seen_slugs.add(slug)
            records.append(
                {
                    "id": slug,
                    "title": title,
                    "company": EXPECTED_COMPANY,
                    "location": EXPECTED_LOCATION,
                    "listing_workload": workload_text,
                    "employment_type": normalize_workload(workload_text),
                    "spontaneous": spontaneous,
                    "unit": unit,
                    "url": public_url,
                    "listing_page_url": page_url,
                }
            )
    badges = {
        value for raw in page.css('a[href="/en/jobs/"] .bluepill').getall()
        if (value := html_to_text(raw))
    }
    if not records or badges != {str(ordinary_count)}:
        raise HostpointParseError("Hostpoint listing has an inconsistent vacancy count")
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_slug: str,
    expected_title: str,
    expected_workload: str,
) -> dict[str, Any]:
    expected_host = urlsplit(expected_url).netloc.casefold()
    if (
        not same_url(page_url, expected_url)
        or extract_detail_slug(page_url, expected_host=expected_host) != expected_slug
    ):
        raise HostpointParseError("Hostpoint detail page returned a different vacancy")
    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url, detail_slug=expected_slug)
    heads = page.css(".jobs-head")
    contents = page.css(".jobs-content-inner")
    if len(heads) != 1 or len(contents) != 1:
        raise HostpointParseError("Hostpoint detail page is missing the requested vacancy")
    internal_slug = optional_text(heads[0].attrib.get("data-slug"))
    titles = unique_selector_texts(heads[0], "h1")
    full_titles = {
        value for raw in heads[0].css("h1::attr(data-fulltitle)").getall()
        if (value := optional_text(raw))
    }
    locations = unique_selector_texts(contents[0], ".jobs-params li.-location")
    workloads = unique_selector_texts(contents[0], ".jobs-params li.-employment")
    description_parts = [
        value
        for node in contents[0].css(
            ":scope > h2, :scope > h3, :scope > p, :scope > blockquote, "
            ":scope > ul:not(.jobs-params)"
        )
        if (value := html_to_text(node.get()))
    ]
    description = optional_multiline_text("\n\n".join(description_parts))
    location_text = next(iter(locations)) if len(locations) == 1 else None
    workload_text = next(iter(workloads)) if len(workloads) == 1 else None
    workload = normalize_workload(workload_text)
    expected_normalized_workload = normalize_workload(expected_workload)
    if (
        titles != {expected_title}
        or full_titles != {expected_title}
        or not internal_slug
        or INTERNAL_SLUG_PATTERN.fullmatch(internal_slug) is None
        or not location_text
        or "Rapperswil-Jona" not in location_text
        or not workload_text
        or workload != expected_normalized_workload
        or not description
        or not page.css("form.apply-form")
        or not page.css(".flat-button.-apply")
    ):
        raise HostpointParseError("Hostpoint detail page contains an incomplete vacancy")
    return {
        "id": expected_slug,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "apply_url": expected_url,
        "posted_at": None,
        "employment_type": workload,
        "description": description,
        "internal_slug": internal_slug,
    }


def validate_page_identity(
    page: Selector,
    *,
    expected_url: str,
    detail_slug: str | None,
) -> None:
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    site_names = unique_attribute_values(page, 'meta[property="og:site_name"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    body_classes = (optional_text(page.css("body::attr(class)").get()) or "").split()
    canonical_url = expected_url
    if detail_slug:
        parts = urlsplit(expected_url)
        canonical_url = f"https://{parts.netloc}/jobs/details/{detail_slug}/"
    expected_body_class = "jobsd" if detail_slug else "jobsn"
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), canonical_url)
        or site_names != {EXPECTED_SITE_NAME}
        or languages != {EXPECTED_LANGUAGE}
        or expected_body_class not in body_classes
        or EXPECTED_LANGUAGE not in body_classes
    ):
        raise HostpointParseError("Hostpoint page has an unexpected identity")


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="hostpoint",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=EXPECTED_LOCATION,
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=None,
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def extract_detail_slug(value: Any, *, expected_host: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if match := WORKLOAD_RANGE_PATTERN.search(text):
        lower, upper = (int(item) for item in match.groups())
        return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None
    if match := WORKLOAD_PATTERN.search(text):
        workload = int(match.group(1))
        return f"{workload}%" if 1 <= workload <= 100 else None
    return None


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
        and actual.query == target.query
        and not actual.fragment
    )


def deduplicate_hostpoint_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {value for node in selector.css(css) if (value := html_to_text(node.get()))}


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value for raw in selector.css(f"{css}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


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
