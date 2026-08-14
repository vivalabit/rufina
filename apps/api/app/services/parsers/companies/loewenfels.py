from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

LOEWENFELS_CAREERS_URL = "https://www.loewenfels.ch/karriere/"
LOEWENFELS_API_URL = (
    "https://odm.ostendis.com/ojp/data/v55/jobs/"
    "e093bfef1e5b4b119ddf2f3eb38e665e/DE?domain=www.loewenfels.ch"
)
LOEWENFELS_HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
PUBLICATION_TOKEN = "e093bfef1e5b4b119ddf2f3eb38e665e"
EXPECTED_COMPANY = "Löwenfels Partner AG"
EXPECTED_LOCATION = "6004 Luzern, Switzerland"
EXPECTED_LOGO = "https://www.loewenfels.ch/wp-content/uploads/2025/08/loewenfels-logo-claim-rgb.svg"
EXPECTED_ADDRESS_PARTS = (
    EXPECTED_COMPANY,
    "Maihofstrasse 1",
    "CH – 6004 Luzern",
    "+41 41 418 44 00",
    "info@loewenfels.ch",
)
DETAIL_PATH_PATTERN = re.compile(r"^/publication/[a-z0-9]+(?:-[a-z0-9]+)*/([a-z0-9]+)$")
APPLY_PATH_PATTERN = re.compile(r"^/cvdropper/[a-f0-9]{32}/[A-Z]{2}$", re.IGNORECASE)
EMBED_PATTERN = re.compile(
    rf'OSTENDISJOBS\.embed\(\s*"{PUBLICATION_TOKEN}"\s*,(?:\s*//.*?\n)?\s*'
    r'"DE"\s*,(?:\s*//.*?\n)?\s*"#ostendisJobs"',
    re.MULTILINE,
)


class LoewenfelsParseError(DirectCompanyRequestError):
    pass


class LoewenfelsJobsParser:
    """Collect Löwenfels Partner AG's complete official Ostendis catalog."""

    parser_id = "loewenfels"

    def __init__(
        self,
        *,
        base_url: str = LOEWENFELS_CAREERS_URL,
        api_url: str = LOEWENFELS_API_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**LOEWENFELS_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                careers_response = client.get(self.base_url)
                careers_response.raise_for_status()
                parse_careers_html(
                    careers_response.text,
                    page_url=str(careers_response.url),
                    expected_url=self.base_url,
                    expected_api_url=self.api_url,
                )
                catalog_response = client.get(
                    self.api_url,
                    headers={"Referer": self.base_url},
                )
                catalog_response.raise_for_status()
                records = parse_catalog_payload(catalog_response.json())
                self.enrich_records(client, records)
        except LoewenfelsParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Löwenfels vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Löwenfels vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_loewenfels_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Löwenfels Switzerland vacancies from the official catalog"
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
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, LoewenfelsParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_careers_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_api_url: str,
) -> None:
    if not same_url(page_url, expected_url):
        raise LoewenfelsParseError("Löwenfels career page returned unexpected content")
    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    loaders = page.css("script#ostendisLoader")
    headings = unique_selector_texts(page, "main h1, main h2")
    logos = unique_attribute_values(page, "img.custom-logo", "data-src")
    expected_api = urlsplit(expected_api_url)
    api_parts = expected_api.path.rstrip("/").split("/")
    api_token = api_parts[-2] if len(api_parts) >= 2 else None
    spontaneous_links = {
        value
        for raw in page.css('main a[href*="cvdropper"]::attr(href)').getall()
        if (value := optional_text(raw)) and is_spontaneous_apply_url(value)
    }
    organizations = [
        item for item in extract_json_objects(page) if item.get("@type") == "Organization"
    ]
    organization_valid = any(
        same_url(item.get("url"), "https://www.loewenfels.ch")
        and comparable_text(item.get("name")).startswith("löwenfels")
        for item in organizations
    )
    footer_text = html_to_text("".join(node.get() for node in page.css("footer")))
    if (
        canonicals != {expected_url}
        or og_urls != {expected_url}
        or languages != {"de-CH"}
        or len(loaders) != 1
        or optional_text(loaders[0].attrib.get("src"))
        != "https://odm.ostendis.com/ojp/assets/loader"
        or optional_text(loaders[0].attrib.get("data-token")) != PUBLICATION_TOKEN
        or api_token != PUBLICATION_TOKEN
        or parse_qs(expected_api.query) != {"domain": ["www.loewenfels.ch"]}
        or len(page.css("main #ostendisJobs")) != 1
        or len(EMBED_PATTERN.findall(page_html)) != 1
        or len(spontaneous_links) != 1
        or not {"Karriere", "Offene Stellen"}.issubset(headings)
        or EXPECTED_LOGO not in logos
        or not organization_valid
        or not footer_text
        or not all(part in footer_text for part in EXPECTED_ADDRESS_PARTS)
    ):
        raise LoewenfelsParseError("Löwenfels career page has an unexpected identity or job portal")


def parse_catalog_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise LoewenfelsParseError("Löwenfels catalog payload is malformed")
    error = payload.get("error")
    if not isinstance(error, dict):
        raise LoewenfelsParseError("Löwenfels catalog payload is malformed")
    if error_message := optional_text(error.get("message")):
        raise LoewenfelsParseError(f"Löwenfels catalog returned an error: {error_message}")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_record in payload["jobs"]:
        if not isinstance(raw_record, dict):
            raise LoewenfelsParseError("Löwenfels catalog contains an invalid vacancy")
        record = dict(raw_record)
        job_id = optional_text(record.get("id"))
        title = optional_text(record.get("title"))
        detail_url = optional_text(record.get("detail"))
        detail_token = extract_detail_token(detail_url)
        country_code = optional_text(record.get("countrycode"))
        city = optional_text(record.get("city"))
        apply_url = optional_text(record.get("action"))
        workload = normalize_workload(record.get("workload"))
        if (
            not job_id
            or not job_id.isdigit()
            or not title
            or not detail_token
            or optional_text(record.get("langcode")) != "DE"
            or country_code not in {None, "CH"}
            or city not in {None, "Luzern"}
            or not workload
            or (apply_url and not is_apply_url(apply_url, expected_source_token=detail_token))
        ):
            raise LoewenfelsParseError(
                "Löwenfels catalog contains an incomplete or non-Swiss vacancy"
            )
        if job_id in seen_ids:
            raise LoewenfelsParseError("Löwenfels catalog contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        record.update(
            {
                "id": job_id,
                "title": title,
                "url": detail_url,
                "apply_url": apply_url,
                "workload": workload,
            }
        )
        records.append(record)
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise LoewenfelsParseError("Löwenfels detail page returned a different vacancy")
    detail_token = extract_detail_token(page_url)
    page = Selector(page_html)
    schemas = list(extract_job_posting_schemas(page))
    if not detail_token or len(schemas) != 1:
        raise LoewenfelsParseError("Löwenfels detail page is missing its JobPosting data")
    schema = schemas[0]
    title = optional_text(schema.get("title"))
    company = extract_company(schema)
    location = extract_swiss_location(schema.get("jobLocation"))
    description_html = optional_text(schema.get("description"))
    description = html_to_text(description_html or "")
    apply_urls = extract_apply_urls(
        description_html or "",
        expected_source_token=detail_token,
    )
    identifier = schema.get("identifier")
    identifier_name = (
        optional_text(identifier.get("name")) if isinstance(identifier, dict) else None
    )
    posted_at = normalize_iso_date(schema.get("datePosted"))
    employment_type = normalize_employment_type(schema.get("employmentType"))
    if (
        title != optional_text(expected_title)
        or company != EXPECTED_COMPANY
        or location != EXPECTED_LOCATION
        or identifier_name != EXPECTED_COMPANY
        or not description
        or len(apply_urls) != 1
        or not posted_at
        or not employment_type
    ):
        raise LoewenfelsParseError(
            "Löwenfels detail page contains an incomplete or mismatched vacancy"
        )
    return {
        "title": title,
        "company": company,
        "location": location,
        "apply_url": next(iter(apply_urls)),
        "posted_at": posted_at,
        "employment_type": employment_type,
        "description": description,
        "schema": schema,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="loewenfels",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=(optional_text(detail.get("location")) or normalize_listing_location(record)),
        url=optional_text(record.get("url")),
        apply_url=(
            optional_text(detail.get("apply_url"))
            or optional_text(record.get("apply_url"))
            or optional_text(record.get("url"))
        ),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=format_employment_type(
            detail.get("employment_type"),
            record.get("workload"),
        ),
        seniority=optional_text(record.get("position")),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def extract_json_objects(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        yield from walk_json(payload)


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for candidate in extract_json_objects(page):
        schema_type = candidate.get("@type")
        if schema_type == "JobPosting" or (
            isinstance(schema_type, list) and "JobPosting" in schema_type
        ):
            yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_company(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    return optional_text(organization.get("name")) if isinstance(organization, dict) else None


def extract_swiss_location(value: Any) -> str | None:
    locations = value if isinstance(value, list) else [value]
    for location in locations:
        if not isinstance(location, dict) or not isinstance(location.get("address"), dict):
            continue
        address = location["address"]
        country = optional_text(address.get("addressCountry"))
        locality = optional_text(address.get("addressLocality"))
        postal_code = optional_text(address.get("postalCode"))
        if country not in {"CH", "CHE", "Schweiz", "Switzerland"} or not locality:
            continue
        return f"{postal_code + ' ' if postal_code else ''}{locality}, Switzerland"
    return None


def extract_apply_urls(description_html: str, *, expected_source_token: str) -> set[str]:
    fragment = Selector(f"<div>{description_html}</div>")
    return {
        value
        for raw in fragment.css("a::attr(href)").getall()
        if (value := optional_text(raw))
        and is_apply_url(value, expected_source_token=expected_source_token)
    }


def extract_detail_token(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.loewenfels.ch"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def is_apply_url(value: Any, *, expected_source_token: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.loewenfels.ch"
        and APPLY_PATH_PATTERN.fullmatch(parts.path) is not None
        and parse_qs(parts.query) == {"src": [expected_source_token]}
        and not parts.fragment
    )


def is_spontaneous_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.loewenfels.ch"
        and parts.path == "/ojp/"
        and re.fullmatch(
            r"!/cvdropper/[a-f0-9]{32}/DE\?src=[a-z0-9]+",
            parts.fragment,
        )
        is not None
    )


def normalize_listing_location(record: dict[str, Any]) -> str | None:
    if optional_text(record.get("countrycode")) != "CH":
        return None
    city = optional_text(record.get("city"))
    postal_code = optional_text(record.get("zip"))
    return f"{postal_code + ' ' if postal_code else ''}{city}, Switzerland" if city else None


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?%", text)
    if not match:
        return None
    lower = int(match.group(1))
    upper = int(match.group(2) or match.group(1))
    if not 1 <= lower <= upper <= 100:
        return None
    return f"{lower}%" if lower == upper else f"{lower}–{upper}%"


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
        "OTHER": "Other",
    }
    normalized: list[str] = []
    for item in values:
        text = optional_text(item)
        label = labels.get(text.upper()) if text else None
        if label and label not in normalized:
            normalized.append(label)
    return " / ".join(normalized) or None


def format_employment_type(*values: Any) -> str | None:
    parts: list[str] = []
    for value in values:
        text = optional_text(value)
        if text and text not in parts:
            parts.append(text)
    return " · ".join(parts) or None


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


def deduplicate_loewenfels_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


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
