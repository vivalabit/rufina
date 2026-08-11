from __future__ import annotations

import base64
import html
import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

TERADATA_JOBS_URL = "https://careers.teradata.com/jobs"
TERADATA_JOBS_API_URL = "https://careers.teradata.com/graphql"
TERADATA_LOCATION = "Switzerland"
TERADATA_PAGE_SIZE = 25
TERADATA_TRUSTED_DOCUMENT_ID = "search-jobs"
TERADATA_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9",
    "Apollo-Require-Preflight": "true",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
WORKPLACE_TYPES = {
    "HYBRID": "Hybrid",
    "REMOTE": "Remote",
    "ON_SITE": "On-site",
}
JOB_KEY_PATTERN = re.compile(r"^[1-9]\d*$")


class TeradataSwitzerlandParseError(DirectCompanyRequestError):
    pass


class TeradataSwitzerlandJobsParser:
    """Collect Swiss roles from Teradata's public GR8 People GraphQL catalog."""

    parser_id = "teradata_switzerland"

    def __init__(
        self,
        *,
        base_url: str = TERADATA_JOBS_URL,
        api_url: str = TERADATA_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        records: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        try:
            with httpx.Client(
                headers={**TERADATA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                total, pages_fetched = self.collect_records(
                    client,
                    records=records,
                    seen_keys=seen_keys,
                )
        except TeradataSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Teradata vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Teradata vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_teradata_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Teradata Switzerland vacancies from "
                f"{total} GR8 People records across {pages_fetched} page requests"
            ),
        )

    def collect_records(
        self,
        client: httpx.Client,
        *,
        records: list[dict[str, Any]],
        seen_keys: set[str],
    ) -> tuple[int, int]:
        total: int | None = None
        offsets = [0]
        pages_fetched = 0

        for offset in offsets:
            response = client.post(
                self.api_url,
                json=search_payload(offset=offset),
            )
            pages_fetched += 1
            response.raise_for_status()
            page_total, page_records = parse_search_payload(
                response.json(),
                offset=offset,
            )

            if total is None:
                total = page_total
                offsets[:] = page_offsets(total)
                if len(offsets) > self.max_pages:
                    raise TeradataSwitzerlandParseError(
                        f"Teradata exposes {len(offsets)} Swiss pages, above the "
                        f"configured limit of {self.max_pages}"
                    )
            elif page_total != total:
                raise TeradataSwitzerlandParseError(
                    "Teradata changed its Swiss vacancy total during pagination"
                )

            for raw_record in page_records:
                record = normalize_record(raw_record, offset=offset)
                key = record["key"]
                if key in seen_keys:
                    raise TeradataSwitzerlandParseError(
                        "Teradata returned duplicate Swiss vacancy IDs"
                    )
                seen_keys.add(key)
                records.append(record)

        if len(records) != (total or 0):
            raise TeradataSwitzerlandParseError(
                f"Teradata yielded {len(records)} unique Swiss vacancies of "
                f"{total or 0} filtered records"
            )
        return total or 0, pages_fetched

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        public_url = public_job_url(
            self.base_url,
            key=record["key"],
            title=record["title"],
        )
        position_type = optional_text(record.get("position_type"))
        workplace_type = optional_text(record.get("workplace_type"))
        employment_parts = [value for value in (position_type, workplace_type) if value]
        return ParsedJob(
            source=self.parser_id,
            title=record["title"],
            company="Teradata",
            location=record["location"],
            url=public_url,
            apply_url=apply_url(public_url),
            posted_at=record["posted_at"],
            employment_type=", ".join(employment_parts) or None,
            description=record["description"],
            raw=dict(record),
        )


def search_payload(*, offset: int) -> dict[str, Any]:
    return {
        "operationName": "searchJobs",
        "variables": {
            "query": None,
            "first": TERADATA_PAGE_SIZE,
            "start": offset,
            "filters": {"location": [{"address": TERADATA_LOCATION}]},
        },
        "extensions": {
            "trustedDocument": {"id": TERADATA_TRUSTED_DOCUMENT_ID},
        },
    }


def page_offsets(total: int) -> list[int]:
    if total < 0:
        raise ValueError("total must not be negative")
    return list(range(0, total, TERADATA_PAGE_SIZE)) or [0]


def parse_search_payload(
    payload: Any,
    *,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict) or payload.get("errors"):
        raise TeradataSwitzerlandParseError("Teradata GraphQL response contains errors")
    data = payload.get("data")
    search = data.get("searchJobs") if isinstance(data, dict) else None
    results = search.get("results") if isinstance(search, dict) else None
    if (
        not isinstance(search, dict)
        or search.get("__typename") != "JobPostingSearch"
        or not isinstance(results, dict)
        or results.get("__typename") != "JobPostingConnection"
    ):
        raise TeradataSwitzerlandParseError(
            "Teradata GraphQL response has an invalid search contract"
        )

    total = results.get("totalCount")
    nodes = results.get("nodes")
    page_info = results.get("pageInfo")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or not isinstance(nodes, list)
        or not isinstance(page_info, dict)
        or any(not isinstance(node, dict) for node in nodes)
    ):
        raise TeradataSwitzerlandParseError("Teradata GraphQL response has invalid pagination data")

    remaining = max(0, total - offset)
    expected_count = min(TERADATA_PAGE_SIZE, remaining)
    expected_next = offset + len(nodes) < total
    if (
        len(nodes) != expected_count
        or page_info.get("hasNextPage") is not expected_next
        or page_info.get("hasPreviousPage") is not (offset > 0)
    ):
        raise TeradataSwitzerlandParseError(
            f"Teradata returned an incomplete page at offset {offset}"
        )
    return total, nodes


def normalize_record(record: dict[str, Any], *, offset: int) -> dict[str, Any]:
    key = optional_text(record.get("key"))
    number = optional_text(record.get("number"))
    title = optional_text(record.get("title"))
    description_html = optional_text(record.get("descriptionHTML"))
    posted_at = normalize_date(record.get("postedOn"))
    if (
        not key
        or not JOB_KEY_PATTERN.fullmatch(key)
        or number != key
        or not valid_graphql_id(record.get("id"), expected_key=key)
        or record.get("status") != "OPEN"
        or record.get("postType") != "INT_EXT"
        or not title
        or not description_html
        or not posted_at
    ):
        raise TeradataSwitzerlandParseError("Teradata returned an incomplete Swiss vacancy")

    location = swiss_location(record.get("places"))
    if not location:
        raise TeradataSwitzerlandParseError("Teradata location filter returned a non-Swiss vacancy")
    validate_structured_data(
        record.get("structuredDataJSON"),
        expected_key=key,
        expected_title=title,
        expected_posted_at=posted_at,
    )

    workplace_code = optional_text(record.get("workplaceType"))
    if workplace_code and workplace_code not in WORKPLACE_TYPES:
        raise TeradataSwitzerlandParseError("Teradata returned an unknown workplace type")
    position_type = record.get("positionType")
    position_type = position_type if isinstance(position_type, dict) else {}
    position_name = optional_text(position_type.get("name"))

    normalized = dict(record)
    normalized.update(
        {
            "key": key,
            "title": title,
            "location": location,
            "posted_at": posted_at,
            "position_type": position_name,
            "workplace_type": WORKPLACE_TYPES.get(workplace_code or ""),
            "description": html_to_text(description_html),
            "listing_offset": offset,
        }
    )
    return normalized


def swiss_location(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    nodes = value.get("nodes")
    if not isinstance(nodes, list):
        return None
    locations: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            return None
        name = optional_text(node.get("name"))
        if (
            name
            and (
                name.casefold() == TERADATA_LOCATION.casefold()
                or name.casefold().endswith(f", {TERADATA_LOCATION}".casefold())
            )
            and name not in locations
        ):
            locations.append(name)
    return " / ".join(locations) or None


def validate_structured_data(
    value: Any,
    *,
    expected_key: str,
    expected_title: str,
    expected_posted_at: str,
) -> None:
    text = optional_text(value)
    if not text:
        raise TeradataSwitzerlandParseError("Teradata vacancy is missing structured data")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TeradataSwitzerlandParseError("Teradata vacancy has invalid structured data") from exc
    organization = data.get("hiringOrganization") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("@type") != "JobPosting"
        or optional_text(data.get("identifier")) != expected_key
        or optional_text(data.get("title")) != expected_title
        or normalize_date(data.get("datePosted")) != expected_posted_at
        or not isinstance(organization, dict)
        or optional_text(organization.get("name")) != "Teradata"
    ):
        raise TeradataSwitzerlandParseError(
            "Teradata vacancy structured data does not match the listing"
        )


def valid_graphql_id(value: Any, *, expected_key: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    return decoded == f"JobPosting/{expected_key}"


def public_job_url(base_url: str, *, key: str, title: str) -> str:
    parts = urlsplit(base_url)
    slug = slugify(title)
    return f"{parts.scheme}://{parts.netloc}/jobs/{key}/{slug}"


def apply_url(public_url: str) -> str:
    parts = urlsplit(public_url)
    destination = f"{parts.path}/apply"
    return f"{parts.scheme}://{parts.netloc}/login?dest={quote(destination, safe='')}"


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug or "job"


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.date().isoformat() if parsed.tzinfo is not None else None


def deduplicate_teradata_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_key(job.url)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def extract_job_key(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path_parts = parts.path.strip("/").split("/")
    if (
        parts.scheme != "https"
        or len(path_parts) != 3
        or path_parts[0] != "jobs"
        or not JOB_KEY_PATTERN.fullmatch(path_parts[1])
        or not path_parts[2]
    ):
        return None
    return path_parts[1]


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
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None
