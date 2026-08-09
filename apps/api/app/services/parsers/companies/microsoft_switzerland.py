from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import urljoin

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

MICROSOFT_SWITZERLAND_JOBS_BASE_URL = (
    "https://apply.careers.microsoft.com/careers?start=0&"
    "location=Switzerland%2C+Z%C3%BCrich%2C+Z%C3%BCrich&"
    "pid=1970393556942270&sort_by=distance&filter_distance=160&"
    "filter_include_remote=1&filter_include_relocation=0"
)
MICROSOFT_SWITZERLAND_JOBS_API_URL = "https://apply.careers.microsoft.com/api/pcsx/search"
MICROSOFT_SWITZERLAND_JOB_DETAILS_API_URL = (
    "https://apply.careers.microsoft.com/api/pcsx/position_details"
)
MICROSOFT_SWITZERLAND_LOCATION = "Switzerland, Zürich, Zürich"
MICROSOFT_DOMAIN = "microsoft.com"
MICROSOFT_PAGE_SIZE = 10
MICROSOFT_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class MicrosoftSwitzerlandParseError(DirectCompanyRequestError):
    pass


class MicrosoftSwitzerlandJobsParser:
    """Collect Microsoft's complete careers catalog around Zürich, Switzerland."""

    parser_id = "microsoft_switzerland"

    def __init__(
        self,
        *,
        base_url: str = MICROSOFT_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = MICROSOFT_SWITZERLAND_JOBS_API_URL,
        detail_api_url: str = MICROSOFT_SWITZERLAND_JOB_DETAILS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.detail_api_url = detail_api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**MICROSOFT_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except MicrosoftSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Microsoft Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Microsoft Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_microsoft_switzerland_jobs(jobs)
        page_label = "page" if pages_fetched == 1 else "pages"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Microsoft Switzerland vacancies across "
                f"{pages_fetched} API {page_label} ({total} listed)"
            ),
        )

    def listing_params(self, *, offset: int) -> dict[str, str | int]:
        return {
            "domain": MICROSOFT_DOMAIN,
            "query": "",
            "location": MICROSOFT_SWITZERLAND_LOCATION,
            "start": offset,
            "sort_by": "distance",
            "filter_distance": 160,
            "filter_include_remote": 1,
            "filter_include_relocation": 0,
        }

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records: list[dict[str, Any]] = []
        expected_total: int | None = None
        required_pages = 1

        for page_number in range(1, self.max_pages + 1):
            offset = (page_number - 1) * MICROSOFT_PAGE_SIZE
            response = client.get(self.api_url, params=self.listing_params(offset=offset))
            response.raise_for_status()
            page_total, page_records = parse_listing_payload(response.json())

            if expected_total is None:
                expected_total = page_total
                required_pages = max(1, ceil(expected_total / MICROSOFT_PAGE_SIZE))
                if required_pages > self.max_pages:
                    raise MicrosoftSwitzerlandParseError(
                        f"Microsoft Switzerland exposes {required_pages} pages, above "
                        f"the configured limit of {self.max_pages}"
                    )
            elif page_total != expected_total:
                raise MicrosoftSwitzerlandParseError(
                    "Microsoft Switzerland changed its vacancy total during pagination"
                )

            expected_page_size = min(
                MICROSOFT_PAGE_SIZE,
                max(0, expected_total - offset),
            )
            if len(page_records) != expected_page_size:
                raise MicrosoftSwitzerlandParseError(
                    f"Microsoft Switzerland page {page_number} returned "
                    f"{len(page_records)} vacancies, expected {expected_page_size}"
                )

            for record in page_records:
                normalized = dict(record)
                normalized["listing_page"] = page_number
                normalized["total_available"] = expected_total
                records.append(normalized)

            if page_number >= required_pages:
                break

        if expected_total is None:
            raise MicrosoftSwitzerlandParseError(
                "Microsoft Switzerland jobs response was not collected"
            )
        if len(records) != expected_total:
            raise MicrosoftSwitzerlandParseError(
                f"Microsoft Switzerland returned {len(records)} vacancies of {expected_total}"
            )
        return records, required_pages, expected_total

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
            job_id = extract_job_id(record)
            try:
                response = client.get(
                    self.detail_api_url,
                    params={
                        "position_id": job_id,
                        "domain": MICROSOFT_DOMAIN,
                        "hl": "en",
                        "queried_location": MICROSOFT_SWITZERLAND_LOCATION,
                    },
                )
                response.raise_for_status()
                return record, parse_detail_payload(response.json(), expected_job_id=job_id)
            except (httpx.HTTPError, MicrosoftSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def build_job_url(self, record: dict[str, Any]) -> str:
        position_url = optional_text(record.get("positionUrl"))
        if position_url:
            return urljoin("https://apply.careers.microsoft.com", position_url)
        return f"https://apply.careers.microsoft.com/careers/job/{extract_job_id(record)}"

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        public_url = optional_text(detail.get("publicUrl")) or self.build_job_url(record)
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("name")) or optional_text(record.get("name")),
            company="Microsoft",
            location=extract_location(detail) or extract_location(record) or "Switzerland",
            url=public_url,
            apply_url=public_url,
            posted_at=epoch_to_iso(detail.get("postedTs") or record.get("postedTs")),
            employment_type=first_list_text(detail.get("efcustomTextEmploymentType")),
            seniority=first_list_text(detail.get("efcustomTextRoletype")),
            description=html_to_text(detail.get("jobDescription")),
            raw=dict(record),
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    data = parse_api_data(payload, context="jobs")
    total = data.get("count")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise MicrosoftSwitzerlandParseError(
            "Microsoft Switzerland jobs response has an invalid total"
        )
    positions = data.get("positions")
    if not isinstance(positions, list):
        raise MicrosoftSwitzerlandParseError(
            "Microsoft Switzerland jobs response has invalid positions"
        )

    records: list[dict[str, Any]] = []
    for item in positions:
        if (
            not isinstance(item, dict)
            or not extract_job_id(item)
            or not optional_text(item.get("name"))
            or not optional_text(item.get("positionUrl"))
        ):
            raise MicrosoftSwitzerlandParseError(
                "Microsoft Switzerland jobs response contains an incomplete vacancy"
            )
        records.append(item)
    return total, records


def parse_detail_payload(payload: Any, *, expected_job_id: str) -> dict[str, Any]:
    data = parse_api_data(payload, context="detail")
    if extract_job_id(data) != expected_job_id:
        raise MicrosoftSwitzerlandParseError(
            "Microsoft Switzerland detail response has an unexpected vacancy id"
        )
    sanitized = dict(data)
    if "positionExtraDetails" in sanitized:
        sanitized.pop("positionExtraDetails")
        sanitized["raw_fields_removed"] = ["positionExtraDetails"]
    return sanitized


def parse_api_data(payload: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("status") != 200:
        raise MicrosoftSwitzerlandParseError(
            f"Microsoft Switzerland {context} response has an invalid status"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise MicrosoftSwitzerlandParseError(
            f"Microsoft Switzerland {context} response has invalid data"
        )
    return data


def extract_job_id(record: dict[str, Any]) -> str:
    value = record.get("id")
    if value is None or isinstance(value, bool):
        return ""
    return optional_text(value) or ""


def extract_location(record: dict[str, Any]) -> str | None:
    locations = record.get("locations")
    if not isinstance(locations, Sequence) or isinstance(locations, (str, bytes)):
        return optional_text(record.get("location"))
    unique = [location for item in locations if (location := optional_text(item))]
    return "; ".join(dict.fromkeys(unique)) or optional_text(record.get("location"))


def first_list_text(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if text := optional_text(item):
                return text
    return optional_text(value) if isinstance(value, str) else None


def epoch_to_iso(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def deduplicate_microsoft_switzerland_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or job.url or ""
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
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


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
