from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BAYER_SWITZERLAND_JOBS_BASE_URL = (
    "https://talent.bayer.com/careers?location=Basel%2CBasel-City%2CSwitzerland&"
    "pid=562949977567067&job%20type=professional&job%20type=job%20starter&"
    "job%20type=student&job%20type=graduate&domain=bayer.com&sort_by=relevance&"
    "triggerGoButton=false"
)
BAYER_SWITZERLAND_JOBS_API_URL = "https://talent.bayer.com/api/apply/v2/jobs"
BAYER_DOMAIN = "bayer.com"
BAYER_LOCATION = "Switzerland"
BAYER_JOB_TYPES = ("professional", "job starter", "student", "graduate")
BAYER_PAGE_SIZE = 10
BAYER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/careers/job/(?P<id>\d+)(?:-[^/?#]+)?/?$")


class BayerSwitzerlandParseError(DirectCompanyRequestError):
    pass


class BayerSwitzerlandJobsParser:
    """Collect Bayer's complete country-filtered Swiss Eightfold catalog."""

    parser_id = "bayer_switzerland"

    def __init__(
        self,
        *,
        base_url: str = BAYER_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = BAYER_SWITZERLAND_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def careers_origin(self) -> str:
        parts = urlsplit(self.base_url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**BAYER_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except BayerSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Bayer Switzerland vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Bayer Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bayer_jobs(jobs)
        page_label = "page" if pages_fetched == 1 else "pages"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Bayer Switzerland vacancies across "
                f"{pages_fetched} API {page_label} ({total} listed)"
            ),
        )

    def listing_params(self, *, offset: int) -> list[tuple[str, str | int]]:
        params: list[tuple[str, str | int]] = [
            ("domain", BAYER_DOMAIN),
            ("start", offset),
            ("num", BAYER_PAGE_SIZE),
            ("query", ""),
            ("location", BAYER_LOCATION),
        ]
        params.extend(("job type", job_type) for job_type in BAYER_JOB_TYPES)
        params.append(("sort_by", "relevance"))
        return params

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.get(self.api_url, params=self.listing_params(offset=offset))
        response.raise_for_status()
        total, records = parse_listing_payload(response.json(), base_url=self.base_url)
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        requests_made = 0
        last_total = 0
        last_unique = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            initial = self.fetch_listing_page(client, offset=0)
            requests_made += 1
            expected_total = initial[1]
            last_total = expected_total
            required_pages = max(1, ceil(expected_total / BAYER_PAGE_SIZE))
            if required_pages > self.max_pages:
                raise BayerSwitzerlandParseError(
                    f"Bayer Switzerland exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [initial]
            for offset in range(BAYER_PAGE_SIZE, expected_total, BAYER_PAGE_SIZE):
                page_results.append(self.fetch_listing_page(client, offset=offset))
                requests_made += 1

            records_by_id: dict[str, dict[str, Any]] = {}
            pass_records = 0
            catalog_changed = False
            for offset, page_total, records in page_results:
                expected_size = min(BAYER_PAGE_SIZE, max(0, expected_total - offset))
                if page_total != expected_total or len(records) != expected_size:
                    catalog_changed = True
                    break
                pass_records += len(records)
                for record in records:
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(extract_job_id(record), normalized)

            last_unique = len(records_by_id)
            if not catalog_changed and pass_records == expected_total == last_unique:
                return list(records_by_id.values()), requests_made, expected_total

        raise BayerSwitzerlandParseError(
            f"Bayer Switzerland yielded only {last_unique} unique vacancies of {last_total} "
            f"after {self.max_catalog_passes} catalog passes"
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
            detail_url = self.build_job_url(record)
            try:
                response = client.get(detail_url, headers={"Accept": "text/html"})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                    base_url=self.base_url,
                )
            except (httpx.HTTPError, BayerSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def build_job_url(self, record: dict[str, Any]) -> str:
        listing_url = normalize_job_url(
            record.get("canonicalPositionUrl"),
            base_url=self.base_url,
            require_domain_query=False,
        )
        if listing_url:
            return listing_url
        return f"{self.careers_origin}/careers/job/{extract_job_id(record)}"

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        public_url = optional_text(detail.get("public_url")) or self.build_job_url(record)
        raw = dict(record)
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("name")),
            company="Bayer",
            location=(
                extract_swiss_listing_location(record)
                or optional_text(detail.get("location"))
                or "Switzerland"
            ),
            url=public_url,
            apply_url=public_url,
            posted_at=(
                optional_text(detail.get("date_posted")) or epoch_to_date(record.get("t_create"))
            ),
            employment_type=normalize_employment_type(detail.get("employment_type")),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("job_description"))
            ),
            raw=raw,
        )


def parse_listing_payload(
    payload: Any,
    *,
    base_url: str,
) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise BayerSwitzerlandParseError("Bayer Switzerland jobs response must be an object")
    total = payload.get("count")
    positions = payload.get("positions")
    query = payload.get("query")
    if (
        payload.get("domain") != BAYER_DOMAIN
        or payload.get("location_used") != BAYER_LOCATION
        or payload.get("isSubQuery") is not True
        or not isinstance(query, dict)
        or query.get("query") != ""
        or query.get("location") != BAYER_LOCATION
        or query.get("pid") != ""
        or query.get("job type") != list(BAYER_JOB_TYPES)
    ):
        raise BayerSwitzerlandParseError(
            "Bayer Switzerland jobs response has unexpected query metadata"
        )
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise BayerSwitzerlandParseError("Bayer Switzerland jobs response has an invalid count")
    if not isinstance(positions, list):
        raise BayerSwitzerlandParseError("Bayer Switzerland jobs response has invalid positions")

    records: list[dict[str, Any]] = []
    for item in positions:
        if not isinstance(item, dict) or not is_valid_listing_record(item, base_url=base_url):
            raise BayerSwitzerlandParseError(
                "Bayer Switzerland jobs response contains an invalid vacancy"
            )
        records.append(item)
    return total, records


def is_valid_listing_record(record: dict[str, Any], *, base_url: str) -> bool:
    job_id = extract_job_id(record)
    title = optional_text(record.get("name"))
    canonical = normalize_job_url(
        record.get("canonicalPositionUrl"),
        base_url=base_url,
        require_domain_query=False,
    )
    locations = sequence_text(record.get("locations"))
    return bool(
        job_id
        and title
        and comparable_text(title) == comparable_text(record.get("posting_name"))
        and canonical
        and extract_url_job_id(canonical) == job_id
        and record.get("isPrivate") is False
        and record.get("type") == "ATS"
        and optional_text(record.get("ats_job_id"))
        and optional_text(record.get("display_job_id"))
        and record.get("ats_job_id") == record.get("display_job_id")
        and optional_text(record.get("id_locale"))
        and optional_text(record.get("locale"))
        and optional_text(record.get("department"))
        and optional_text(record.get("business_unit"))
        and locations
        and any(is_swiss_location(location) for location in locations)
    )


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
    base_url: str,
) -> dict[str, Any]:
    expected_job_id = extract_job_id(expected_record)
    if extract_url_job_id(page_url) not in {None, expected_job_id}:
        raise BayerSwitzerlandParseError("Bayer detail page returned a different vacancy")

    page = Selector(page_html)
    schemas = [
        node
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        for node in job_posting_nodes(raw)
    ]
    if len(schemas) != 1:
        raise BayerSwitzerlandParseError("Bayer detail page is missing its JobPosting data")
    schema = schemas[0]
    canonical = normalize_job_url(
        page.css('link[rel="canonical"]::attr(href)').get(),
        base_url=base_url,
        require_domain_query=True,
    )
    schema_url = normalize_job_url(
        schema.get("url"),
        base_url=base_url,
        require_domain_query=True,
    )
    title = optional_text(schema.get("title"))
    company = optional_text(nested_value(schema, "hiringOrganization", "name"))
    date_posted = normalize_date(schema.get("datePosted"))
    valid_through = normalize_date(schema.get("validThrough"))
    employment_type = optional_text(schema.get("employmentType"))
    description = optional_multiline_text(schema.get("description"))
    location = parse_swiss_schema_location(schema.get("jobLocation"))
    if (
        not canonical
        or canonical != schema_url
        or extract_url_job_id(canonical) != expected_job_id
        or comparable_text(title) != comparable_text(expected_record.get("name"))
        or company != "Bayer"
        or not date_posted
        or not valid_through
        or not employment_type
        or not description
        or not location
    ):
        raise BayerSwitzerlandParseError(
            "Bayer detail page contains an incomplete or mismatched vacancy"
        )
    return {
        "id": expected_job_id,
        "title": title,
        "company": company,
        "location": location,
        "public_url": canonical,
        "date_posted": date_posted,
        "valid_through": valid_through,
        "employment_type": employment_type,
        "description": description,
        "schema": schema,
    }


def job_posting_nodes(raw_json: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(html.unescape(raw_json))
    except (json.JSONDecodeError, TypeError):
        return []
    candidates: list[Any] = []
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        candidates.extend(graph if isinstance(graph, list) else [payload])
    elif isinstance(payload, list):
        candidates.extend(payload)
    return [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting"
    ]


def parse_swiss_schema_location(value: Any) -> str | None:
    locations = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for location in locations:
        address = location.get("address") if isinstance(location, dict) else None
        if not isinstance(address, dict):
            continue
        country = address.get("addressCountry")
        country_code = (
            optional_text(country.get("name"))
            if isinstance(country, dict)
            else optional_text(country)
        )
        locality = optional_text(address.get("addressLocality"))
        region = optional_text(address.get("addressRegion"))
        if country_code != "CH" or not locality or (region and not region.endswith(",CH")):
            continue
        normalized.append(f"{locality}, Switzerland")
    return ", ".join(dict.fromkeys(normalized)) if normalized else None


def normalize_job_url(
    value: Any,
    *,
    base_url: str,
    require_domain_query: bool,
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(base_url)
    if (
        parts.scheme != "https"
        or parts.hostname != expected.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port != expected.port
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.fragment
    ):
        return None
    query = parse_qs(parts.query, keep_blank_values=True)
    if require_domain_query and query != {"domain": [BAYER_DOMAIN]}:
        return None
    if not require_domain_query and query not in ({}, {"domain": [BAYER_DOMAIN]}):
        return None
    normalized_query = f"domain={BAYER_DOMAIN}" if query else ""
    return urlunsplit(
        ("https", expected.netloc.casefold(), parts.path.rstrip("/"), normalized_query, "")
    )


def extract_url_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group("id") if match else None


def extract_job_id(record: dict[str, Any]) -> str:
    value = record.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ""
    normalized = str(value).strip()
    return normalized if normalized.isdigit() else ""


def is_swiss_location(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and text.casefold().endswith(",switzerland"))


def format_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not is_swiss_location(text):
        return None
    return ", ".join(part.strip() for part in text.split(",") if part.strip())


def extract_swiss_listing_location(record: dict[str, Any]) -> str | None:
    locations = [record.get("location"), *sequence_text(record.get("locations"))]
    swiss_locations = [
        formatted for value in locations if (formatted := format_location(value)) is not None
    ]
    return ", ".join(dict.fromkeys(swiss_locations)) if swiss_locations else None


def normalize_employment_type(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    return {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "INTERN": "Internship",
    }.get(text, text.replace("_", " ").title())


def epoch_to_date(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def deduplicate_bayer_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or job.url or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def nested_value(record: dict[str, Any], *keys: str) -> Any:
    value: Any = record
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def sequence_text(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [text for item in value if (text := optional_text(item))]


def comparable_text(value: Any) -> str:
    return " ".join((optional_text(value) or "").casefold().split())


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None
