from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

CUDOS_JOBS_URL = "https://cudos.ch/de/jobs/"
CUDOS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Cudos AG"
EXPECTED_SCHEMA_COMPANY = "Cudos Software Engineers"
JOB_PATH_PATTERN = re.compile(r"^/de/jobs/([a-z0-9][a-z0-9-]*)/$")
DUALOO_APPLY_PATH_PATTERN = re.compile(
    r"^/link/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/apply$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(
    r"^(\d{1,3})(?:\s*[–-]\s*(\d{1,3}))?\s*%\s*\(M/W/D\)$",
    re.IGNORECASE,
)
OFFICE_LOCATIONS = {
    "Zürich": "8951 Fahrweid, Switzerland",
    "Chur": "7000 Chur, Switzerland",
}
SCHEMA_CITY_TO_OFFICE = {"Fahrweid": "Zürich", "Chur": "Chur"}


class CudosParseError(DirectCompanyRequestError):
    pass


class CudosJobsParser:
    """Collect the complete server-rendered Cudos vacancy catalog."""

    parser_id = "cudos"

    def __init__(
        self,
        *,
        base_url: str = CUDOS_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(10, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=CUDOS_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_base_url=self.base_url,
                )
                self.enrich_records(client, records)
        except CudosParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Cudos vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Cudos vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_cudos_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Cudos vacancies from the complete official catalog"),
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
                    expected_base_url=self.base_url,
                )
            except (httpx.HTTPError, CudosParseError, ValueError) as exc:
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
        public_url = optional_text(record.get("url"))
        workload = optional_text(record.get("workload"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=optional_text(detail.get("location")) or "Switzerland",
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(f"Full-time · {workload}" if workload else "Full-time"),
            seniority=infer_seniority(record.get("title")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_base_url: str,
) -> list[dict[str, Any]]:
    if canonical_catalog_url(page_url) != canonical_catalog_url(expected_base_url):
        raise CudosParseError("Cudos catalog redirected to an unexpected page")

    page = Selector(page_html)
    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    if canonical_catalog_url(canonical) != canonical_catalog_url(expected_base_url):
        raise CudosParseError("Cudos catalog has an unexpected canonical URL")
    validate_organization_schema(page)

    catalogs = page.css(".app-content-plugin-32118")
    if len(catalogs) != 1:
        raise CudosParseError("Cudos listing is missing its official vacancy catalog")
    catalog = catalogs[0]
    ajax_base = optional_text(
        catalog.css(".filter-container::attr(data-ajax-filter-base-url)").get()
    )
    filters = {
        (optional_text(option.css("::attr(value)").get()), selector_text(option))
        for option in catalog.css("select#category option")
        if optional_text(option.css("::attr(value)").get())
    }
    if ajax_base != "/de/jobs/1/?plugin_id=32118" or filters != {
        ("76", "Standort Zürich"),
        ("77", "Standort Chur"),
    }:
        raise CudosParseError("Cudos listing has an unexpected catalog configuration")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in catalog.css(".css-grid__item"):
        href = optional_text(card.css("a.teaser::attr(href)").get())
        url = canonical_job_url(urljoin(page_url, href or ""), expected_base_url)
        job_id = extract_job_id(url, expected_base_url=expected_base_url)
        title = selector_text(card, "h3.text--h4")
        workload_label = selector_text(card, ".teaser__content > span.text--medium")
        workload = normalize_workload(workload_label)
        if not job_id or not url or not title or not workload:
            raise CudosParseError("Cudos listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise CudosParseError("Cudos listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": EXPECTED_COMPANY,
                "url": url,
                "workload": workload,
                "workload_label": workload_label,
            }
        )

    seo_catalogs = page.css(".app-content-plugin-26416")
    if len(seo_catalogs) != 1:
        raise CudosParseError("Cudos listing is missing its catalog cross-check")
    seo_records = {
        canonical_job_url(urljoin(page_url, str(href)), expected_base_url): title
        for link in seo_catalogs[0].css("a[href]")
        if (href := optional_text(link.css("::attr(href)").get()))
        if (title := selector_text(link, ".button-label"))
    }
    primary_records = {record["url"]: record["title"] for record in records}
    if seo_records != primary_records:
        raise CudosParseError("Cudos catalog representations do not match")
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
    expected_base_url: str,
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"), expected_base_url)
    if canonical_job_url(page_url, expected_base_url) != expected_url:
        raise CudosParseError("Cudos detail page returned a different vacancy")

    page = Selector(page_html)
    canonical = canonical_job_url(
        page.css('link[rel="canonical"]::attr(href)').get(),
        expected_base_url,
    )
    title = selector_text(page, "h1.text--h2")
    workload_label = selector_text(
        page,
        ".hero-content__background .text-container > p.text--h6",
    )
    workload = normalize_workload(workload_label)
    if (
        canonical != expected_url
        or comparable_text(title) != comparable_text(expected_record.get("title"))
        or workload != expected_record.get("workload")
    ):
        raise CudosParseError("Cudos detail page contains a mismatched vacancy")
    validate_organization_schema(page)

    description = extract_description(page)
    apply_links = extract_apply_links(page)
    if not description or not apply_links:
        raise CudosParseError("Cudos detail page contains an incomplete vacancy")
    office_names = order_offices(apply_links)
    location = "; ".join(OFFICE_LOCATIONS[name] for name in office_names)
    apply_urls = list(dict.fromkeys(apply_links.values()))
    apply_url = apply_urls[0] if len(apply_urls) == 1 else expected_url

    metadata = extract_jobposting_metadata(page)
    if metadata is not None and set(metadata["offices"]) != set(office_names):
        raise CudosParseError("Cudos JobPosting locations do not match its apply links")
    return {
        "id": expected_record.get("id"),
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": location,
        "public_url": expected_url,
        "apply_url": apply_url,
        "apply_urls": apply_urls,
        "applications": apply_links,
        "posted_at": metadata.get("posted_at") if metadata else None,
        "employment_type": metadata.get("employment_type") if metadata else None,
        "description": description,
        "jobposting": metadata,
    }


def validate_organization_schema(page: Any) -> None:
    organizations = [
        candidate
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        if (candidate := parse_json_document(raw, strict=True))
        if candidate.get("@type") == "Organization"
    ]
    if len(organizations) != 1:
        raise CudosParseError("Cudos page is missing its Organization data")
    organization = organizations[0]
    if organization.get("name") != "Cudos" or organization.get("url") != "https://cudos.ch":
        raise CudosParseError("Cudos page contains unexpected Organization data")


def extract_description(page: Any) -> str | None:
    parts: list[str] = []
    for block in page.css(".content-plugin.text-plugin.text-container"):
        heading = selector_text(block, "h2.text--h4")
        if not heading:
            continue
        if heading == "Jetzt bewerben":
            break
        parts.append(heading)
        for node in block.css("p, li"):
            if node.css('script[type="application/ld+json"]'):
                continue
            text = selector_text(node)
            if not text:
                continue
            parts.append(f"- {text}" if node.tag == "li" else text)
    return optional_multiline_text("\n".join(dict.fromkeys(parts)))


def extract_apply_links(page: Any) -> dict[str, str]:
    links: dict[str, str] = {}
    for link in page.css('a[href*="jobs.dualoo.com/link/"]'):
        label = selector_text(link, ".button-label")
        match = re.fullmatch(r"Bewerben für (Zürich|Chur)", label or "")
        url = normalize_apply_url(link.css("::attr(href)").get())
        if not match or not url or match.group(1) in links:
            return {}
        links[match.group(1)] = url
    return links


def extract_jobposting_metadata(page: Any) -> dict[str, Any] | None:
    schemas = [
        candidate
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        for candidate in parse_json_objects(raw, strict=False)
        if candidate.get("@type") == "JobPosting"
    ]
    if not schemas:
        return None
    if len(schemas) != 1:
        raise CudosParseError("Cudos detail page contains multiple JobPosting records")
    schema = schemas[0]
    company = nested_value(schema, "hiringOrganization", "name")
    posted_at = normalize_date(schema.get("datePosted"))
    employment_type = optional_text(schema.get("employmentType"))
    direct_apply = optional_text(schema.get("directApply"))
    offices = normalize_schema_offices(schema.get("jobLocation"))
    if (
        company != EXPECTED_SCHEMA_COMPANY
        or not posted_at
        or employment_type != "FULL_TIME"
        or direct_apply != "TRUE"
        or not offices
    ):
        raise CudosParseError("Cudos JobPosting data is incomplete or unexpected")
    return {
        "posted_at": posted_at,
        "employment_type": "Full-time",
        "offices": offices,
        "schema": schema,
    }


def normalize_schema_offices(value: Any) -> list[str]:
    locations = value if isinstance(value, list) else [value]
    offices: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            return []
        address = location.get("address")
        if not isinstance(address, dict):
            return []
        country = optional_text(address.get("addressCountry"))
        city = optional_text(address.get("addressLocality"))
        office = SCHEMA_CITY_TO_OFFICE.get(city or "")
        if country != "Schweiz" or not office:
            return []
        offices.append(office)
    return list(dict.fromkeys(offices)) if len(offices) == len(set(offices)) else []


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.dualoo.com"
        or not DUALOO_APPLY_PATH_PATTERN.fullmatch(parts.path)
        or query != {"lang": ["DE"]}
    ):
        return None
    return urlunsplit(("https", "jobs.dualoo.com", parts.path, "lang=DE", ""))


def canonical_catalog_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "cudos.ch"
        or parts.path != "/de/jobs/"
        or parts.query
        or parts.fragment
    ):
        return None
    return CUDOS_JOBS_URL


def canonical_job_url(value: Any, expected_base_url: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(expected_base_url)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected.netloc.casefold()
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", expected.netloc.casefold(), parts.path, "", ""))


def extract_job_id(value: str | None, *, expected_base_url: str) -> str | None:
    url = canonical_job_url(value, expected_base_url)
    if not url:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path)
    return match.group(1) if match else None


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    match = WORKLOAD_PATTERN.fullmatch(text or "")
    if not match:
        return None
    start, end = match.groups()
    if not 1 <= int(start) <= 100 or (end and not int(start) <= int(end) <= 100):
        return None
    return f"{start}-{end}%" if end else f"{start}%"


def infer_seniority(value: Any) -> str | None:
    title = optional_text(value)
    if not title:
        return None
    if re.search(r"\bjunior\b", title, re.IGNORECASE):
        return "Junior"
    if re.search(r"\bsenior\b", title, re.IGNORECASE):
        return "Senior"
    return None


def order_offices(value: dict[str, str]) -> list[str]:
    return [office for office in OFFICE_LOCATIONS if office in value]


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def parse_json_objects(value: Any, *, strict: bool) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(str(value), strict=strict)
    except (TypeError, json.JSONDecodeError):
        return
    yield from walk_json(payload)


def parse_json_document(value: Any, *, strict: bool) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(value), strict=strict)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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


def selector_text(node: Any, css: str | None = None) -> str | None:
    selected = node.css(css)[0] if css and node.css(css) else node
    return optional_text(" ".join(str(value) for value in selected.css("::text").getall()))


def comparable_text(value: Any) -> str:
    text = optional_text(value)
    return re.sub(r"[^a-z0-9]+", "", text.casefold() if text else "")


def deduplicate_cudos_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
