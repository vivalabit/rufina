from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

FLUGHAFEN_ZUERICH_JOBS_BASE_URL = (
    "https://www.flughafen-zuerich.ch/de/unternehmen/jobs/karriere/stellenangebote"
)
FLUGHAFEN_ZUERICH_JOBS_API_URL = (
    "https://www.flughafen-zuerich.ch/api/jobs/jobs?"
    "sc_site=dxp-portal&sc_lang=de&"
    "sc_itemid=%7b264461F0-4A00-4CF0-8B38-D24541D30C92%7d"
)
FLUGHAFEN_ZUERICH_SITECORE_API_KEY = "{3DCC43C7-A5C3-4A72-8CA5-A343CFD63F34}"
FLUGHAFEN_ZUERICH_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(
    r"/offene-stellen/[^/?#]+/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r"<script\b(?=[^>]*\btype\s*=\s*(['\"])application/ld\+json\1)[^>]*>"
    r"(.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)


class FlughafenZuerichParseError(DirectCompanyRequestError):
    pass


class FlughafenZuerichJobsParser:
    """Collect the complete Flughafen Zürich catalog from its Sitecore API."""

    parser_id = "flughafen_zuerich"

    def __init__(
        self,
        *,
        base_url: str = FLUGHAFEN_ZUERICH_JOBS_BASE_URL,
        api_url: str = FLUGHAFEN_ZUERICH_JOBS_API_URL,
        api_key: str = FLUGHAFEN_ZUERICH_SITECORE_API_KEY,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=FLUGHAFEN_ZUERICH_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(
                    self.api_url,
                    headers={
                        "Referer": self.base_url,
                        "sc_apikey": self.api_key,
                    },
                )
                response.raise_for_status()
                records = parse_listing_payload(response.json())
                self.enrich_records(client, records)
        except FlughafenZuerichParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Flughafen Zürich vacancy request failed") from exc
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise DirectCompanyRequestError("Flughafen Zürich vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_flughafen_zuerich_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Flughafen Zürich vacancies from the official API"),
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
            detail_url = optional_text(record.get("jobLink"))
            if not detail_url:
                return record, None
            try:
                response = client.get(
                    detail_url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": self.base_url,
                    },
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                )
            except (
                httpx.HTTPError,
                FlughafenZuerichParseError,
                ValueError,
            ) as exc:
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
        schema = detail.get("schema")
        schema = schema if isinstance(schema, dict) else {}
        public_url = optional_text(detail.get("canonical_url")) or optional_text(
            record.get("jobLink")
        )

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="Flughafen Zürich AG",
            location=(optional_text(detail.get("location")) or "Flughafen Zürich"),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(
                extract_filter_value(record, filter_id="30") or extract_employment_type(schema)
            ),
            seniority=extract_filter_value(record, filter_id="20"),
            description=(
                optional_multiline_text(detail.get("description"))
                or html_to_text(optional_text(record.get("shortDescription")) or "")
                or None
            ),
            raw=raw,
        )


def parse_listing_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise FlughafenZuerichParseError("Flughafen Zürich vacancy API must return a list")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise FlughafenZuerichParseError(
                "Flughafen Zürich vacancy API contains an invalid record"
            )
        job_id = optional_text(item.get("id"))
        view_key = optional_text(item.get("viewKey"))
        title = optional_text(item.get("title"))
        job_url = optional_text(item.get("jobLink"))
        if (
            not job_id
            or not view_key
            or not title
            or not job_url
            or extract_view_key(job_url) != view_key.casefold()
        ):
            raise FlughafenZuerichParseError(
                "Flughafen Zürich vacancy API contains an incomplete record"
            )
        if job_id in seen_ids:
            raise FlughafenZuerichParseError(
                "Flughafen Zürich vacancy API contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)

        filters = item.get("relevantFilters")
        if not isinstance(filters, list):
            raise FlughafenZuerichParseError(
                "Flughafen Zürich vacancy API contains invalid filters"
            )
        records.append(dict(item))
    return records


def parse_detail_html(page_html: str, *, page_url: str) -> dict[str, Any]:
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page_html), {})
    title = optional_text(schema.get("title"))
    description_html = optional_text(schema.get("description"))
    canonical_url = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    apply_url = optional_text(page.css('a.apply[href*="/apply/ats/"]::attr(href)').get())
    if not title or not description_html or not canonical_url or not apply_url:
        raise FlughafenZuerichParseError(
            "Flughafen Zürich detail page is missing required vacancy data"
        )

    return {
        "title": title,
        "canonical_url": urljoin(page_url, canonical_url),
        "apply_url": urljoin(page_url, apply_url),
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "location": extract_schema_location(schema),
        "description": html_to_text(description_html),
        "schema": schema,
    }


def extract_job_posting_schemas(page_html: str) -> Iterator[dict[str, Any]]:
    # Prospective appends the JobPosting block after </html>, outside the DOM tree.
    for _, raw_script in LD_JSON_SCRIPT_PATTERN.findall(page_html):
        try:
            payload = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
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
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_view_key(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1).casefold() if match else None


def extract_filter_value(record: dict[str, Any], *, filter_id: str) -> str | None:
    filters = record.get("relevantFilters")
    if not isinstance(filters, Sequence) or isinstance(filters, (str, bytes)):
        return None
    values: list[str] = []
    for item in filters:
        if not isinstance(item, dict) or optional_text(item.get("filterId")) != filter_id:
            continue
        options = item.get("filterOptions")
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
            continue
        for option in options:
            if isinstance(option, dict):
                value = optional_text(option.get("optionValue"))
                if value:
                    values.append(value)
    return ", ".join(dict.fromkeys(values)) or None


def extract_schema_location(schema: dict[str, Any]) -> str | None:
    location = schema.get("jobLocation")
    if isinstance(location, Sequence) and not isinstance(location, (str, bytes)):
        values = [extract_place_name(item) for item in location]
        names = [name for name in values if name]
        return ", ".join(dict.fromkeys(names)) or None
    return extract_place_name(location)


def extract_place_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return optional_text(value)
    address = value.get("address")
    if isinstance(address, dict):
        return optional_text(address.get("addressLocality")) or optional_text(
            address.get("addressRegion")
        )
    return optional_text(value.get("name"))


def extract_employment_type(schema: dict[str, Any]) -> str | None:
    value = schema.get("employmentType")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [text for item in value if (text := optional_text(item))]
        return ", ".join(values) or None
    return optional_text(value)


def deduplicate_flughafen_zuerich_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or extract_view_key(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
