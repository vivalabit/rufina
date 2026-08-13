from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SIKA_SWITZERLAND_JOBS_BASE_URL = "https://www.sika.com/en/career/jobs.html"
SIKA_SWITZERLAND_JOBS_CATALOG_URL = (
    "https://www.sika.com/en/career/jobs/_jcr_content/content/"
    "layoutcontainer_1337473725/first/jobposting.listing.json"
)
SIKA_HEADERS = {
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(
    r"^/en/career/jobs/job-posting-page/jid-([0-9a-f-]{36})\.html$",
    re.IGNORECASE,
)
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
SMARTRECRUITERS_PATH_PATTERN = re.compile(r"^/SikaAG/[^/]+/?$", re.IGNORECASE)
SWISS_COUNTRY_VALUES = {"ch", "che", "switzerland", "schweiz", "suisse", "svizzera"}


class SikaSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SikaSwitzerlandJobsParser:
    """Collect Sika's complete Switzerland catalog from its official AEM API."""

    parser_id = "sika_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SIKA_SWITZERLAND_JOBS_BASE_URL,
        catalog_url: str = SIKA_SWITZERLAND_JOBS_CATALOG_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**SIKA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SikaSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Sika Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Sika Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_sika_switzerland_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Sika Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} API {request_label}"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0
        catalog_host = urlsplit(self.catalog_url).netloc.casefold()

        # Offset pages can move while a vacancy is published. Repeat the walk
        # and union stable Sika UUIDs until the declared catalog is complete.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            offset = 0
            seen_offsets: set[int] = set()
            page_number = 0

            while True:
                if offset in seen_offsets:
                    raise SikaSwitzerlandParseError(
                        "Sika Switzerland pagination returned a repeated offset"
                    )
                seen_offsets.add(offset)
                page_number += 1
                if page_number > self.max_pages:
                    raise SikaSwitzerlandParseError(
                        "Sika Switzerland catalog exceeds the configured limit "
                        f"of {self.max_pages} pages"
                    )

                response = client.get(
                    self.catalog_url,
                    params={"country": "ch", "offset": offset},
                )
                pages_fetched += 1
                response.raise_for_status()
                total, next_offset, records = parse_listing_payload(
                    response.json(),
                    page_url=str(response.url),
                    expected_host=catalog_host,
                    current_offset=offset,
                )

                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise SikaSwitzerlandParseError(
                        "Sika Switzerland changed its vacancy total during pagination"
                    )

                for record in records:
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

                if len(records_by_id) > expected_total:
                    raise SikaSwitzerlandParseError(
                        "Sika Switzerland catalog changed while pages were collected"
                    )
                if next_offset is None:
                    break
                offset = next_offset

            if len(records_by_id) == (expected_total or 0):
                return list(records_by_id.values()), pages_fetched, expected_total or 0

        raise SikaSwitzerlandParseError(
            f"Sika Switzerland returned {len(records_by_id)} unique vacancies but "
            f"declared {expected_total or 0}"
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
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                    expected_location=record["location"],
                )
            except (httpx.HTTPError, SikaSwitzerlandParseError, ValueError) as exc:
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
        tags = record.get("tags")
        tags = tags if isinstance(tags, list) else []
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="Sika AG",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(optional_text(detail.get("employment_type")) or first_text(tags)),
            seniority=optional_text(detail.get("seniority")),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("description"))
            ),
            raw=dict(record),
        )


def parse_listing_payload(
    payload: Any,
    *,
    page_url: str,
    expected_host: str,
    current_offset: int,
) -> tuple[int, int | None, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise SikaSwitzerlandParseError("Sika Switzerland catalog response must be an object")
    total = payload.get("totalItems")
    next_offset = payload.get("nextOffset")
    items = payload.get("items")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise SikaSwitzerlandParseError("Sika Switzerland catalog response has an invalid total")
    if next_offset is not None and (
        isinstance(next_offset, bool)
        or not isinstance(next_offset, int)
        or next_offset <= current_offset
        or next_offset > total
    ):
        raise SikaSwitzerlandParseError(
            "Sika Switzerland catalog response has an invalid next offset"
        )
    if not isinstance(items, list):
        raise SikaSwitzerlandParseError("Sika Switzerland catalog response has invalid items")
    if total == 0 and (items or next_offset is not None):
        raise SikaSwitzerlandParseError(
            "Sika Switzerland empty catalog has unexpected pagination data"
        )
    if total > current_offset and not items:
        raise SikaSwitzerlandParseError(
            "Sika Switzerland catalog returned an unexpectedly empty page"
        )
    if next_offset is None and current_offset + len(items) < total:
        raise SikaSwitzerlandParseError(
            "Sika Switzerland catalog stopped before its declared total"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise SikaSwitzerlandParseError("Sika Switzerland catalog contains an invalid vacancy")
        job_id = optional_text(item.get("id"))
        title = optional_text(item.get("title"))
        description = optional_multiline_text(item.get("description"))
        location = optional_text(item.get("location"))
        url = canonical_job_url(item.get("url"), expected_host=expected_host)
        tags = item.get("tags")
        if (
            not job_id
            or not UUID_PATTERN.fullmatch(job_id)
            or not title
            or not description
            or not location
            or not is_swiss_location(location)
            or not url
            or extract_job_id(url) != job_id
            or not isinstance(tags, list)
            or not tags
            or any(not optional_text(tag) for tag in tags)
        ):
            raise SikaSwitzerlandParseError(
                "Sika Switzerland catalog contains an incomplete or non-Swiss vacancy"
            )
        if job_id in seen_ids:
            raise SikaSwitzerlandParseError(
                "Sika Switzerland catalog page contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                **item,
                "id": job_id,
                "title": title,
                "description": description,
                "location": location,
                "url": url,
                "listing_page_url": page_url,
            }
        )
    return total, next_offset, records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_location: str,
) -> dict[str, Any]:
    if extract_job_id(page_url) != expected_job_id:
        raise SikaSwitzerlandParseError("Sika Switzerland detail page returned a different vacancy")

    page = Selector(page_html)
    schemas = list(extract_job_posting_schemas(page))
    if len(schemas) != 1:
        raise SikaSwitzerlandParseError(
            "Sika Switzerland detail page must contain one JobPosting record"
        )
    schema = schemas[0]
    identifier = schema.get("identifier")
    identifier = identifier if isinstance(identifier, dict) else {}
    organization = schema.get("hiringOrganization")
    organization = organization if isinstance(organization, dict) else {}
    schema_id = optional_text(identifier.get("value"))
    title = optional_text(schema.get("title"))
    company = optional_text(organization.get("name"))
    location, country = extract_schema_location(schema.get("jobLocation"))
    if schema_id != expected_job_id:
        raise SikaSwitzerlandParseError("Sika Switzerland detail page returned a different vacancy")
    if (
        comparable_text(title) != comparable_text(expected_title)
        or not company
        or "sika" not in company.casefold()
        or not location
        or not country
        or country.casefold() not in SWISS_COUNTRY_VALUES
        or comparable_text(location) != comparable_text(expected_location)
    ):
        raise SikaSwitzerlandParseError(
            "Sika Switzerland detail page contains incomplete, mismatched, or "
            "non-Swiss vacancy data"
        )

    apply_url = canonical_apply_url(
        page.css('a[href*="jobs.smartrecruiters.com/SikaAG/"]::attr(href)').get()
    )
    description = extract_detail_description(page)
    if not apply_url or not description:
        raise SikaSwitzerlandParseError(
            "Sika Switzerland detail page is missing its application or description"
        )
    return {
        "title": title,
        "company": company,
        "location": location,
        "apply_url": apply_url,
        "posted_at": normalize_date(schema.get("datePosted")),
        "employment_type": optional_text(schema.get("employmentType")),
        "seniority": optional_text(schema.get("experienceRequirements")),
        "description": description,
        "schema": schema,
    }


def extract_job_posting_schemas(page: Any) -> Iterator[dict[str, Any]]:
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(html.unescape(str(raw)))
        except (TypeError, json.JSONDecodeError):
            continue
        yield from (
            candidate for candidate in walk_json(payload) if candidate.get("@type") == "JobPosting"
        )


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_schema_location(value: Any) -> tuple[str | None, str | None]:
    locations = value if isinstance(value, list) else [value]
    labels: list[str] = []
    countries: list[str] = []
    for item in locations:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        address = address if isinstance(address, dict) else {}
        country = optional_text(address.get("addressCountry"))
        locality = optional_text(address.get("addressLocality"))
        region = optional_text(address.get("addressRegion"))
        if country:
            countries.append(country)
        parts = [part for part in (locality, region, "Switzerland") if part]
        label = ", ".join(dict.fromkeys(parts))
        if label and label not in labels:
            labels.append(label)
    unique_countries = list(dict.fromkeys(countries))
    if len(unique_countries) != 1:
        return None, None
    return "; ".join(labels) or None, unique_countries[0]


def extract_detail_description(page: Any) -> str | None:
    sections = (
        (".cmp-job-posting-details__description", "About the Role"),
        (".cmp-job-posting-details__qualifications", "Your Skills and Experience"),
        (".cmp-job-posting-details__additional-information", "Why Join Us"),
        (".cmp-job-posting-details__company-description", "About Sika"),
    )
    parts: list[str] = []
    for selector, heading in sections:
        bodies = [text for node in page.css(selector) if (text := html_to_text(node.get()))]
        if bodies:
            parts.append(f"{heading}\n" + "\n\n".join(bodies))
    return optional_multiline_text("\n\n".join(parts))


def canonical_job_url(value: Any, *, expected_host: str | None = None) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or (expected_host and parts.netloc.casefold() != expected_host)
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", parts.netloc.casefold(), parts.path, "", ""))


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1).casefold() if match else None


def canonical_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(html.unescape(text))
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.smartrecruiters.com"
        or not SMARTRECRUITERS_PATH_PATTERN.fullmatch(parts.path)
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.smartrecruiters.com", parts.path, parts.query, ""))


def is_swiss_location(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and re.search(r"(?:^|,\s*)Switzerland$", text, re.IGNORECASE))


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ].*)?", text)
    return match.group(1) if match else None


def deduplicate_sika_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: Any) -> str | None:
    text = str(value or "")
    if not text:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    normalized = optional_multiline_text(text)
    return re.sub(r"\n\n(?=- )", "\n", normalized) if normalized else None


def comparable_text(value: Any) -> str:
    return (
        re.sub(r"[^a-z0-9]+", "", optional_text(value).casefold()) if optional_text(value) else ""
    )


def first_text(values: Iterable[Any]) -> str | None:
    return next((text for value in values if (text := optional_text(value))), None)


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
