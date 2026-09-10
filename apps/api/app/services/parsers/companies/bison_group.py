from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BISON_GROUP_JOBS_BASE_URL = "https://www.bison-group.com/karriere/offene-stellen/"
BISON_GROUP_JOBS_API_URL = "https://ohws.prospective.ch/public/v1/medium/1008012/jobs"
BISON_GROUP_MEDIUM_ID = "1008012"
BISON_GROUP_RESULTS_PER_PAGE = 96
BISON_GROUP_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
HREF_PATTERN = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
SWISS_COUNTRIES = {"ch", "schweiz", "switzerland", "suisse", "svizzera"}
KNOWN_COUNTRIES = {*SWISS_COUNTRIES, "de", "deutschland", "germany", "allemagne"}


class BisonGroupParseError(DirectCompanyRequestError):
    pass


class BisonGroupJobsParser:
    """Collect Bison Group vacancies available in Switzerland."""

    parser_id = "bison_group"

    def __init__(
        self,
        *,
        base_url: str = BISON_GROUP_JOBS_BASE_URL,
        api_url: str = BISON_GROUP_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **BISON_GROUP_HEADERS,
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                catalog, page_requests, total = self.collect_listing_records(client)
                records = [record for record in catalog if is_swiss_record(record)]
                self.enrich_records(client, records)
        except BisonGroupParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Bison Group vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Bison Group vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bison_group_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Bison Group Swiss vacancies from {total} "
                f"global catalog records across {page_requests} API page requests"
            ),
        )

    def fetch_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.get(
            self.api_url,
            params={
                "lang": "de",
                "offset": offset,
                "limit": BISON_GROUP_RESULTS_PER_PAGE,
            },
        )
        response.raise_for_status()
        page_offset, total, records = parse_listing_payload(response.json())
        if page_offset != offset:
            raise BisonGroupParseError(
                f"Bison Group returned offset {page_offset} for requested offset {offset}"
            )
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        page_requests = 0
        last_total = 0
        last_unique = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_page(client, offset=0)
            page_requests += 1
            expected_total = first_page[1]
            last_total = expected_total
            required_pages = max(
                1,
                ceil(expected_total / BISON_GROUP_RESULTS_PER_PAGE),
            )
            if required_pages > self.max_pages:
                raise BisonGroupParseError(
                    f"Bison Group exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            pages = [first_page]
            for offset in range(
                BISON_GROUP_RESULTS_PER_PAGE,
                expected_total,
                BISON_GROUP_RESULTS_PER_PAGE,
            ):
                pages.append(self.fetch_page(client, offset=offset))
                page_requests += 1

            records_by_id: dict[str, dict[str, Any]] = {}
            records_seen = 0
            catalog_changed = False
            for offset, page_total, page_records in pages:
                if page_total != expected_total or (offset < expected_total and not page_records):
                    catalog_changed = True
                    break
                records_seen += len(page_records)
                for record in page_records:
                    job_id = str(record["id"])
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)

            last_unique = len(records_by_id)
            if catalog_changed or records_seen != expected_total:
                continue
            if last_unique == expected_total:
                return list(records_by_id.values()), page_requests, expected_total

        raise BisonGroupParseError(
            f"Bison Group yielded only {last_unique} unique vacancies of {last_total} "
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
            try:
                response = client.get(
                    record["links"]["directlink"],
                    headers={
                        "Accept": (
                            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                        ),
                        "Referer": self.base_url,
                    },
                )
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    expected_title=optional_text(record.get("title")),
                    expected_viewkey=optional_text(record.get("viewkey")),
                )
                return record, detail
            except (httpx.HTTPError, BisonGroupParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        attributes = record.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        szas = record.get("szas")
        szas = szas if isinstance(szas, dict) else {}
        links = record.get("links")
        links = links if isinstance(links, dict) else {}
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        public_url = optional_text(links.get("directlink")) or self.base_url

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="Bison Schweiz AG",
            location=extract_location(szas) or optional_text(detail.get("location")),
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url"))
                or optional_text(szas.get("sza_apply_link"))
                or public_url
            ),
            posted_at=(
                optional_text(detail.get("posted_at")) or optional_text(record.get("start_date"))
            ),
            employment_type=extract_employment_type(
                szas,
                schema_type=detail.get("employment_type"),
            ),
            seniority=(optional_text(szas.get("sza_role")) or first_text(attributes.get("20"))),
            description=(
                optional_multiline_text(detail.get("description")) or extract_description(szas)
            ),
            raw=dict(record),
        )


def parse_listing_payload(payload: Any) -> tuple[int, int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise BisonGroupParseError("Bison Group jobs response must be an object")
    total = payload.get("total")
    offset = payload.get("offset")
    jobs = payload.get("jobs")
    if optional_text(payload.get("medium_id")) != BISON_GROUP_MEDIUM_ID:
        raise BisonGroupParseError("Bison Group jobs response has another medium ID")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise BisonGroupParseError("Bison Group jobs response has an invalid total")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise BisonGroupParseError("Bison Group jobs response has an invalid offset")
    if not isinstance(jobs, list):
        raise BisonGroupParseError("Bison Group jobs response has invalid jobs")
    return offset, total, [validate_listing_record(item) for item in jobs]


def validate_listing_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BisonGroupParseError("Bison Group catalog contains an invalid vacancy")
    job_id = optional_text(value.get("id"))
    viewkey = optional_text(value.get("viewkey"))
    title = optional_text(value.get("title"))
    attributes = value.get("attributes")
    szas = value.get("szas")
    links = value.get("links")
    directlink = links.get("directlink") if isinstance(links, dict) else None
    apply_url = szas.get("sza_apply_link") if isinstance(szas, dict) else None
    locations = all_location_values(szas) if isinstance(szas, dict) else []
    if (
        not job_id
        or not job_id.isdigit()
        or not viewkey
        or not UUID_PATTERN.fullmatch(viewkey)
        or not title
        or not isinstance(attributes, dict)
        or not first_text(attributes.get("30"))
        or not isinstance(szas, dict)
        or (
            optional_text(szas.get("sza_department")) != "Bison"
            and not (
                optional_text(szas.get("sza_department")) is None
                and optional_text(value.get("hk_id")) == "1007218"
            )
        )
        or not locations
        or not all(has_known_country(location) for location in locations)
        or not extract_description(szas)
        or not valid_directlink(directlink, expected_viewkey=viewkey)
        or not valid_talentsoft_apply_url(apply_url)
        or not valid_iso_datetime(value.get("start_date"))
        or optional_text(value.get("language")) != "de"
    ):
        raise BisonGroupParseError("Bison Group catalog contains an incomplete vacancy")
    return dict(value)


def parse_detail_html(
    page_html: str,
    *,
    expected_title: str | None,
    expected_viewkey: str | None,
) -> dict[str, Any]:
    schema = next(extract_job_posting_schemas(page_html), {})
    title = optional_text(html.unescape(str(schema.get("title", ""))))
    organization = schema.get("hiringOrganization")
    organization_name = (
        optional_text(organization.get("name")) if isinstance(organization, dict) else None
    )
    description = html_to_text(schema.get("description"))
    location = extract_schema_location(schema)
    apply_url = next(
        (
            html.unescape(link)
            for link in HREF_PATTERN.findall(page_html)
            if valid_prospective_apply_url(link, expected_viewkey=expected_viewkey)
        ),
        None,
    )
    if (
        not title
        or title.casefold() != (expected_title or "").casefold()
        or organization_name != "Bison Schweiz AG"
        or not description
        or not location
        or not apply_url
        or not valid_date(schema.get("datePosted"))
    ):
        raise BisonGroupParseError("Bison Group detail page is incomplete or inconsistent")
    return {
        "title": title,
        "company": organization_name,
        "location": location,
        "apply_url": apply_url,
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "employment_type": schema.get("employmentType"),
        "description": description,
        "schema": schema,
    }


def extract_job_posting_schemas(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError, ValueError):
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


def is_swiss_record(record: dict[str, Any]) -> bool:
    szas = record.get("szas")
    return isinstance(szas, dict) and bool(swiss_location_values(szas))


def all_location_values(szas: dict[str, Any]) -> list[str]:
    return [
        location
        for suffix in ("", ".2", ".3")
        if (location := optional_text(szas.get(f"sza_location{suffix}")))
    ]


def swiss_location_values(szas: dict[str, Any]) -> list[str]:
    return [
        location
        for location in all_location_values(szas)
        if contains_country(location, SWISS_COUNTRIES)
    ]


def extract_location(szas: dict[str, Any]) -> str | None:
    cities: list[str] = []
    for suffix in ("", ".2", ".3"):
        location = optional_text(szas.get(f"sza_location{suffix}"))
        if not location or not contains_country(location, SWISS_COUNTRIES):
            continue
        city = optional_text(szas.get(f"sza_location{suffix}.city"))
        value = f"{city}, Schweiz" if city else location
        if value not in cities:
            cities.append(value)
    return "; ".join(cities) or None


def extract_schema_location(schema: dict[str, Any]) -> str | None:
    value = schema.get("jobLocation")
    locations = (
        value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    )
    results: list[str] = []
    for location in locations:
        address = location.get("address") if isinstance(location, dict) else None
        if not isinstance(address, dict):
            continue
        country = optional_text(address.get("addressCountry"))
        if not country or country.casefold() not in SWISS_COUNTRIES:
            continue
        locality = optional_text(address.get("addressLocality"))
        result = ", ".join(part for part in (locality, country) if part)
        if result and result not in results:
            results.append(result)
    return "; ".join(results) or None


def extract_employment_type(
    szas: dict[str, Any],
    *,
    schema_type: Any,
) -> str | None:
    employment = optional_text(szas.get("sza_employment_type"))
    schema_employment = normalize_schema_employment(schema_type)
    workload = optional_text(szas.get("sza_pensum"))
    minimum = optional_text(szas.get("sza_pensum.min"))
    maximum = optional_text(szas.get("sza_pensum.max"))
    if minimum and maximum:
        percentage = f"{minimum}%" if minimum == maximum else f"{minimum}–{maximum}%"
        workload = ", ".join(dict.fromkeys(item for item in (workload, percentage) if item))
    return (
        ", ".join(dict.fromkeys(item for item in (employment, schema_employment, workload) if item))
        or None
    )


def normalize_schema_employment(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [normalize_schema_employment(item) for item in value]
        return ", ".join(dict.fromkeys(item for item in values if item)) or None
    text = optional_text(value)
    if not text:
        return None
    return {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
    }.get(text.upper(), text.replace("_", " ").title())


def extract_description(szas: dict[str, Any]) -> str | None:
    sections: list[str] = []
    for label, key in (
        ("Einleitung", "sza_introduction"),
        ("Aufgaben", "sza_tasks"),
        ("Anforderungen", "sza_requirements"),
        ("Über Bison", "sza_company_profil"),
    ):
        content = html_to_text(szas.get(key))
        if content:
            sections.append(f"{label}\n{content}")
    return "\n\n".join(sections) or None


def valid_directlink(value: Any, *, expected_viewkey: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.hostname == "ohws.prospective.ch"
        and parts.path == f"/public/v1/jobs/{expected_viewkey}"
    )


def valid_prospective_apply_url(value: Any, *, expected_viewkey: str | None) -> bool:
    text = optional_text(value)
    if not text or not expected_viewkey:
        return False
    parts = urlsplit(html.unescape(text))
    return (
        parts.scheme == "https"
        and parts.hostname == "ohws.prospective.ch"
        and parts.path == f"/public/v1/redirect/{expected_viewkey}/ats/"
    )


def valid_talentsoft_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    return (
        parts.scheme == "https"
        and parts.hostname == "fenaco-career.talent-soft.com"
        and parts.path.casefold() == "/pages/offre/detailoffre.aspx"
        and bool(query.get("idOffre"))
        and query.get("action") == ["jobapplication"]
    )


def has_known_country(location: str) -> bool:
    return contains_country(location, KNOWN_COUNTRIES)


def contains_country(value: str, countries: set[str]) -> bool:
    folded = value.casefold()
    return any(
        re.search(rf"(?:^|[,\s]){re.escape(country)}(?:$|[,\s])", folded) for country in countries
    )


def valid_iso_datetime(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


def valid_date(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def deduplicate_bison_group_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    text = optional_text(value)
    if not text:
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(
        r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>",
        "\n",
        text,
    )
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def first_text(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return next((text for item in value if (text := optional_text(item))), None)
    return optional_text(value)


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None
