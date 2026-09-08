from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

NEXPLORE_JOBS_URL = "https://www.nexplore.ch/jobs"
NEXPLORE_JOBS_API_URL = "https://cms.nexplore.ch/api/jobs"
NEXPLORE_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$")
WORKLOAD_PATTERN = re.compile(r"^(\d{1,3})\s*-\s*(\d{1,3})\s*%")
NON_VACANCY_SLUGS = {"wer-sind-wir", "spontanbewerbungen"}
SWISS_LOCATIONS = {"Basel", "Bern", "Homeoffice", "Thun"}
PHYSICAL_LOCATIONS = SWISS_LOCATIONS - {"Homeoffice"}
EXPECTED_COMPANY = "Nexplore AG"
EXPECTED_COUNTRY = "Switzerland"


class NexploreParseError(DirectCompanyRequestError):
    pass


class NexploreJobsParser:
    """Collect open roles from Nexplore's official full-catalog CMS API."""

    parser_id = "nexplore"

    def __init__(
        self,
        *,
        base_url: str = NEXPLORE_JOBS_URL,
        api_url: str = NEXPLORE_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**NEXPLORE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records, catalog_total = parse_catalog_payload(
                    response.json(),
                    api_url=self.api_url,
                )
        except NexploreParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Nexplore vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Nexplore vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_nexplore_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Nexplore Switzerland vacancies from "
                f"{catalog_total} official catalog records"
            ),
        )


def parse_catalog_payload(
    payload: Any,
    *,
    api_url: str,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise NexploreParseError("Nexplore catalog response must be an object")
    raw_records = payload.get("data")
    meta = payload.get("meta")
    links = payload.get("links")
    if (
        not isinstance(raw_records, list)
        or not isinstance(meta, dict)
        or not isinstance(links, dict)
    ):
        raise NexploreParseError("Nexplore catalog response has an invalid contract")

    total = positive_int(meta.get("total"))
    if (
        total is None
        or total != len(raw_records)
        or positive_int(meta.get("current_page")) != 1
        or positive_int(meta.get("last_page")) != 1
        or positive_int(meta.get("per_page"), allow_zero=False) is None
        or positive_int(meta.get("to"), allow_zero=True) != total
        or links.get("next") is not None
        or not same_api_url(meta.get("path"), api_url)
    ):
        raise NexploreParseError("Nexplore catalog response is incomplete")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for item in raw_records:
        if not isinstance(item, dict):
            raise NexploreParseError("Nexplore catalog contains an invalid record")
        job_id = optional_text(item.get("id"))
        slug = optional_text(item.get("slug"))
        title = optional_text(item.get("title"))
        if (
            not job_id
            or not UUID_PATTERN.fullmatch(job_id)
            or not slug
            or not SLUG_PATTERN.fullmatch(slug)
            or not title
            or item.get("collection") != "jobs"
            or item.get("blueprint") != "job"
            or item.get("status") != "published"
            or item.get("published") is not True
            or item.get("private") is not False
            or item.get("parent_url") != "/jobs"
            or item.get("url") != f"/jobs/{slug}"
            or not is_public_job_url(item.get("permalink"), expected_slug=slug)
            or not is_api_entry_url(item.get("api_url"), expected_job_id=job_id)
        ):
            raise NexploreParseError("Nexplore catalog contains an incomplete record")
        if job_id in seen_ids or slug in seen_slugs:
            raise NexploreParseError("Nexplore catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_slugs.add(slug)

        if slug in NON_VACANCY_SLUGS:
            continue
        records.append(normalize_record(item))
    return records, total


def normalize_record(item: dict[str, Any]) -> dict[str, Any]:
    summary = html_to_text(optional_text(item.get("description")))
    workload, locations = parse_summary(summary)
    content_items = item.get("content_items")
    categories = item.get("job_categories")
    if not isinstance(content_items, list) or not isinstance(categories, list):
        raise NexploreParseError("Nexplore vacancy is missing its content or categories")
    if not has_application_form(content_items):
        raise NexploreParseError("Nexplore vacancy is missing its application form")

    category_names: list[str] = []
    for category in categories:
        if not isinstance(category, dict):
            raise NexploreParseError("Nexplore vacancy has an invalid category")
        name = optional_text(category.get("title"))
        slug = optional_text(category.get("slug"))
        if not name or not slug or not SLUG_PATTERN.fullmatch(slug):
            raise NexploreParseError("Nexplore vacancy has an invalid category")
        category_names.append(name)

    description = extract_description(content_items, summary=summary)
    posted_at = normalize_date(item.get("date"))
    if not description or not posted_at:
        raise NexploreParseError("Nexplore vacancy is missing its description or date")
    return {
        "id": optional_text(item.get("id")),
        "title": optional_text(item.get("title")),
        "slug": optional_text(item.get("slug")),
        "url": optional_text(item.get("permalink")),
        "posted_at": posted_at,
        "workload": workload,
        "location": f"{' / '.join(locations)}, {EXPECTED_COUNTRY}",
        "categories": category_names,
        "description": description,
        "catalog_record": dict(item),
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="nexplore",
        title=optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=optional_text(record.get("location")),
        url=public_url,
        apply_url=public_url,
        posted_at=optional_text(record.get("posted_at")),
        employment_type=optional_text(record.get("workload")),
        seniority=None,
        description=optional_multiline_text(record.get("description")),
        raw=dict(record),
    )


def parse_summary(value: str | None) -> tuple[str, list[str]]:
    if not value:
        raise NexploreParseError("Nexplore vacancy is missing its location summary")
    parts = [optional_text(part) for part in value.split("|")]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        raise NexploreParseError("Nexplore vacancy has an invalid location summary")
    workload_match = WORKLOAD_PATTERN.match(parts[0])
    if not workload_match:
        raise NexploreParseError("Nexplore vacancy has an invalid workload")
    workload = f"{workload_match.group(1)}–{workload_match.group(2)}%"

    locations: list[str] = []
    for raw_location in parts[1:]:
        location = optional_text(re.sub(r"\s*\([^)]*\)\s*$", "", raw_location))
        if location not in SWISS_LOCATIONS:
            raise NexploreParseError("Nexplore vacancy has an unknown location")
        if location not in locations:
            locations.append(location)
    if not PHYSICAL_LOCATIONS.intersection(locations):
        raise NexploreParseError("Nexplore vacancy has no Swiss office location")
    return workload, locations


def has_application_form(content_items: list[Any]) -> bool:
    for item in content_items:
        if not isinstance(item, dict):
            raise NexploreParseError("Nexplore vacancy contains invalid content")
        form = item.get("form")
        if isinstance(form, dict) and form.get("handle") == "application_form":
            return True
    return False


def extract_description(content_items: list[Any], *, summary: str | None) -> str | None:
    parts: list[str] = []
    if summary:
        parts.append(summary)
    for item in content_items:
        if not isinstance(item, dict):
            raise NexploreParseError("Nexplore vacancy contains invalid content")
        item_type = optional_text(item.get("type"))
        candidates: list[Any] = []
        if item_type in {"text", "text_2_3"}:
            candidates.append(item.get("text"))
        elif item_type == "call_to_action":
            candidates.append(item.get("description"))
        for candidate in candidates:
            text = html_to_text(optional_text(candidate))
            if text and text not in parts:
                parts.append(text)
    return "\n\n".join(parts) if len(parts) > 1 else None


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.date().isoformat() if parsed.tzinfo is not None else None


def is_public_job_url(value: Any, *, expected_slug: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "www.nexplore.ch"
        and parts.path == f"/jobs/{expected_slug}"
        and not parts.query
        and not parts.fragment
    )


def is_api_entry_url(value: Any, *, expected_job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "cms.nexplore.ch"
        and parts.path == f"/api/collections/jobs/entries/{expected_job_id}"
        and not parts.query
        and not parts.fragment
    )


def same_api_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and not actual.query
        and not actual.fragment
        and not target.query
        and not target.fragment
    )


def positive_int(value: Any, *, allow_zero: bool = False) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    minimum = 0 if allow_zero else 1
    return value if value >= minimum else None


def deduplicate_nexplore_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        record_id = optional_text(job.raw.get("id"))
        key = record_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
