from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

M_S_CAREERS_URL = "https://www.m-s.ch/karriere/offene-stellen/"
M_S_API_URL = (
    "https://m-s.onlyfy.io/job/list/s717ythviciiuecx51r1kx3pb1bowby"
    "?format=json&lang=de&sorting_mode=date&sorting_dir=DESC&max_results=100"
)
M_S_HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "M&S Software Engineering AG"
EXPECTED_LOGO = "https://www.m-s.ch/img/brand-logo.svg"
EXPECTED_OFFICES = {"Bern": "3014", "Schlieren": "8952"}
FEED_HANDLE_PATTERN = re.compile(r"^[a-z0-9]{31}$")
PUBLIC_HANDLE_PATTERN = re.compile(r"^[a-z0-9]{30}$")
SHORT_HANDLE_PATTERN = re.compile(r"^[a-z0-9]{8}$")
YOUSTY_PATH_PATTERN = re.compile(r"^/de-CH/lehrstellen/profile/(\d+)-[a-z0-9-]+$")


class MSParseError(DirectCompanyRequestError):
    pass


class MSSoftwareEngineeringJobsParser:
    """Collect M&S Software Engineering AG's complete official vacancy catalog."""

    parser_id = "m_s_software_engineering"

    def __init__(
        self,
        *,
        base_url: str = M_S_CAREERS_URL,
        api_url: str = M_S_API_URL,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**M_S_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                careers_response = client.get(self.base_url)
                careers_response.raise_for_status()
                page_catalog = parse_careers_html(
                    careers_response.text,
                    page_url=str(careers_response.url),
                    expected_url=self.base_url,
                    expected_api_url=self.api_url,
                )
                api_response = client.get(self.api_url, headers={"Referer": self.base_url})
                api_response.raise_for_status()
                onlyfy_records = parse_onlyfy_payload(
                    api_response.json(),
                    page_catalog=page_catalog,
                )
                apprenticeship_records = parse_apprenticeships(page_catalog["apprenticeships"])
        except MSParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("M&S vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("M&S vacancy parsing failed") from exc

        records = [*onlyfy_records, *apprenticeship_records]
        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_m_s_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} M&S Switzerland vacancies from "
                f"{len(onlyfy_records)} Onlyfy records and "
                f"{len(apprenticeship_records)} apprenticeship listings"
            ),
        )


def parse_careers_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_api_url: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise MSParseError("M&S career page returned unexpected content")

    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    languages = unique_attribute_values(page, "html", "lang")
    titles = unique_selector_texts(page, "title")
    headings = unique_selector_texts(page, "main header, main h3")
    feeds = page.css("main #msui-jobs-feed")
    organization = find_organization(page)
    baked_jobs = load_json_script(page, "msui-jobs-feed-baked")
    apprenticeships = load_json_script(page, "msui-lehrstellen-baked")
    job_schemas = list(extract_job_posting_schemas(page))
    footer_text = html_to_text("".join(node.get() for node in page.css("footer")))
    if (
        canonicals != {expected_url}
        or languages != {"de"}
        or titles != {f"Offene Stellen | {EXPECTED_COMPANY}"}
        or len(feeds) != 1
        or optional_text(feeds[0].attrib.get("data-jobs-feed-url")) != expected_api_url
        or not {"Offene Stellen", "Schlieren (ZH)", "Bern Wankdorf"}.issubset(headings)
        or not valid_organization(organization)
        or not isinstance(baked_jobs, list)
        or not isinstance(apprenticeships, list)
        or len(job_schemas) != len(baked_jobs)
        or not footer_text
        or not all(
            part in footer_text
            for part in ("Bern Wankdorf", "Schlieren (ZH)", "info [at] m-s.ch", "+41 44 738 19 19")
        )
    ):
        raise MSParseError("M&S career page has an unexpected identity or vacancy portal")

    expected_query = {
        "format": ["json"],
        "lang": ["de"],
        "sorting_mode": ["date"],
        "sorting_dir": ["DESC"],
        "max_results": ["100"],
    }
    api_parts = urlsplit(expected_api_url)
    if (
        api_parts.scheme != "https"
        or api_parts.netloc.casefold() != "m-s.onlyfy.io"
        or api_parts.path != "/job/list/s717ythviciiuecx51r1kx3pb1bowby"
        or parse_qs(api_parts.query) != expected_query
        or api_parts.fragment
    ):
        raise MSParseError("M&S career page references an unexpected vacancy feed")

    return {
        "baked_jobs": baked_jobs,
        "apprenticeships": apprenticeships,
        "job_schemas": job_schemas,
    }


def parse_onlyfy_payload(
    payload: Any,
    *,
    page_catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise MSParseError("M&S Onlyfy payload is malformed")
    jobs = payload["jobs"]
    total = payload.get("totalResults")
    if (
        payload.get("company") != EXPECTED_COMPANY
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total != len(jobs)
        or payload.get("currentStartDisplay") != 0
    ):
        raise MSParseError("M&S Onlyfy payload contains inconsistent catalog metadata")

    baked_by_handle = index_page_records(page_catalog.get("baked_jobs"), "handle")
    schemas_by_handle = index_schemas(page_catalog.get("job_schemas"))
    if set(baked_by_handle) != set(schemas_by_handle) or len(baked_by_handle) != total:
        raise MSParseError("M&S career page and Onlyfy catalog do not match")

    records: list[dict[str, Any]] = []
    seen_public_handles: set[str] = set()
    for raw_record in jobs:
        if not isinstance(raw_record, dict):
            raise MSParseError("M&S Onlyfy catalog contains an invalid vacancy")
        record = dict(raw_record)
        handle = optional_text(record.get("handle"))
        short_handle = optional_text(record.get("shortHandle"))
        title = optional_text(record.get("title"))
        show_url = optional_text(record.get("showUrl"))
        apply_url = optional_text(record.get("applyUrl"))
        public_handle = extract_onlyfy_handle(show_url, path_prefix="/job/")
        city = valid_city(record.get("city"))
        description = optional_text(record.get("simple_html_content"))
        description_text = html_to_text(description or "")
        posted_at = normalize_iso_date(record.get("published_at"))
        department = nested_text(record.get("department"), "title")
        position_type = nested_text(record.get("positionType"), "title")
        seniority = nested_text(record.get("seniority"), "title")
        applications = record.get("applications_deadline_information")
        if (
            not handle
            or not FEED_HANDLE_PATTERN.fullmatch(handle)
            or not short_handle
            or not SHORT_HANDLE_PATTERN.fullmatch(short_handle)
            or not title
            or not public_handle
            or extract_onlyfy_handle(apply_url, path_prefix="/application/apply/") != public_handle
            or not city
            or not description
            or not description_text
            or not posted_at
            or not department
            or not position_type
            or not seniority
            or not isinstance(applications, dict)
            or applications.get("applications_allowed") is not True
            or public_handle in seen_public_handles
            or not page_record_matches(record, baked_by_handle.get(handle))
            or not schema_matches(record, schemas_by_handle.get(handle))
        ):
            raise MSParseError("M&S Onlyfy catalog contains an incomplete or mismatched vacancy")
        seen_public_handles.add(public_handle)
        record.update(
            {
                "id": public_handle,
                "title": title,
                "url": show_url,
                "apply_url": apply_url,
                "location": city,
                "description_text": description_text,
                "posted_at": posted_at,
                "department_text": department,
                "position_type_text": position_type,
                "seniority_text": seniority,
                "kind": "onlyfy",
            }
        )
        records.append(record)
    if set(baked_by_handle) != {optional_text(record.get("handle")) for record in records}:
        raise MSParseError("M&S career page and Onlyfy feed expose different vacancies")
    return records


def parse_apprenticeships(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise MSParseError("M&S apprenticeship catalog is malformed")
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_record in payload:
        if not isinstance(raw_record, dict):
            raise MSParseError("M&S apprenticeship catalog contains an invalid vacancy")
        title = optional_text(raw_record.get("title"))
        city = optional_text(raw_record.get("city"))
        description = optional_text(raw_record.get("text"))
        url = optional_text(raw_record.get("url"))
        job_id = extract_yousty_id(url)
        if (
            not title
            or city not in EXPECTED_OFFICES
            or not description
            or not job_id
            or job_id in seen_ids
        ):
            raise MSParseError("M&S apprenticeship catalog contains an incomplete vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                **raw_record,
                "id": f"yousty-{job_id}",
                "title": title,
                "url": url,
                "apply_url": url,
                "location": {
                    "title": city,
                    "zip_code": EXPECTED_OFFICES[city],
                },
                "description_text": description,
                "position_type_text": "Apprenticeship",
                "seniority_text": "Apprenticeship",
                "kind": "apprenticeship",
            }
        )
    return records


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    title = optional_text(record.get("title"))
    position_type = normalize_position_type(record.get("position_type_text"))
    workload = extract_workload(title)
    return ParsedJob(
        source="m_s_software_engineering",
        title=title,
        company=EXPECTED_COMPANY,
        location=format_location(record.get("location")),
        url=optional_text(record.get("url")),
        apply_url=optional_text(record.get("apply_url")),
        posted_at=optional_text(record.get("posted_at")),
        employment_type=join_unique(position_type, workload),
        seniority=optional_text(record.get("seniority_text")),
        description=optional_multiline_text(record.get("description_text")),
        raw=dict(record),
    )


def page_record_matches(record: dict[str, Any], baked: Any) -> bool:
    return bool(
        isinstance(baked, dict)
        and optional_text(baked.get("title")) == optional_text(record.get("title"))
        and same_url(baked.get("href"), record.get("showUrl"))
        and optional_text(baked.get("city")) == nested_text(record.get("city"), "title")
        and optional_text(baked.get("metaDescription"))
        == optional_text(record.get("metaDescription"))
    )


def schema_matches(record: dict[str, Any], schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    organization = schema.get("hiringOrganization")
    identifier = schema.get("identifier")
    locations = schema.get("jobLocation")
    locations = locations if isinstance(locations, list) else [locations]
    city = nested_text(record.get("city"), "title")
    zip_code = nested_text(record.get("city"), "zip_code")
    location_matches = any(
        isinstance(location, dict)
        and isinstance(location.get("address"), dict)
        and optional_text(location["address"].get("addressCountry")) == "CH"
        and optional_text(location["address"].get("addressLocality")) == city
        and optional_text(location["address"].get("postalCode")) == zip_code
        for location in locations
    )
    return bool(
        optional_text(schema.get("title")) == optional_text(record.get("title"))
        and normalize_iso_date(schema.get("datePosted"))
        == normalize_iso_date(record.get("published_at"))
        and optional_text(schema.get("description"))
        and isinstance(organization, dict)
        and optional_text(organization.get("name")) == EXPECTED_COMPANY
        and same_url(organization.get("sameAs"), "https://www.m-s.ch/")
        and optional_text(organization.get("logo")) == EXPECTED_LOGO
        and isinstance(identifier, dict)
        and optional_text(identifier.get("name")) == EXPECTED_COMPANY
        and optional_text(identifier.get("value")) == optional_text(record.get("handle"))
        and location_matches
        and normalize_schema_employment(schema.get("employmentType"))
        == normalize_position_type(nested_text(record.get("positionType"), "title"))
    )


def valid_organization(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    addresses = value.get("location")
    addresses = addresses if isinstance(addresses, list) else []
    office_pairs = {
        (
            nested_text(item.get("address"), "addressLocality"),
            nested_text(item.get("address"), "postalCode"),
        )
        for item in addresses
        if isinstance(item, dict)
    }
    return bool(
        optional_text(value.get("name")) == EXPECTED_COMPANY
        and optional_text(value.get("legalName")) == EXPECTED_COMPANY
        and same_url(value.get("url"), "https://www.m-s.ch/")
        and optional_text(value.get("logo")) == EXPECTED_LOGO
        and optional_text(value.get("email")) == "info@m-s.ch"
        and optional_text(value.get("telephone")) == "+41 44 738 19 19"
        and office_pairs == {(city, zip_code) for city, zip_code in EXPECTED_OFFICES.items()}
    )


def find_organization(page: Selector) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in extract_json_objects(page)
            if item.get("@type") == "Organization"
            and optional_text(item.get("legalName")) == EXPECTED_COMPANY
        ),
        None,
    )


def load_json_script(page: Selector, script_id: str) -> Any:
    scripts = page.css(f"script#{script_id}::text").getall()
    if len(scripts) != 1:
        return None
    try:
        return json.loads(str(scripts[0]))
    except (TypeError, json.JSONDecodeError):
        return None


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


def index_page_records(value: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise MSParseError("M&S career page catalog is malformed")
    indexed: dict[str, dict[str, Any]] = {}
    for item in value:
        item_key = optional_text(item.get(key)) if isinstance(item, dict) else None
        if not item_key or item_key in indexed:
            raise MSParseError("M&S career page catalog contains invalid records")
        indexed[item_key] = item
    return indexed


def index_schemas(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise MSParseError("M&S career page JobPosting catalog is malformed")
    indexed: dict[str, dict[str, Any]] = {}
    for schema in value:
        identifier = schema.get("identifier") if isinstance(schema, dict) else None
        handle = nested_text(identifier, "value")
        if not handle or handle in indexed:
            raise MSParseError("M&S career page contains invalid JobPosting data")
        indexed[handle] = schema
    return indexed


def valid_city(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    city = optional_text(value.get("title"))
    zip_code = optional_text(value.get("zip_code"))
    if (
        city not in EXPECTED_OFFICES
        or zip_code != EXPECTED_OFFICES[city]
        or optional_text(value.get("country")) != "Schweiz"
        or optional_text(value.get("countryCode")) != "CH"
    ):
        return None
    return dict(value)


def extract_onlyfy_handle(value: Any, *, path_prefix: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    handle = parts.path.removeprefix(path_prefix) if parts.path.startswith(path_prefix) else ""
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "m-s.onlyfy.jobs"
        or not PUBLIC_HANDLE_PATTERN.fullmatch(handle)
        or parts.query
        or parts.fragment
    ):
        return None
    return handle


def extract_yousty_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = YOUSTY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.yousty.ch"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def format_location(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    city = optional_text(value.get("title"))
    zip_code = optional_text(value.get("zip_code"))
    return f"{zip_code + ' ' if zip_code else ''}{city}, Switzerland" if city else None


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def normalize_position_type(value: Any) -> str | None:
    text = optional_text(value)
    labels = {
        "Teilzeit / Vollzeit": "Part-time / Full-time",
        "Vollzeit": "Full-time",
        "Teilzeit": "Part-time",
        "Apprenticeship": "Apprenticeship",
    }
    return labels.get(text) if text else None


def normalize_schema_employment(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = {"FULL_TIME": "Full-time", "PART_TIME": "Part-time"}
    normalized = [labels[text] for item in values if (text := optional_text(item)) in labels]
    if set(normalized) == {"Full-time", "Part-time"}:
        return "Part-time / Full-time"
    return " / ".join(normalized) or None


def extract_workload(title: Any) -> str | None:
    text = optional_text(title)
    if not text:
        return None
    matches = re.findall(r"\((\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?%\)", text)
    if len(matches) != 1:
        return None
    lower_text, upper_text = matches[0]
    lower = int(lower_text)
    upper = int(upper_text or lower_text)
    if not 1 <= lower <= upper <= 100:
        return None
    return f"{lower}%" if lower == upper else f"{lower}–{upper}%"


def join_unique(*values: Any) -> str | None:
    parts: list[str] = []
    for value in values:
        text = optional_text(value)
        if text and text not in parts:
            parts.append(text)
    return " · ".join(parts) or None


def nested_text(value: Any, key: str) -> str | None:
    return optional_text(value.get(key)) if isinstance(value, dict) else None


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


def deduplicate_m_s_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
