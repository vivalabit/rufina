from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SIEGFRIED_JOBS_BASE_URL = "https://siegfried.wd103.myworkdayjobs.com/external"
SIEGFRIED_TENANT = "siegfried"
SIEGFRIED_SITE = "external"
WORKDAY_RESULTS_PER_PAGE = 20
SIEGFRIED_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class SiegfriedParseError(DirectCompanyRequestError):
    pass


class SiegfriedJobsParser:
    """Collect every vacancy from Siegfried's public Workday site."""

    parser_id = "siegfried"

    def __init__(
        self,
        *,
        base_url: str = SIEGFRIED_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def api_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return (
            f"{parts.scheme}://{parts.netloc}/wday/cxs/"
            f"{SIEGFRIED_TENANT}/{SIEGFRIED_SITE}"
        )

    @property
    def site_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/{SIEGFRIED_SITE}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.api_base_url}/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        records: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        try:
            with httpx.Client(
                headers={
                    **SIEGFRIED_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                total, pages_fetched = self.collect_listing_records(
                    client,
                    records=records,
                    seen_paths=seen_paths,
                )
                self.enrich_records(client, records)
        except SiegfriedParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Siegfried Workday request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Siegfried vacancy request failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_siegfried_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Siegfried vacancies from {total} catalog "
                f"records across {pages_fetched} Workday page requests"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
        *,
        records: list[dict[str, Any]],
        seen_paths: set[str],
    ) -> tuple[int, int]:
        pages_fetched = 0
        last_error: SiegfriedParseError | None = None

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            pass_records: list[dict[str, Any]] = []
            pass_seen_paths: set[str] = set()
            total: int | None = None
            offsets = [0]
            catalog_changed = False

            for offset in offsets:
                response = client.post(
                    self.listing_api_url,
                    json={
                        "appliedFacets": {},
                        "limit": WORKDAY_RESULTS_PER_PAGE,
                        "offset": offset,
                        "searchText": "",
                    },
                )
                pages_fetched += 1
                response.raise_for_status()
                page_total, postings = parse_listing_payload(response.json())

                if total is None:
                    total = page_total
                    offsets.extend(page_offsets(total)[1:])
                    if len(offsets) > self.max_pages:
                        raise SiegfriedParseError(
                            f"Siegfried exposes {len(offsets)} pages, above the "
                            f"configured limit of {self.max_pages}"
                        )
                if offset < (total or 0) and not postings:
                    last_error = SiegfriedParseError(
                        f"Siegfried Workday page at offset {offset} was "
                        "unexpectedly empty"
                    )
                    catalog_changed = True
                    break

                for posting in postings:
                    external_path = optional_text(posting.get("externalPath"))
                    if not external_path or external_path in pass_seen_paths:
                        continue
                    pass_seen_paths.add(external_path)
                    record = dict(posting)
                    record["catalog_pass"] = catalog_pass
                    record["listing_offset"] = offset
                    record["total_available"] = total
                    pass_records.append(record)

            if catalog_changed:
                continue

            if len(pass_records) != (total or 0):
                last_error = SiegfriedParseError(
                    f"Siegfried yielded {len(pass_records)} unique vacancies of "
                    f"{total or 0} catalog records"
                )
                continue

            records.extend(pass_records)
            seen_paths.update(pass_seen_paths)
            return total or 0, pages_fetched

        if last_error is not None:
            raise last_error
        raise SiegfriedParseError(
            f"Siegfried catalog did not stabilize after {self.max_catalog_passes} passes"
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(record: dict[str, Any]) -> tuple[dict[str, Any], Any]:
            external_path = optional_text(record.get("externalPath"))
            if not external_path:
                return record, None
            try:
                response = client.get(f"{self.api_base_url}{external_path}")
                response.raise_for_status()
                return record, response.json()
            except (httpx.HTTPError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(
            max_workers=min(self.detail_workers, len(records))
        ) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, payload = future.result()
                if isinstance(payload, dict):
                    record["detail"] = payload

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        posting_info = detail.get("jobPostingInfo")
        posting_info = posting_info if isinstance(posting_info, dict) else {}
        organization = detail.get("hiringOrganization")
        organization = organization if isinstance(organization, dict) else {}
        external_path = optional_text(record.get("externalPath"))
        public_url = optional_text(posting_info.get("externalUrl")) or (
            f"{self.site_base_url}{external_path}" if external_path else self.base_url
        )
        description_html = optional_text(posting_info.get("jobDescription"))

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=(
                optional_text(posting_info.get("title"))
                or optional_text(record.get("title"))
            ),
            company=optional_text(organization.get("name")) or "Siegfried",
            location=extract_location(posting_info, record),
            url=public_url,
            apply_url=public_url,
            posted_at=(
                optional_text(posting_info.get("startDate"))
                or optional_text(posting_info.get("postedOn"))
                or optional_text(record.get("postedOn"))
            ),
            employment_type=extract_employment_type(posting_info, record),
            description=html_to_text(description_html) if description_html else None,
            raw=raw,
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise SiegfriedParseError("Siegfried Workday response must be an object")
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise SiegfriedParseError("Siegfried Workday response has an invalid total")
    postings = payload.get("jobPostings")
    if not isinstance(postings, list):
        raise SiegfriedParseError(
            "Siegfried Workday response has invalid jobPostings"
        )

    records: list[dict[str, Any]] = []
    for posting in postings:
        if (
            not isinstance(posting, dict)
            or not optional_text(posting.get("title"))
            or not optional_text(posting.get("externalPath"))
        ):
            raise SiegfriedParseError(
                "Siegfried Workday response contains an incomplete vacancy"
            )
        records.append(posting)
    return total, records


def page_offsets(total: int) -> list[int]:
    if total <= 0:
        return []
    return list(range(0, total, WORKDAY_RESULTS_PER_PAGE))


def extract_location(
    posting_info: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    values: list[str] = []
    primary = optional_text(posting_info.get("location"))
    if primary:
        values.append(primary)
    additional = posting_info.get("additionalLocations")
    if isinstance(additional, Sequence) and not isinstance(additional, (str, bytes)):
        values.extend(text for item in additional if (text := optional_text(item)))
    if not values:
        listing_location = optional_text(listing.get("locationsText"))
        if listing_location and not re.fullmatch(
            r"\d+\s+Locations?",
            listing_location,
            re.IGNORECASE,
        ):
            values.append(listing_location)
    if not values:
        external_path = optional_text(listing.get("externalPath"))
        path_parts = external_path.strip("/").split("/") if external_path else []
        if len(path_parts) >= 2 and path_parts[0] == "job":
            values.append(unquote(path_parts[1]).replace("-", " "))
    unique = list(dict.fromkeys(values))
    return ", ".join(unique) if unique else None


def extract_employment_type(
    posting_info: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    values = [
        optional_text(posting_info.get("timeType")),
        optional_text(posting_info.get("remoteType"))
        or optional_text(listing.get("remoteType")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def deduplicate_siegfried_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        external_path = optional_text(job.raw.get("externalPath"))
        key = external_path or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
