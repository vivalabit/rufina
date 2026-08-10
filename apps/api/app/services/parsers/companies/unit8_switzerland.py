from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

UNIT8_SWITZERLAND_JOBS_BASE_URL = "https://unit8.com/career/"
UNIT8_SWITZERLAND_JOBS_API_URL = "https://apply.workable.com/api/v1/widget/accounts/unit8"
UNIT8_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
SHORTCODE_PATTERN = re.compile(r"^[A-F0-9]{10}$")
POSTED_PATTERN = re.compile(r"^Posted\s+(\d{4}-\d{2}-\d{2})$")


class Unit8SwitzerlandParseError(DirectCompanyRequestError):
    pass


class Unit8SwitzerlandJobsParser:
    """Collect only Swiss Unit8 vacancies from its public Workable catalog."""

    parser_id = "unit8_switzerland"

    def __init__(
        self,
        *,
        base_url: str = UNIT8_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = UNIT8_SWITZERLAND_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**UNIT8_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records, global_total = parse_catalog_payload(
                    response.json(),
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except Unit8SwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Unit8 Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Unit8 Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_unit8_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Unit8 Switzerland vacancies from "
                f"{global_total} global Workable postings"
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
                    detail_markdown_url(record["id"]),
                    headers={"Accept": "text/markdown", "Referer": self.base_url},
                )
                response.raise_for_status()
                return record, parse_detail_markdown(
                    response.text,
                    expected_shortcode=record["id"],
                    expected_title=optional_text(record.get("title")),
                )
            except (
                httpx.HTTPError,
                Unit8SwitzerlandParseError,
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
        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=optional_text(detail.get("company")) or "Unit8 SA",
            location=extract_swiss_location(record.get("locations")),
            url=optional_text(detail.get("public_url")) or optional_text(record.get("url")),
            apply_url=optional_text(record.get("application_url")),
            posted_at=optional_text(detail.get("posted_at"))
            or optional_text(record.get("published_on")),
            employment_type=optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type")),
            seniority=optional_text(record.get("experience")),
            description=optional_multiline_text(detail.get("description")),
            raw=raw,
        )


def parse_catalog_payload(
    payload: Any,
    *,
    max_jobs: int,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise Unit8SwitzerlandParseError("Unit8 Workable response is missing its jobs catalog")

    rows = payload["jobs"]
    validated: list[dict[str, Any]] = []
    unique_shortcodes: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            raise Unit8SwitzerlandParseError("Unit8 Workable response contains an invalid vacancy")
        shortcode = normalize_shortcode(item.get("shortcode"))
        title = optional_text(item.get("title"))
        country = optional_text(item.get("country"))
        url = optional_text(item.get("url"))
        application_url = optional_text(item.get("application_url"))
        locations = item.get("locations")
        if (
            not shortcode
            or not title
            or not country
            or not valid_job_url(url, shortcode=shortcode)
            or not valid_job_url(
                application_url,
                shortcode=shortcode,
                apply=True,
            )
            or not valid_locations(locations)
        ):
            raise Unit8SwitzerlandParseError(
                "Unit8 Workable response contains an incomplete vacancy"
            )
        unique_shortcodes.add(shortcode)
        validated.append(dict(item))

    global_total = len(unique_shortcodes)
    if global_total > max_jobs:
        raise Unit8SwitzerlandParseError(
            f"Unit8 exposes {global_total} vacancies, above the configured limit of {max_jobs}"
        )

    swiss_by_id: dict[str, dict[str, Any]] = {}
    for row in validated:
        if not is_swiss_row(row):
            continue
        shortcode = str(row["shortcode"]).upper()
        existing = swiss_by_id.get(shortcode)
        if existing is None:
            existing = dict(row)
            existing["id"] = shortcode
            existing["locations"] = []
            existing["catalog_records"] = 0
            existing["total_available"] = global_total
            swiss_by_id[shortcode] = existing
        elif optional_text(existing.get("title")) != optional_text(
            row.get("title")
        ) or optional_text(existing.get("url")) != optional_text(row.get("url")):
            raise Unit8SwitzerlandParseError(
                "Unit8 Workable response has conflicting duplicate vacancies"
            )

        existing["catalog_records"] += 1
        merge_locations(existing["locations"], row["locations"])

    records = list(swiss_by_id.values())
    swiss_total = len(records)
    for record in records:
        record["swiss_total_available"] = swiss_total
    return records, global_total


def parse_detail_markdown(
    page_markdown: str,
    *,
    expected_shortcode: str,
    expected_title: str | None,
) -> dict[str, Any]:
    lines = page_markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title_line = next((line.strip() for line in lines if line.strip()), "")
    title = optional_text(title_line.removeprefix("# "))
    metadata_line = next((line.strip() for line in lines if line.startswith("> ")), "")
    metadata = metadata_line.removeprefix("> ").split(" · ")
    if len(metadata) < 4:
        raise Unit8SwitzerlandParseError(
            "Unit8 detail page is missing its markdown vacancy contract"
        )

    company = optional_text(metadata[0])
    location_summary = optional_text(metadata[1])
    employment_type = optional_text(metadata[-2])
    posted_match = POSTED_PATTERN.fullmatch(metadata[-1])
    posted_at = posted_match.group(1) if posted_match else None
    description = extract_markdown_description(lines)
    if (
        not title
        or not company
        or not location_summary
        or "Switzerland" not in location_summary
        or not employment_type
        or not posted_at
        or not description
    ):
        raise Unit8SwitzerlandParseError("Unit8 detail page contains an incomplete vacancy")
    if expected_title and title.casefold() != expected_title.casefold():
        raise Unit8SwitzerlandParseError("Unit8 detail page returned a different vacancy title")

    return {
        "id": expected_shortcode,
        "title": title,
        "company": company,
        "public_url": f"https://apply.workable.com/unit8/j/{expected_shortcode}/",
        "posted_at": posted_at,
        "employment_type": employment_type,
        "description": description,
        "markdown_url": detail_markdown_url(expected_shortcode),
    }


def detail_markdown_url(shortcode: str) -> str:
    return f"https://apply.workable.com/unit8/jobs/view/{shortcode}.md"


def extract_markdown_description(lines: list[str]) -> str | None:
    try:
        start = next(index for index, line in enumerate(lines) if line == "## Description")
        end = next(
            index
            for index, line in enumerate(lines[start + 1 :], start=start + 1)
            if line == "## Apply"
        )
    except StopIteration:
        return None
    return markdown_to_text("\n".join(lines[start:end]))


def markdown_to_text(value: str) -> str | None:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`]+", "", text)
    text = text.replace(r"\*", "*")
    return optional_multiline_text(html.unescape(text))


def normalize_shortcode(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    normalized = text.upper()
    return normalized if SHORTCODE_PATTERN.fullmatch(normalized) else None


def valid_job_url(
    value: str | None,
    *,
    shortcode: str,
    apply: bool = False,
    company_path: bool = False,
) -> bool:
    if not value:
        return False
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.netloc != "apply.workable.com":
        return False
    path = parts.path.rstrip("/")
    expected = (
        f"/unit8/j/{shortcode}" if company_path else f"/j/{shortcode}{'/apply' if apply else ''}"
    )
    return path == expected


def valid_locations(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(
        isinstance(location, dict)
        and optional_text(location.get("countryCode"))
        and optional_text(location.get("country"))
        and optional_text(location.get("city"))
        for location in value
    )


def is_swiss_row(record: dict[str, Any]) -> bool:
    if optional_text(record.get("country")) != "Switzerland":
        return False
    locations = record.get("locations")
    return isinstance(locations, list) and all(
        isinstance(location, dict)
        and optional_text(location.get("country")) == "Switzerland"
        and optional_text(location.get("countryCode")) == "CH"
        for location in locations
    )


def merge_locations(target: list[Any], source: list[Any]) -> None:
    seen = {location_key(item) for item in target if isinstance(item, dict)}
    for item in source:
        if not isinstance(item, dict) or not is_swiss_location(item):
            continue
        key = location_key(item)
        if key in seen:
            continue
        seen.add(key)
        target.append(dict(item))


def location_key(location: dict[str, Any]) -> tuple[str, str, str]:
    return (
        optional_text(location.get("city")) or "",
        optional_text(location.get("region")) or "",
        optional_text(location.get("countryCode")) or "",
    )


def is_swiss_location(location: dict[str, Any]) -> bool:
    country = optional_text(location.get("country"))
    country_code = optional_text(location.get("countryCode"))
    return country in {"Switzerland", "CH"} or country_code == "CH"


def extract_swiss_location(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    labels: list[str] = []
    for location in value:
        if not isinstance(location, dict) or not is_swiss_location(location):
            continue
        parts = [
            optional_text(location.get("city")),
            optional_text(location.get("region")),
            "Switzerland",
        ]
        label = ", ".join(part for part in parts if part)
        if label and label not in labels:
            labels.append(label)
    return "; ".join(labels) or None


def deduplicate_unit8_switzerland_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = normalize_shortcode(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


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
