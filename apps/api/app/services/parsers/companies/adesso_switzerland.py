from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ADESSO_SWITZERLAND_JOBS_URL = "https://www.adesso.ch/de_ch/jobs-karriere/unsere-stellenangebote/"
ADESSO_SWITZERLAND_FEED_URL = (
    "https://www.adesso.ch/de_ch/jobs-karriere/unsere-stellenangebote/"
    "rss_generator-rss0.php?unit=adesso_ch&lang=de"
)
ADESSO_HEADERS = {
    "Accept": "application/xml,text/xml;q=0.9,text/html;q=0.8,*/*;q=0.7",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7,fr;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_SCHEMA_COMPANY = "adesso Schweiz AG Jobportal"
OUTPUT_COMPANY = "adesso Schweiz AG"
SWISS_OFFICES = {"Basel", "Bern", "Lausanne", "Lugano", "St. Gallen", "Zürich"}
DETAIL_PATH_PATTERN = re.compile(
    r"^/de_ch/jobs-karriere/unsere-stellenangebote/.+-de-j(\d+)\.html$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    r"^/de_ch/jobs-karriere/unsere-stellenangebote/.+-de-f(\d+)\.html$",
    re.IGNORECASE,
)
MAX_FEED_BYTES = 5_000_000


class AdessoSwitzerlandParseError(DirectCompanyRequestError):
    pass


class AdessoSwitzerlandJobsParser:
    """Collect the complete official adesso Schweiz Rexx catalog."""

    parser_id = "adesso_switzerland"

    def __init__(
        self,
        *,
        base_url: str = ADESSO_SWITZERLAND_JOBS_URL,
        feed_url: str = ADESSO_SWITZERLAND_FEED_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.feed_url = feed_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ADESSO_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.feed_url)
                response.raise_for_status()
                records = parse_catalog_xml(response.content, base_url=self.base_url)
                self.enrich_records(client, records)
        except AdessoSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Adesso Switzerland vacancy request failed") from exc
        except (ElementTree.ParseError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Adesso Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_adesso_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Adesso Switzerland vacancies from the "
                "complete official catalog"
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
                    expected_record=record,
                    base_url=self.base_url,
                )
            except (httpx.HTTPError, AdessoSwitzerlandParseError, ValueError) as exc:
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
        public_url = optional_text(detail.get("public_url")) or optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=OUTPUT_COMPANY,
            location=format_locations(record.get("locations")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
            ),
            employment_type=normalize_employment_type(detail.get("employment_type")),
            seniority=join_values(record.get("career_levels")),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("teaser"))
            ),
            raw=dict(record),
        )


def parse_catalog_xml(content: bytes, *, base_url: str) -> list[dict[str, Any]]:
    if (
        len(content) > MAX_FEED_BYTES
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise AdessoSwitzerlandParseError("Adesso Switzerland catalog XML is unsafe")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise AdessoSwitzerlandParseError("Adesso Switzerland catalog XML is malformed") from exc
    if root.tag != "documents" or any(child.tag != "document" for child in root):
        raise AdessoSwitzerlandParseError(
            "Adesso Switzerland catalog XML has an unexpected structure"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for document in root:
        job_id = optional_text(document.attrib.get("uid"))
        fields = extract_xml_fields(document)
        title = single_field(fields, "title")
        detail_url = normalize_catalog_job_url(single_field(fields, "link"), base_url)
        posted_at = normalize_date(single_field(fields, "last_update_date"))
        teaser = single_field(fields, "content")
        locations = unique_fields(fields, "location_multi_keyword")
        departments = unique_fields(fields, "department_multi_keyword")
        career_levels = unique_fields(fields, "career_level_multi_keyword")
        if (
            not job_id
            or not job_id.isdigit()
            or extract_query_job_id(detail_url) != job_id
            or not title
            or not detail_url
            or not posted_at
            or not teaser
            or not locations
            or not departments
            or not career_levels
            or set(locations) - SWISS_OFFICES
            or single_field(fields, "content_type_multi_keyword") != "jobs"
            or single_field(fields, "mime_type_multi_keyword") != "text/html"
            or single_field(fields, "language_multi_keyword") != "de"
        ):
            raise AdessoSwitzerlandParseError(
                "Adesso Switzerland catalog contains an incomplete or unexpected vacancy"
            )
        if job_id in seen_ids:
            raise AdessoSwitzerlandParseError(
                "Adesso Switzerland catalog contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": OUTPUT_COMPANY,
                "locations": locations,
                "url": detail_url,
                "posted_at": posted_at,
                "departments": departments,
                "career_levels": career_levels,
                "teaser": teaser,
            }
        )
    return records


def extract_xml_fields(document: ElementTree.Element) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for field in document:
        name = optional_text(field.attrib.get("name")) if field.tag == "field" else None
        if not name or list(field):
            raise AdessoSwitzerlandParseError(
                "Adesso Switzerland catalog contains a malformed field"
            )
        value = optional_text(field.text)
        if value:
            fields.setdefault(name, []).append(value)
    return fields


def single_field(fields: dict[str, list[str]], name: str) -> str | None:
    values = fields.get(name, [])
    return values[0] if len(values) == 1 else None


def unique_fields(fields: dict[str, list[str]], name: str) -> list[str]:
    values = fields.get(name, [])
    return list(dict.fromkeys(values)) if len(values) == len(set(values)) else []


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
    base_url: str,
) -> dict[str, Any]:
    expected_job_id = optional_text(expected_record.get("id"))
    expected_listing_url = normalize_catalog_job_url(expected_record.get("url"), base_url)
    if not expected_job_id or normalize_catalog_job_url(page_url, base_url) != expected_listing_url:
        raise AdessoSwitzerlandParseError(
            "Adesso Switzerland detail page returned a different vacancy"
        )

    page = Selector(page_html)
    schemas = [
        candidate
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        for candidate in parse_json_objects(raw)
        if candidate.get("@type") == "JobPosting"
    ]
    if len(schemas) != 1:
        raise AdessoSwitzerlandParseError(
            "Adesso Switzerland detail page is missing its JobPosting data"
        )
    schema = schemas[0]
    canonical = normalize_public_job_url(
        page.css('link[rel="canonical"]::attr(href)').get(),
        base_url=base_url,
        expected_job_id=expected_job_id,
    )
    title = optional_text(schema.get("title"))
    company = optional_text(nested_value(schema, "hiringOrganization", "name"))
    posted_at = normalize_date(schema.get("datePosted"))
    valid_through = normalize_date(schema.get("validThrough"))
    employment_type = optional_text(schema.get("employmentType"))
    description = html_to_text(schema.get("description"))
    schema_locations = normalize_schema_locations(schema.get("jobLocation"))
    expected_locations = extract_string_list(expected_record.get("locations"))
    apply_urls = {
        normalized
        for value in page.css("#btn_online_application a::attr(href)").getall()
        if (
            normalized := normalize_apply_url(
                str(value),
                base_url=base_url,
                expected_job_id=expected_job_id,
            )
        )
    }
    if (
        not canonical
        or comparable_text(title) != comparable_text(expected_record.get("title"))
        or company != EXPECTED_SCHEMA_COMPANY
        or posted_at != expected_record.get("posted_at")
        or not valid_through
        or not employment_type
        or not description
        or set(schema_locations) != set(expected_locations)
        or len(apply_urls) != 1
    ):
        raise AdessoSwitzerlandParseError(
            "Adesso Switzerland detail page contains an incomplete or mismatched vacancy"
        )
    return {
        "id": expected_job_id,
        "title": title,
        "company": OUTPUT_COMPANY,
        "locations": schema_locations,
        "public_url": canonical,
        "apply_url": apply_urls.pop(),
        "posted_at": posted_at,
        "valid_through": valid_through,
        "employment_type": employment_type,
        "description": description,
        "schema": schema,
    }


def normalize_catalog_job_url(value: Any, base_url: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(base_url)
    query = parse_qs(parts.query)
    job_ids = query.get("yid")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected.netloc.casefold()
        or parts.path != "/de_ch/jobs-karriere/unsere-stellenangebote/stellenangebot.html"
        or len(query) != 1
        or not job_ids
        or len(job_ids) != 1
        or not job_ids[0].isdigit()
    ):
        return None
    return urlunsplit(
        (
            "https",
            expected.netloc.casefold(),
            parts.path,
            urlencode({"yid": job_ids[0]}),
            "",
        )
    )


def extract_query_job_id(value: str | None) -> str | None:
    if not value:
        return None
    values = parse_qs(urlsplit(value).query).get("yid")
    return values[0] if values and len(values) == 1 else None


def normalize_public_job_url(
    value: Any,
    *,
    base_url: str,
    expected_job_id: str,
) -> str | None:
    return normalize_path_job_url(
        value,
        base_url=base_url,
        expected_job_id=expected_job_id,
        pattern=DETAIL_PATH_PATTERN,
    )


def normalize_apply_url(
    value: Any,
    *,
    base_url: str,
    expected_job_id: str,
) -> str | None:
    return normalize_path_job_url(
        value,
        base_url=base_url,
        expected_job_id=expected_job_id,
        pattern=APPLY_PATH_PATTERN,
    )


def normalize_path_job_url(
    value: Any,
    *,
    base_url: str,
    expected_job_id: str,
    pattern: re.Pattern[str],
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(base_url)
    match = pattern.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected.netloc.casefold()
        or not match
        or match.group(1) != expected_job_id
    ):
        return None
    return urlunsplit(("https", expected.netloc.casefold(), parts.path, "", ""))


def normalize_schema_locations(value: Any) -> list[str]:
    raw_locations = value if isinstance(value, list) else [value]
    locations: list[str] = []
    for location in raw_locations:
        if not isinstance(location, dict):
            return []
        address = location.get("address")
        if not isinstance(address, dict):
            return []
        country = optional_text(address.get("addressCountry"))
        city = optional_text(address.get("addressLocality"))
        if country != "CH" or city not in SWISS_OFFICES:
            return []
        locations.append(city)
    return list(dict.fromkeys(locations)) if len(locations) == len(set(locations)) else []


def format_locations(value: Any) -> str | None:
    locations = extract_string_list(value)
    return "; ".join(f"{location}, Switzerland" for location in locations) or None


def normalize_employment_type(value: Any) -> str | None:
    mapping = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "INTERN": "Internship",
    }
    text = optional_text(value)
    return mapping.get(text or "", text)


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def parse_json_objects(value: Any) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return
    yield from walk_json(payload)


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"(?is)<(script|style|picture|figure)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def comparable_text(value: Any) -> str:
    text = optional_text(value)
    return re.sub(r"[^a-z0-9]+", "", text.casefold() if text else "")


def extract_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := optional_text(item))]


def join_values(value: Any) -> str | None:
    values = extract_string_list(value)
    return ", ".join(dict.fromkeys(values)) if values else None


def deduplicate_adesso_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line) or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or None
