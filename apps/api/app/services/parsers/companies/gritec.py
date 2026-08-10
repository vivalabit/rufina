from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

GRITEC_CAREERS_URL = "https://www.gritec.ch/en/career"
GRITEC_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
PORTAL_PATH_PATTERN = re.compile(r"^/portal/([a-z0-9]{8})/?$", re.IGNORECASE)
DETAIL_PATH_PATTERN = re.compile(
    r"^/portal/([a-z0-9]{8})/([0-9a-f-]{36})/detail/?$",
    re.IGNORECASE,
)
EXPECTED_CATALOG_SECTIONS = {
    "vacancy",
    "apprenticeship",
    "placement",
    "unsolicited",
}


class GritecParseError(DirectCompanyRequestError):
    pass


class GritecJobsParser:
    """Collect every Swiss job catalog embedded on the GRITEC career page."""

    parser_id = "gritec"

    def __init__(
        self,
        *,
        base_url: str = GRITEC_CAREERS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**GRITEC_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                portals = parse_career_page(response.text)
                records: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                for portal in portals:
                    portal_response = client.get(
                        portal["url"],
                        headers={"Referer": self.base_url},
                    )
                    portal_response.raise_for_status()
                    portal_records = parse_portal_html(
                        portal_response.text,
                        page_url=str(portal_response.url),
                        expected_portal_id=portal["portal_id"],
                        catalog_section=portal["catalog_section"],
                        catalog_title=portal["catalog_title"],
                    )
                    duplicate_ids = seen_ids.intersection(record["id"] for record in portal_records)
                    if duplicate_ids:
                        raise GritecParseError("GRITEC catalogs contain duplicate vacancy IDs")
                    seen_ids.update(record["id"] for record in portal_records)
                    records.extend(portal_records)
                self.enrich_records(client, records)
        except GritecParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("GRITEC vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("GRITEC vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_gritec_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} GRITEC Switzerland opportunities from the official catalog"
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
                response = client.get(
                    record["url"],
                    headers={"Referer": record["listing_page_url"]},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_portal_id=record["portal_id"],
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, GritecParseError, ValueError) as exc:
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
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(detail.get("company")) or "GRITEC AG",
            location=(
                optional_text(detail.get("location"))
                or normalize_listing_location(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(
                optional_text(detail.get("employment_type"))
                or fallback_employment_type(record.get("catalog_section"))
            ),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_career_page(page_html: str) -> list[dict[str, str]]:
    page = Selector(page_html)
    portal_sections = page.css(".node--type-stellenportal")
    portals: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for section in portal_sections:
        title = selector_text(section, ".field--name-title")
        portal_url = optional_text(section.css("iframe.dualooFrame::attr(src)").get())
        portal_id = extract_portal_id(portal_url)
        catalog_section = classify_catalog(title)
        if not title or not portal_url or not portal_id or not catalog_section:
            raise GritecParseError("GRITEC career page contains an invalid job portal")
        if portal_id in seen_ids:
            raise GritecParseError("GRITEC career page contains duplicate job portals")
        seen_ids.add(portal_id)
        portals.append(
            {
                "portal_id": portal_id,
                "url": portal_url,
                "catalog_section": catalog_section,
                "catalog_title": title,
            }
        )

    if {portal["catalog_section"] for portal in portals} != EXPECTED_CATALOG_SECTIONS:
        raise GritecParseError("GRITEC career page is missing an expected job portal")
    return portals


def parse_portal_html(
    page_html: str,
    *,
    page_url: str,
    expected_portal_id: str,
    catalog_section: str,
    catalog_title: str,
) -> list[dict[str, Any]]:
    page = Selector(page_html)
    portal_id = optional_text(page.css("#jobPortalUrl::attr(value)").get())
    if portal_id != expected_portal_id or not page.css(".JobInfoBox").get():
        raise GritecParseError("GRITEC Dualoo portal returned unexpected content")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css(".JobInfoBox a.jobElement"):
        detail_path = optional_text(card.attrib.get("href"))
        detail_url = urljoin(page_url, detail_path) if detail_path else None
        path_ids = extract_detail_ids(detail_url)
        title = selector_text(card, ".jobName")
        location = selector_text(card, ".cityName")
        category = selector_text(card, ".jobCategory")
        if (
            not path_ids
            or path_ids[0] != expected_portal_id
            or not title
            or not normalize_listing_location(location)
        ):
            raise GritecParseError("GRITEC catalog contains an incomplete or non-Swiss opportunity")
        job_id = path_ids[1]
        if job_id in seen_ids:
            raise GritecParseError("GRITEC portal contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "portal_id": expected_portal_id,
                "title": title,
                "location": location,
                "category": category,
                "catalog_section": catalog_section,
                "catalog_title": catalog_title,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_portal_id: str,
    expected_job_id: str,
) -> dict[str, Any]:
    path_ids = extract_detail_ids(page_url)
    if path_ids != (expected_portal_id, expected_job_id):
        raise GritecParseError("GRITEC detail page returned a different opportunity")

    page = Selector(page_html)
    schemas = list(extract_job_posting_schemas(page))
    if len(schemas) != 1:
        raise GritecParseError("GRITEC detail page is missing its JobPosting data")
    schema = schemas[0]
    title = optional_text(schema.get("title"))
    company = extract_company(schema)
    locations = extract_swiss_locations(schema.get("jobLocation"))
    description = combine_description(schema)
    apply_path = optional_text(page.css("a.btn-apply::attr(href)").get())
    apply_url = urljoin(page_url, apply_path) if apply_path else None
    if (
        not title
        or not company
        or "gritec" not in company.casefold()
        or not locations
        or not description
        or not is_matching_apply_url(
            apply_url,
            portal_id=expected_portal_id,
            job_id=expected_job_id,
        )
    ):
        raise GritecParseError("GRITEC detail page contains an incomplete or non-Swiss opportunity")

    return {
        "id": expected_job_id,
        "title": title,
        "company": company,
        "location": "; ".join(locations),
        "apply_url": apply_url,
        "posted_at": optional_text(schema.get("datePosted")),
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
            if candidate.get("@type") == "JobPosting":
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def classify_catalog(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    lowered = text.casefold()
    if "professional experience" in lowered:
        return "vacancy"
    if "apprenticeship" in lowered or "orientation course" in lowered:
        return "apprenticeship"
    if "university" in lowered or "placement" in lowered:
        return "placement"
    if "spontaneous" in lowered or "unsolicited" in lowered:
        return "unsolicited"
    return None


def extract_portal_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = PORTAL_PATH_PATTERN.fullmatch(parts.path)
    if parts.scheme != "https" or parts.netloc.casefold() != "jobs.dualoo.com" or not match:
        return None
    return match.group(1).casefold()


def extract_detail_ids(value: Any) -> tuple[str, str] | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    if parts.scheme != "https" or parts.netloc.casefold() != "jobs.dualoo.com" or not match:
        return None
    return match.group(1).casefold(), match.group(2).casefold()


def is_matching_apply_url(value: Any, *, portal_id: str, job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    expected_path = f"/portal/{portal_id}/{job_id}/apply"
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.dualoo.com"
        and parts.path.rstrip("/").casefold() == expected_path.casefold()
    )


def extract_company(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    if not isinstance(organization, dict):
        return None
    return optional_text(organization.get("name"))


def extract_swiss_locations(value: Any) -> list[str]:
    locations = value if isinstance(value, list) else [value]
    normalized: list[str] = []
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
            "svizzera",
        }:
            continue
        locality = optional_text(address.get("addressLocality"))
        if not locality:
            continue
        label = f"{locality}, Switzerland"
        if label not in normalized:
            normalized.append(label)
    return normalized


def normalize_listing_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    compact = re.sub(r"[^a-z]", "", text.casefold())
    if "grüsch" in text.casefold() or "grusch" in compact:
        return "Grüsch, Switzerland"
    if "kriens" in compact:
        return "Kriens, Switzerland"
    return None


def combine_description(schema: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("description", "responsibilities", "skills", "qualifications", "jobBenefits"):
        value = optional_text(schema.get(key))
        text = html_to_text(value or "")
        if text and text not in parts:
            parts.append(text)
    return "\n\n".join(parts) or None


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
        "VOLUNTEER": "Volunteer",
        "PER_DIEM": "Per diem",
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


def fallback_employment_type(value: Any) -> str | None:
    return {
        "apprenticeship": "Apprenticeship",
        "placement": "Internship",
        "unsolicited": "Unsolicited application",
    }.get(optional_text(value) or "")


def deduplicate_gritec_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        path_ids = extract_detail_ids(job.url)
        key = path_ids[1] if path_ids else job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


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
