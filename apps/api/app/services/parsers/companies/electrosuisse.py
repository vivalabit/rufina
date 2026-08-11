from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ELECTROSUISSE_CAREERS_URL = (
    "https://www.electrosuisse.ch/de/karriere/offene-stellen/"
)
ELECTROSUISSE_API_URL = (
    "https://odm.ostendis.com/ojp/data/v55/jobs/"
    "3bydei12tjzhiw5j4mqa85cfj4bjoud2/DE"
    "?domain=www.electrosuisse.ch"
)
ELECTROSUISSE_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,fr;q=0.7,en;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DETAIL_PATH_PATTERN = re.compile(r"^/publication/[^/]+/([a-z0-9]+)$", re.IGNORECASE)
APPLY_PATH_PATTERN = re.compile(r"^/cvdropper/[a-f0-9]+/[A-Z]{2}$", re.IGNORECASE)
EXPECTED_COMPANY = "Electrosuisse"


class ElectrosuisseParseError(DirectCompanyRequestError):
    pass


class ElectrosuisseJobsParser:
    """Collect the complete official Electrosuisse Ostendis catalog."""

    parser_id = "electrosuisse"

    def __init__(
        self,
        *,
        base_url: str = ELECTROSUISSE_CAREERS_URL,
        api_url: str = ELECTROSUISSE_API_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ELECTROSUISSE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records = parse_catalog_payload(response.json())
                self.enrich_records(client, records)
        except ElectrosuisseParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Electrosuisse vacancy request failed"
            ) from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Electrosuisse vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_electrosuisse_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Electrosuisse vacancies from the official catalog"
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
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, ElectrosuisseParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(
            max_workers=min(self.detail_workers, len(records))
        ) as executor:
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
                normalize_listing_location(record)
                or optional_text(detail.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=(
                optional_text(detail.get("posted_at"))
                or normalize_listing_date(record.get("published"))
            ),
            employment_type=format_employment_type(
                detail.get("employment_type"),
                record.get("type"),
                record.get("workload"),
            ),
            seniority=optional_text(record.get("position")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_catalog_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ElectrosuisseParseError("Electrosuisse catalog payload is malformed")

    error = payload.get("error")
    if not isinstance(error, dict):
        raise ElectrosuisseParseError("Electrosuisse catalog payload is malformed")
    error_message = optional_text(error.get("message"))
    if error_message:
        raise ElectrosuisseParseError(
            f"Electrosuisse catalog returned an error: {error_message}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_record in payload["jobs"]:
        if not isinstance(raw_record, dict):
            raise ElectrosuisseParseError(
                "Electrosuisse catalog contains an invalid vacancy"
            )
        record = dict(raw_record)
        job_id = optional_text(record.get("id"))
        title = optional_text(record.get("title"))
        country_code = optional_text(record.get("countrycode"))
        city = optional_text(record.get("city"))
        detail_url = optional_text(record.get("detail"))
        action_url = optional_text(record.get("action"))
        if (
            not job_id
            or not title
            or country_code != "CH"
            or not city
            or not is_detail_url(detail_url)
            or action_url != detail_url
        ):
            raise ElectrosuisseParseError(
                "Electrosuisse catalog contains an incomplete or non-Swiss vacancy"
            )
        if job_id in seen_ids:
            raise ElectrosuisseParseError(
                "Electrosuisse catalog contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        record["id"] = job_id
        record["title"] = title
        record["city"] = city
        record["url"] = detail_url
        records.append(record)
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_title: str,
) -> dict[str, Any]:
    if not is_detail_url(page_url):
        raise ElectrosuisseParseError(
            "Electrosuisse detail page returned a different vacancy"
        )

    page = Selector(page_html)
    schemas = list(extract_job_posting_schemas(page))
    if len(schemas) != 1:
        raise ElectrosuisseParseError(
            "Electrosuisse detail page is missing its JobPosting data"
        )
    schema = schemas[0]
    title = optional_text(schema.get("title"))
    company = extract_company(schema)
    location = extract_swiss_location(schema.get("jobLocation"))
    description_html = optional_text(schema.get("description"))
    description = html_to_text(description_html or "")
    apply_urls = extract_apply_urls(description_html or "", page_url=page_url)
    apply_url = next(iter(apply_urls)) if len(apply_urls) == 1 else None
    if (
        title != optional_text(expected_title)
        or company != EXPECTED_COMPANY
        or not location
        or not description
        or not apply_url
    ):
        raise ElectrosuisseParseError(
            "Electrosuisse detail page contains an incomplete or mismatched vacancy"
        )

    return {
        "title": title,
        "company": company,
        "location": location["label"],
        "apply_url": apply_url,
        "posted_at": normalize_iso_date(schema.get("datePosted")),
        "employment_type": normalize_employment_type(schema.get("employmentType")),
        "description": description,
        "schema": schema,
    }


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            job_type = candidate.get("@type")
            if job_type == "JobPosting" or (
                isinstance(job_type, list) and "JobPosting" in job_type
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
    if not isinstance(organization, dict):
        return None
    return optional_text(organization.get("name"))


def extract_swiss_location(value: Any) -> dict[str, str] | None:
    locations = value if isinstance(value, list) else [value]
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if not isinstance(address, dict):
            continue
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name") or country.get("@id")
        country_text = optional_text(country)
        if not country_text or country_text.casefold() not in {
            "ch",
            "che",
            "switzerland",
            "schweiz",
            "suisse",
        }:
            continue
        locality = optional_text(address.get("addressLocality"))
        postal_code = optional_text(address.get("postalCode"))
        if not locality:
            continue
        prefix = f"{postal_code} " if postal_code else ""
        return {"locality": locality, "label": f"{prefix}{locality}, Switzerland"}
    return None


def extract_apply_urls(description_html: str, *, page_url: str) -> set[str]:
    if not description_html:
        return set()
    fragment = Selector(f"<div>{description_html}</div>")
    return {
        value
        for raw_value in fragment.css("a::attr(href)").getall()
        if (value := optional_text(raw_value))
        and is_apply_url(value, page_url=page_url)
    }


def is_detail_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.electrosuisse.ch"
        and DETAIL_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.query
        and not parts.fragment
    )


def is_apply_url(value: Any, *, page_url: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    source_token = DETAIL_PATH_PATTERN.fullmatch(urlsplit(page_url).path)
    source_values = dict(
        part.split("=", 1) for part in parts.query.split("&") if "=" in part
    )
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.electrosuisse.ch"
        and APPLY_PATH_PATTERN.fullmatch(parts.path) is not None
        and source_token is not None
        and source_values.get("src") == source_token.group(1)
        and not parts.fragment
    )


def normalize_listing_location(record: dict[str, Any]) -> str | None:
    if optional_text(record.get("countrycode")) != "CH":
        return None
    city = optional_text(record.get("city"))
    postal_code = optional_text(record.get("zip"))
    if not city:
        return None
    prefix = f"{postal_code} " if postal_code else ""
    return f"{prefix}{city}, Switzerland"


def normalize_listing_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=UTC).date().isoformat()
    except ValueError:
        return None


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
        if not text:
            continue
        label = labels.get(text.upper(), text.replace("_", " ").title())
        if label not in normalized:
            normalized.append(label)
    return ", ".join(normalized) or None


def format_employment_type(
    detail_value: Any,
    listing_type: Any,
    workload: Any,
) -> str | None:
    parts: list[str] = []
    for value in (detail_value, listing_type, workload):
        text = optional_text(value)
        if text and text not in parts:
            parts.append(text)
    return " · ".join(parts) or None


def deduplicate_electrosuisse_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = optional_text(job.raw.get("id"))
        key = job_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


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
