from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SWISS_LIFE_JOBS_URL = "https://www.swisslife.ch/de/ueber-uns/karriere/jobs.html#"
SWISS_LIFE_CATALOG_URL = "https://ohws.prospective.ch/public/v1/careercenter/1005584/"
SWISS_LIFE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
SWISS_LIFE_PAGE_SIZE = 200
VACANCY_COUNT_PATTERN = re.compile(r"(\d+)\s+Stellen?", re.IGNORECASE)
VACANCY_PATH_PATTERN = re.compile(
    r"^/(?:offene-stellen|postes-vacantes|posti-vacanti)/"
    r"[a-z0-9]+(?:-[a-z0-9]+)*/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    r"^/public/v1/redirect/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/ats/?$",
    re.IGNORECASE,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
SWISS_COUNTRIES = {"ch", "schweiz", "switzerland", "suisse", "svizzera"}
SWISS_COUNTRY_NAMES = SWISS_COUNTRIES - {"ch"}
EMPLOYMENT_TYPES = {
    "FULL_TIME": "Full-time",
    "PART_TIME": "Part-time",
    "CONTRACTOR": "Contract",
    "INTERN": "Internship",
}


class SwissLifeSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SwissLifeSwitzerlandJobsParser:
    """Collect the complete Swiss Life Switzerland Prospective catalog."""

    parser_id = "swiss_life_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SWISS_LIFE_JOBS_URL,
        catalog_url: str = SWISS_LIFE_CATALOG_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        detail_workers: int = 8,
        page_size: int = SWISS_LIFE_PAGE_SIZE,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = min(12, max(1, detail_workers))
        self.page_size = max(1, page_size)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**SWISS_LIFE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, total, pages_fetched = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SwissLifeSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Swiss Life vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Swiss Life vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_swiss_life_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Swiss Life Switzerland vacancies from "
                f"{total} Prospective records across {pages_fetched} page requests"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        total: int | None = None
        offsets = [0]

        for offset in offsets:
            response = client.post(
                self.catalog_url,
                data={
                    "offset": str(offset),
                    "limit": str(self.page_size),
                    "lang": "de",
                },
            )
            response.raise_for_status()
            page_records, page_total, total_pages = parse_listing_html(
                response.text,
                page_url=str(response.url),
                expected_offset=offset,
                page_size=self.page_size,
            )
            if total is None:
                total = page_total
                if total_pages > self.max_pages:
                    raise SwissLifeSwitzerlandParseError(
                        f"Swiss Life catalog exceeds the configured limit of {self.max_pages} pages"
                    )
                offsets[:] = [page_offset * self.page_size for page_offset in range(total_pages)]
            elif page_total != total:
                raise SwissLifeSwitzerlandParseError(
                    "Swiss Life changed its vacancy total during pagination"
                )

            for record in page_records:
                job_id = str(record["id"])
                if job_id in seen_ids:
                    raise SwissLifeSwitzerlandParseError(
                        "Swiss Life catalog contains duplicate vacancy IDs"
                    )
                seen_ids.add(job_id)
                records.append(record)

        if len(records) != (total or 0):
            raise SwissLifeSwitzerlandParseError(
                f"Swiss Life yielded {len(records)} unique vacancies of "
                f"{total or 0} catalog records"
            )
        return records, total or 0, len(offsets)

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
                    str(record["url"]),
                    headers={"Referer": self.catalog_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=str(record["id"]),
                    expected_title=str(record["title"]),
                )
            except (httpx.HTTPError, SwissLifeSwitzerlandParseError, ValueError) as exc:
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
        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(record.get("company")) or "Swiss Life AG",
            location=swiss_location(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=normalize_employment_type(detail.get("employment_type")),
            description=optional_multiline_text(detail.get("description")),
            raw=raw,
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_offset: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int, int]:
    page = Selector(page_html)
    if (
        not page.css("form#careercenter-form")
        or hidden_value(page, "offset") != str(expected_offset)
        or hidden_value(page, "limit") != str(page_size)
        or hidden_value(page, "lang") != "de"
    ):
        raise SwissLifeSwitzerlandParseError(
            "Swiss Life listing did not retain its pagination contract"
        )

    count_text = selector_text(page, "section#jobs .anzStellen")
    count_match = VACANCY_COUNT_PATTERN.search(count_text or "")
    if not count_match:
        raise SwissLifeSwitzerlandParseError("Swiss Life listing is missing its vacancy count")
    total = int(count_match.group(1))
    total_pages = max(1, math.ceil(total / page_size))
    expected_page = (expected_offset // page_size) + 1
    active_page = selector_text(page, "#pagination a.page.active")
    if active_page != str(expected_page):
        raise SwissLifeSwitzerlandParseError(
            "Swiss Life listing returned an inconsistent active page"
        )

    cards = page.css("section#jobs a.job")
    expected_count = min(page_size, max(0, total - expected_offset))
    if len(cards) != expected_count:
        raise SwissLifeSwitzerlandParseError(
            "Swiss Life listing returned an incomplete vacancy page"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        detail_url = optional_text(card.attrib.get("href"))
        job_id = extract_job_id(detail_url)
        title = selector_text(card, ".jobTitle h2")
        company = selector_text(card, ".jobTitle span")
        location = selector_text(card, ".jobArbeitsOrt")
        if job_id and job_id in seen_ids:
            raise SwissLifeSwitzerlandParseError(
                "Swiss Life catalog contains duplicate vacancy IDs"
            )
        if (
            not detail_url
            or not job_id
            or not title
            or not company
            or not company.casefold().startswith("swiss life")
            or not location
            or not is_public_job_url(detail_url)
        ):
            raise SwissLifeSwitzerlandParseError(
                "Swiss Life listing contains an incomplete vacancy"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "url": detail_url,
                "listing_page_url": page_url,
                "listing_offset": expected_offset,
            }
        )
    return records, total, total_pages


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str,
    expected_title: str,
) -> dict[str, Any]:
    if extract_job_id(page_url) != expected_job_id or not is_public_job_url(page_url):
        raise SwissLifeSwitzerlandParseError("Swiss Life detail page returned a different vacancy")

    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    if not schema:
        schema = next(extract_job_posting_schemas_from_html(page_html), {})
    title = optional_text(html.unescape(optional_text(schema.get("title")) or ""))
    description_html = optional_text(schema.get("description"))
    posted_at = normalize_date(schema.get("datePosted"))
    organization = schema.get("hiringOrganization")
    organization = organization if isinstance(organization, dict) else {}
    apply_href = optional_text(page.css("a#applyButton::attr(href)").get())
    apply_url = urljoin(page_url, apply_href) if apply_href else None
    if (
        schema.get("@type") != "JobPosting"
        or title != optional_text(expected_title)
        or not description_html
        or not posted_at
        or not optional_text(organization.get("name"))
        or not optional_text(organization.get("name")).casefold().startswith("swiss life")
        or not is_swiss_schema_location(schema.get("jobLocation"))
        or not is_apply_url(apply_url, expected_job_id=expected_job_id)
    ):
        raise SwissLifeSwitzerlandParseError(
            "Swiss Life detail page contains incomplete or non-Swiss vacancy data"
        )

    return {
        "title": title,
        "apply_url": apply_url,
        "posted_at": posted_at,
        "employment_type": optional_text(schema.get("employmentType")),
        "description": html_to_text(description_html),
        "schema": schema,
    }


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        yield from parse_job_posting_json(raw_script)


def extract_job_posting_schemas_from_html(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        yield from parse_job_posting_json(match.group(1))


def parse_job_posting_json(value: Any) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return
    for candidate in walk_json(payload):
        job_type = candidate.get("@type")
        if job_type == "JobPosting" or (isinstance(job_type, list) and "JobPosting" in job_type):
            yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def hidden_value(page: Selector, name: str) -> str | None:
    return optional_text(page.css(f'input[name="{name}"]::attr(value)').get())


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = VACANCY_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1).lower() if match else None


def is_public_job_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.swisslife.ch"
        and VACANCY_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.query
        and not parts.fragment
    )


def is_apply_url(value: Any, *, expected_job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "ohws.prospective.ch"
        and match is not None
        and match.group(1).casefold() == expected_job_id.casefold()
        and not parts.query
        and not parts.fragment
    )


def is_swiss_schema_location(value: Any) -> bool:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if not isinstance(address, dict):
            continue
        country = optional_text(address.get("addressCountry"))
        if country and country.casefold() in SWISS_COUNTRIES:
            return True
    return False


def swiss_location(value: Any) -> str:
    location = optional_text(value) or "Switzerland"
    normalized = location.casefold()
    if normalized in SWISS_COUNTRIES or any(
        normalized.endswith(f", {country}") for country in SWISS_COUNTRY_NAMES
    ):
        return location
    return f"{location}, Switzerland"


def normalize_employment_type(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [normalize_employment_type(item) for item in value]
        return ", ".join(dict.fromkeys(item for item in values if item)) or None
    text = optional_text(value)
    return EMPLOYMENT_TYPES.get(text or "", text)


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def deduplicate_swiss_life_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " ")) or ""


def selector_text(node: Any, selector: str) -> str | None:
    selected_html = node.css(selector).get()
    return optional_multiline_text(html_to_text(str(selected_html))) if selected_html else None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None
