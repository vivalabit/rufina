from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

OPACC_JOBS_URL = "https://jobs.opacc.ch/"
OPACC_HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Opacc Software AG"
EXPECTED_CATEGORIES = {
    1: ("Kunden bedienen", "kunden-bedienen"),
    2: ("Fundament ausbauen", "fundament-ausbauen"),
}
EXPECTED_LOCATIONS = {
    "Rothenburg, Schweiz": ("Wahligenpark 1", "Rothenburg", "6023"),
    "Münchenstein, Schweiz": ("Tramstrasse 66", "Münchenstein", "4142"),
}
PAGE_SIZE = 4
JOB_PATH_PATTERN = re.compile(
    r"^/(kunden-bedienen|fundament-ausbauen)/([a-z0-9]+(?:-[a-z0-9]+)*)\.html$"
)
JOBS_TOTAL_PATTERN = re.compile(r"<!--\s*(\d+)_adTotalNo:(\d+)\s*-->")
JOBS_SCHEMA_PATTERN = re.compile(r'"@type"\s*:\s*"JobPosting"')
JOBS_ID_PATTERN = re.compile(r"^\d+$")
JOBS_APPLY_PATH_PATTERN = re.compile(
    r"^/job/[a-f0-9]{13,32}/opacc-software-ag/[a-z0-9][a-z0-9_-]*$"
)
JOBS_LEGACY_APPLY_PATH_PATTERN = re.compile(r"^/de/jobpreview/\d+$")


class OpaccParseError(DirectCompanyRequestError):
    pass


class OpaccJobsParser:
    """Collect Opacc Software AG's complete paginated Swiss vacancy catalog."""

    parser_id = "opacc"

    def __init__(
        self,
        *,
        base_url: str = OPACC_JOBS_URL,
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
                headers={**OPACC_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                homepage_response = client.get(self.base_url)
                homepage_response.raise_for_status()
                categories = parse_homepage_html(
                    homepage_response.text,
                    page_url=str(homepage_response.url),
                    expected_url=self.base_url,
                )
                records = self.fetch_catalog(client, categories)
                self.enrich_records(client, records)
        except OpaccParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Opacc vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Opacc vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_opacc_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Opacc Switzerland vacancies from the complete "
                f"{len(categories)}-category catalog"
            ),
        )

    def fetch_catalog(
        self,
        client: httpx.Client,
        categories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for category in categories:
            category_records: list[dict[str, Any]] = []
            page_count = math.ceil(category["total"] / PAGE_SIZE)
            for page_number in range(1, page_count + 1):
                response = client.get(
                    catalog_page_url(
                        self.base_url,
                        category_id=category["id"],
                        page_number=page_number,
                    ),
                    headers={"Referer": self.base_url},
                )
                response.raise_for_status()
                page_records = parse_catalog_payload(
                    response.json(),
                    category=category,
                    page_number=page_number,
                    expected_host=urlsplit(self.base_url).netloc,
                )
                if page_number == 1 and page_records != category["initial_records"]:
                    raise OpaccParseError(
                        "Opacc homepage and paginated catalog expose different vacancies"
                    )
                category_records.extend(page_records)
            if len(category_records) != category["total"]:
                raise OpaccParseError("Opacc paginated catalog is incomplete")
            records.extend(category_records)

        seen_ids: set[str] = set()
        for record in records:
            job_id = record["id"]
            if job_id in seen_ids:
                raise OpaccParseError("Opacc catalog contains duplicate vacancies")
            seen_ids.add(job_id)
        return records

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
                    expected_title=record["title"],
                    expected_location=record["location"],
                    expected_category=record["category"],
                )
            except (httpx.HTTPError, OpaccParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_homepage_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise OpaccParseError("Opacc homepage returned unexpected content")
    page = Selector(page_html)
    languages = unique_attribute_values(page, "html", "lang")
    titles = unique_selector_texts(page, "title")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    generators = unique_attribute_values(page, 'meta[name="generator"]', "content")
    bases = page.css("head base")
    header_logos = unique_attribute_values(page, "header .logo img", "src")
    footer_logos = unique_attribute_values(page, "footer .logo img", "src")
    location_labels = unique_selector_texts(page, "#jobs .city-filter label")
    footer_text = html_to_text("".join(node.get() for node in page.css("footer")))
    website_schemas = [
        item for item in extract_valid_json_objects(page) if item.get("@type") == "WebSite"
    ]
    if (
        languages != {"DE"}
        or titles != {"Opacc Jobs | Opacc Jobs"}
        or og_urls != {expected_url}
        or generators != {"Hannibal CMS"}
        or len(bases) != 1
        or optional_text(bases[0].attrib.get("data-domain")) != "jobs.opacc.ch"
        or not same_url(bases[0].attrib.get("data-url"), expected_url)
        or header_logos != {"https://jobs.opacc.ch/images/logo.png"}
        or footer_logos != {"https://jobs.opacc.ch/images/opacc-logo-large.svg"}
        or location_labels != {"Alle", "Rothenburg, Schweiz", "Münchenstein, Schweiz"}
        or len(website_schemas) != 1
        or optional_text(website_schemas[0].get("name")) != "Opacc Jobs"
        or not same_url(website_schemas[0].get("url"), expected_url)
        or not footer_text
        or not all(
            value in footer_text
            for value in (
                "Opacc",
                "Wahligenpark 1",
                "CH-6023 Rothenburg",
                "+41 41 349 51 00",
                "jobs@opacc.ch",
            )
        )
    ):
        raise OpaccParseError("Opacc homepage has an unexpected identity or catalog")

    categories: list[dict[str, Any]] = []
    containers = [
        node
        for node in page.css("#jobs > .container > .row > .jobs")
        if node.css(":scope > button.latest_ad_load_more")
    ]
    if len(containers) != len(EXPECTED_CATEGORIES):
        raise OpaccParseError("Opacc homepage is missing vacancy categories")
    for container in containers:
        headings = unique_selector_texts(container, ":scope > h3")
        buttons = container.css(":scope > button.latest_ad_load_more")
        if len(headings) != 1 or len(buttons) != 1:
            raise OpaccParseError("Opacc homepage contains an invalid vacancy category")
        button = buttons[0]
        category_id = parse_positive_int(button.attrib.get("data-catid"))
        total = parse_non_negative_int(button.attrib.get("data-total"))
        page_number = parse_positive_int(button.attrib.get("data-pg"))
        expected = EXPECTED_CATEGORIES.get(category_id or -1)
        if (
            expected is None
            or headings != {expected[0]}
            or page_number != 1
            or total is None
            or optional_text(button.attrib.get("id")) != f"load_more_{category_id}"
        ):
            raise OpaccParseError("Opacc homepage contains invalid category metadata")
        initial_records = parse_job_cards(
            container.css(":scope > ul.job-list > li"),
            category_id=category_id,
            category_name=expected[0],
            category_slug=expected[1],
            expected_host=urlsplit(expected_url).netloc,
        )
        if len(initial_records) != min(PAGE_SIZE, total):
            raise OpaccParseError("Opacc homepage contains an incomplete first catalog page")
        categories.append(
            {
                "id": category_id,
                "name": expected[0],
                "slug": expected[1],
                "total": total,
                "initial_records": initial_records,
            }
        )
    if {item["id"] for item in categories} != set(EXPECTED_CATEGORIES):
        raise OpaccParseError("Opacc homepage contains duplicate vacancy categories")
    return sorted(categories, key=lambda item: item["id"])


def parse_catalog_payload(
    payload: Any,
    *,
    category: dict[str, Any],
    page_number: int,
    expected_host: str,
) -> list[dict[str, Any]]:
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "OK"
        or not isinstance(payload.get("html"), str)
    ):
        raise OpaccParseError("Opacc catalog response is malformed")
    fragment = payload["html"]
    totals = JOBS_TOTAL_PATTERN.findall(fragment)
    if totals != [(str(category["id"]), str(category["total"]))]:
        raise OpaccParseError("Opacc catalog response has inconsistent pagination metadata")
    page = Selector(f'<ul class="job-list">{fragment}</ul>')
    records = parse_job_cards(
        page.css("ul.job-list > li"),
        category_id=category["id"],
        category_name=category["name"],
        category_slug=category["slug"],
        expected_host=expected_host,
    )
    expected_count = min(
        PAGE_SIZE,
        max(0, category["total"] - ((page_number - 1) * PAGE_SIZE)),
    )
    if len(records) != expected_count:
        raise OpaccParseError("Opacc catalog response contains an incomplete page")
    return records


def parse_job_cards(
    cards: Any,
    *,
    category_id: int,
    category_name: str,
    category_slug: str,
    expected_host: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for card in cards:
        title_links = card.css(":scope > .jobs-title a")
        location_links = card.css(":scope > .jobs-city a")
        if len(title_links) != 1 or len(location_links) != 1:
            raise OpaccParseError("Opacc catalog contains an incomplete vacancy card")
        title = html_to_text(title_links[0].get())
        location = html_to_text(location_links[0].get())
        summary = optional_text(title_links[0].attrib.get("title"))
        url = optional_text(title_links[0].attrib.get("href"))
        location_url = optional_text(location_links[0].attrib.get("href"))
        job_id = extract_job_id(
            url,
            expected_host=expected_host,
            expected_category_slug=category_slug,
        )
        if (
            not title
            or location not in EXPECTED_LOCATIONS
            or not summary
            or not job_id
            or not same_url(url, location_url)
        ):
            raise OpaccParseError("Opacc catalog contains invalid vacancy data")
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": location,
                "summary": summary,
                "url": url,
                "category_id": category_id,
                "category": category_name,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
    expected_location: str,
    expected_category: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise OpaccParseError("Opacc detail page returned a different vacancy")
    page = Selector(page_html)
    languages = unique_attribute_values(page, "html", "lang")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    og_sites = unique_attribute_values(page, 'meta[property="og:site_name"]', "content")
    bases = page.css("head base")
    sections = page.css(".container.step1")
    if len(sections) != 1:
        raise OpaccParseError("Opacc detail page is missing its vacancy content")
    section = sections[0]
    titles = unique_selector_texts(section, ":scope > h1")
    locations = unique_selector_texts(section, ":scope > h2")
    description = html_to_text(
        "".join(node.get() for node in section.css(":scope > p, :scope > h3, :scope > ul"))
    )
    apply_urls = {
        value
        for raw in section.css(":scope > .links a.dark.button::attr(href)").getall()
        if (value := normalize_apply_url(raw))
    }
    schema = extract_job_schema_fields(page)
    expected_address = EXPECTED_LOCATIONS.get(expected_location)
    detail_path = urlsplit(expected_url).path.lstrip("/")
    if (
        languages != {"DE"}
        or og_urls != {expected_url}
        or og_sites != {"Opacc Jobs"}
        or len(bases) != 1
        or optional_text(bases[0].attrib.get("data-domain")) != "jobs.opacc.ch"
        or optional_text(bases[0].attrib.get("data-request-uri")) != detail_path
        or titles != {expected_title}
        or locations != {expected_location}
        or not description
        or len(apply_urls) != 1
        or not expected_address
        or schema.get("title") != expected_title
        or schema.get("industry") != expected_category
        or schema.get("employment_type") != "FULL_TIME"
        or schema.get("organization") != "Opacc"
        or not same_url(schema.get("same_as"), "https://www.jobs.opacc.ch/")
        or schema.get("logo") != "https://jobs.opacc.ch/images/logo-fav.png"
        or schema.get("street") != expected_address[0]
        or schema.get("locality") != expected_location
        or schema.get("region") != expected_address[1]
        or schema.get("postal_code") != expected_address[2]
        or not schema.get("posted_at")
        or not schema.get("id")
    ):
        raise OpaccParseError("Opacc detail page contains an incomplete vacancy")
    return {
        "id": schema["id"],
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": format_location(expected_location),
        "apply_url": next(iter(apply_urls)),
        "posted_at": schema["posted_at"],
        "employment_type": "Full-time",
        "description": description,
    }


def extract_job_schema_fields(page: Selector) -> dict[str, str | None]:
    scripts = [
        str(raw)
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        if JOBS_SCHEMA_PATTERN.search(str(raw))
    ]
    if len(scripts) != 1:
        return {}
    raw = scripts[0]
    return {
        "title": extract_schema_text(raw, "title"),
        "posted_at": normalize_iso_date(extract_schema_text(raw, "datePosted")),
        "industry": extract_schema_text(raw, "industry"),
        "employment_type": extract_schema_text(raw, "employmentType"),
        "organization": extract_schema_text(raw, "name"),
        "same_as": extract_schema_text(raw, "sameAs"),
        "logo": extract_schema_text(raw, "logo"),
        "street": extract_schema_text(raw, "streetAddress"),
        "locality": extract_schema_text(raw, "addressLocality"),
        "region": extract_schema_text(raw, "addressRegion"),
        "postal_code": extract_schema_text(raw, "postalCode"),
        "id": extract_schema_identifier(raw),
    }


def extract_schema_text(raw: str, key: str) -> str | None:
    matches = re.findall(rf'"{re.escape(key)}"\s*:\s*"([^"\r\n]*)"', raw)
    values = {html.unescape(match).strip() for match in matches if match.strip()}
    return next(iter(values)) if len(values) == 1 else None


def extract_schema_identifier(raw: str) -> str | None:
    match = re.search(
        r'"identifier"\s*:\s*\{.*?"value"\s*:\s*"(\d+)"\s*\}',
        raw,
        re.DOTALL,
    )
    return match.group(1) if match and JOBS_ID_PATTERN.fullmatch(match.group(1)) else None


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    title = optional_text(detail.get("title")) or optional_text(record.get("title"))
    return ParsedJob(
        source="opacc",
        title=title,
        company=EXPECTED_COMPANY,
        location=(optional_text(detail.get("location")) or format_location(record.get("location"))),
        url=optional_text(record.get("url")),
        apply_url=(optional_text(detail.get("apply_url")) or optional_text(record.get("url"))),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=join_unique(
            detail.get("employment_type"),
            extract_workload(title),
        ),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def catalog_page_url(base_url: str, *, category_id: int, page_number: int) -> str:
    query = urlencode(
        {
            "ajax": "adInfinity",
            "module": "latest",
            "json": "1",
            "category_id": category_id,
            "pg": page_number,
        }
    )
    return f"{base_url.rstrip('/')}/?{query}"


def extract_job_id(
    value: Any,
    *,
    expected_host: str,
    expected_category_slug: str,
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host.casefold()
        or not match
        or match.group(1) != expected_category_slug
        or parts.query
        or parts.fragment
    ):
        return None
    return f"{match.group(1)}-{match.group(2)}"


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    modern = (
        JOBS_APPLY_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.query
        and parts.fragment == "application"
    )
    legacy = (
        JOBS_LEGACY_APPLY_PATH_PATTERN.fullmatch(parts.path) is not None
        and parts.query == "tabid=tab2"
        and not parts.fragment
    )
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "my.jobalino.ch"
        or not (modern or legacy)
    ):
        return None
    return text


def format_location(value: Any) -> str | None:
    text = optional_text(value)
    location = EXPECTED_LOCATIONS.get(text or "")
    return f"{location[2]} {location[1]}, Switzerland" if location else None


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def extract_workload(title: Any) -> str | None:
    text = optional_text(title)
    if not text:
        return None
    matches = re.findall(r"(?:\(|,\s*)(\d{1,3})\s*[-–]\s*(\d{1,3})%\)?", text)
    if len(matches) != 1:
        return None
    lower = int(matches[0][0])
    upper = int(matches[0][1])
    return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None


def join_unique(*values: Any) -> str | None:
    parts: list[str] = []
    for value in values:
        text = optional_text(value)
        if text and text not in parts:
            parts.append(text)
    return " · ".join(parts) or None


def parse_positive_int(value: Any) -> int | None:
    text = optional_text(value)
    if not text or not text.isdigit() or int(text) < 1:
        return None
    return int(text)


def parse_non_negative_int(value: Any) -> int | None:
    text = optional_text(value)
    if not text or not text.isdigit():
        return None
    return int(text)


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


def extract_valid_json_objects(page: Selector) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            objects.append(payload)
    return objects


def deduplicate_opacc_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f"{css}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {value for node in selector.css(css) if (value := html_to_text(node.get()))}


def html_to_text(value: str) -> str | None:
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
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
