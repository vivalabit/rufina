from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

INTERSIM_CAREERS_URL = "https://www.intersim.ch/jobs/"
INTERSIM_PORTAL_URL = "https://jobs.dualoo.com/portal/dlpdkskq?lang=DE"
INTERSIM_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
PORTAL_ID = "dlpdkskq"
EXPECTED_PORTAL_TITLE = "Intersim AG - Offene Stellen"
EXPECTED_COMPANY = "Intersim AG"
EXPECTED_LISTING_LOCATION = "Intersim AG - Burgdorf"
EXPECTED_LOCATION = "Burgdorf, Switzerland"
EXPECTED_CATEGORY = "Mitarbeitende"
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
DETAIL_PATH_PATTERN = re.compile(rf"^/portal/{PORTAL_ID}/({UUID_PATTERN})/detail/?$")
APPLY_PATH_PATTERN = re.compile(rf"^/portal/{PORTAL_ID}/({UUID_PATTERN})/apply/?$")
PUBLIC_JOB_PATH_PATTERN = re.compile(rf"^/jobs/({UUID_PATTERN})/?$")
WORKLOAD_RANGE_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%\s*$")
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*%\s*$")


class IntersimParseError(DirectCompanyRequestError):
    pass


class IntersimJobsParser:
    """Collect Intersim's complete official Dualoo vacancy catalog."""

    parser_id = "intersim"

    def __init__(
        self,
        *,
        base_url: str = INTERSIM_CAREERS_URL,
        portal_url: str = INTERSIM_PORTAL_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.portal_url = portal_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**INTERSIM_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                portal_response = client.get(self.portal_url)
                portal_response.raise_for_status()
                records = parse_portal_html(
                    portal_response.text,
                    page_url=str(portal_response.url),
                    expected_url=self.portal_url,
                    careers_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except IntersimParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Intersim vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Intersim vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_intersim_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Intersim vacancies from the complete official Dualoo catalog"
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
                    record["portal_detail_url"],
                    headers={"Referer": record["listing_page_url"]},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["portal_detail_url"],
                    expected_job_id=record["id"],
                    expected_portal_title=record["portal_title"],
                )
            except (httpx.HTTPError, IntersimParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_portal_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    careers_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise IntersimParseError("Intersim portal returned unexpected content")
    if canonical_careers_url(careers_url) is None:
        raise IntersimParseError("Intersim careers URL is outside the expected scope")

    page = Selector(page_html)
    titles = unique_attribute_values(page, 'meta[property="og:title"]', "content")
    portal_ids = unique_attribute_values(page, "#jobPortalUrl", "value")
    languages = unique_attribute_values(page, "#lang", "value")
    boxes = page.css(".JobInfoBox")
    if (
        titles != {EXPECTED_PORTAL_TITLE}
        or portal_ids != {PORTAL_ID}
        or languages != {"DE"}
        or len(boxes) != 1
    ):
        raise IntersimParseError("Intersim Dualoo portal has an invalid identity")

    cards = boxes[0].css(":scope > a.jobElement")
    if len(cards) > max_jobs:
        raise IntersimParseError(
            f"Intersim exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        detail_url = urljoin(page_url, optional_text(card.attrib.get("href")) or "")
        job_id = extract_detail_id(detail_url)
        portal_title = selector_text(card, ".jobName")
        title = strip_workload(portal_title)
        listing_location = selector_text(card, ".cityName")
        categories = unique_selector_texts(card, ".jobCategory")
        start = selector_text(card, ".jobDate")
        employment_type = normalize_workload(portal_title)
        public_url = canonical_public_job_url(
            urljoin(careers_url, job_id or ""),
        )
        if (
            not job_id
            or not portal_title
            or not title
            or listing_location != EXPECTED_LISTING_LOCATION
            or categories != {EXPECTED_CATEGORY}
            or not start
            or not employment_type
            or not public_url
        ):
            raise IntersimParseError("Intersim catalog contains an invalid vacancy")
        if job_id in seen_ids:
            raise IntersimParseError("Intersim catalog contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "portal_title": portal_title,
                "company": EXPECTED_COMPANY,
                "location": EXPECTED_LOCATION,
                "employment_type": employment_type,
                "start": start,
                "url": public_url,
                "portal_detail_url": detail_url,
                "listing_page_url": page_url,
                "listing_location": listing_location,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_portal_title: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_detail_id(page_url) != expected_job_id:
        raise IntersimParseError("Intersim detail page returned a different vacancy")

    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    schemas = list(extract_job_posting_schemas(page))
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or len(schemas) != 1
    ):
        raise IntersimParseError("Intersim detail page has an invalid identity")

    schema = schemas[0]
    portal_title = optional_text(schema.get("title"))
    title = strip_workload(portal_title)
    company = extract_company(schema)
    locations = extract_swiss_locations(schema.get("jobLocation"))
    description = combine_description(schema)
    apply_paths = {
        value
        for raw in page.css("a.btn-apply::attr(href)").getall()
        if (value := optional_text(raw))
    }
    apply_urls = {urljoin(page_url, value) for value in apply_paths}
    if (
        portal_title != expected_portal_title
        or not title
        or company != EXPECTED_COMPANY
        or locations != [EXPECTED_LOCATION]
        or not description
        or schema.get("directApply") is not True
        or len(apply_urls) != 1
        or not is_matching_apply_url(next(iter(apply_urls)), expected_job_id=expected_job_id)
    ):
        raise IntersimParseError("Intersim detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "portal_title": portal_title,
        "company": company,
        "location": locations[0],
        "apply_url": apply_urls.pop(),
        "posted_at": optional_text(schema.get("datePosted")),
        "employment_type": normalize_workload(portal_title)
        or normalize_employment_type(schema.get("employmentType")),
        "description": description,
        "schema": schema,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    title = optional_text(detail.get("title")) or optional_text(record.get("title"))
    return ParsedJob(
        source="intersim",
        title=title,
        company=optional_text(detail.get("company")) or EXPECTED_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority="Senior" if comparable_text(title).startswith("senior ") else None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


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


def extract_detail_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.dualoo.com"
        or not match
        or query != {"lang": ["DE"]}
        or parts.fragment
    ):
        return None
    return match.group(1)


def is_matching_apply_url(value: Any, *, expected_job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.dualoo.com"
        and match is not None
        and match.group(1) == expected_job_id
        and query == {"lang": ["DE"]}
        and not parts.fragment
    )


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.intersim.ch"
        or parts.path.rstrip("/") != "/jobs"
        or parts.query
        or parts.fragment
    ):
        return None
    return INTERSIM_CAREERS_URL


def canonical_public_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = PUBLIC_JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.intersim.ch"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.intersim.ch", f"/jobs/{match.group(1)}", "", ""))


def extract_company(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    return optional_text(organization.get("name")) if isinstance(organization, dict) else None


def extract_swiss_locations(value: Any) -> list[str]:
    locations = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for location in locations:
        address = location.get("address") if isinstance(location, dict) else None
        if not isinstance(address, dict):
            continue
        country = optional_text(address.get("addressCountry"))
        locality = optional_text(address.get("addressLocality"))
        if (
            not country
            or country.casefold() not in {"ch", "che", "switzerland", "schweiz"}
            or not locality
        ):
            continue
        label = f"{locality}, Switzerland"
        if label not in normalized:
            normalized.append(label)
    return normalized


def combine_description(schema: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("description", "responsibilities", "skills", "qualifications", "jobBenefits"):
        text = html_to_text(optional_text(schema.get(key)) or "")
        if text and text not in parts:
            parts.append(text)
    return "\n\n".join(parts) or None


def strip_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = WORKLOAD_RANGE_PATTERN.sub("", text)
    text = WORKLOAD_PATTERN.sub("", text)
    return optional_text(text)


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if match := WORKLOAD_RANGE_PATTERN.search(text):
        lower, upper = (int(item) for item in match.groups())
        return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None
    if match := WORKLOAD_PATTERN.search(text):
        workload = int(match.group(1))
        return f"{workload}%" if 1 <= workload <= 100 else None
    return None


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = {"FULL_TIME": "Full-time", "PART_TIME": "Part-time", "INTERN": "Internship"}
    normalized: list[str] = []
    for item in values:
        text = optional_text(item)
        if text:
            label = labels.get(text.upper(), text.replace("_", " ").title())
            if label not in normalized:
                normalized.append(label)
    return ", ".join(normalized) or None


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == "https"
        and actual.scheme == target.scheme
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and parse_qs(actual.query, keep_blank_values=True)
        == parse_qs(target.query, keep_blank_values=True)
        and not actual.fragment
    )


def deduplicate_intersim_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {
        value
        for node in selector.css(css)
        if (value := optional_text(" ".join(node.css("::text").getall())))
    }


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f'{css}::attr("{attribute}")').getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = html.unescape(text).replace("\xa0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip() or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None
