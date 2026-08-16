from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

JULIUS_BAER_SWITZERLAND_JOBS_BASE_URL = (
    "https://juliusbaer.wd3.myworkdayjobs.com/en-US/External?"
    "Location_Country=187134fccb084a0ea9b4b95f23890dbe"
)
JULIUS_BAER_TENANT = "juliusbaer"
JULIUS_BAER_SITE = "External"
SWITZERLAND_COUNTRY_FACET = "187134fccb084a0ea9b4b95f23890dbe"
WORKDAY_RESULTS_PER_PAGE = 20
JULIUS_BAER_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXTERNAL_PATH_PATTERN = re.compile(r"^/job/[^/]+/[^/]+$")


class JuliusBaerSwitzerlandParseError(DirectCompanyRequestError):
    pass


class JuliusBaerSwitzerlandJobsParser:
    """Collect every vacancy in Julius Baer's official Swiss Workday facet."""

    parser_id = "julius_baer_switzerland"

    def __init__(
        self,
        *,
        base_url: str = JULIUS_BAER_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def api_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return (
            f"{parts.scheme}://{parts.netloc}/wday/cxs/"
            f"{JULIUS_BAER_TENANT}/{JULIUS_BAER_SITE}"
        )

    @property
    def site_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/{JULIUS_BAER_SITE}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.api_base_url}/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        records: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        try:
            with httpx.Client(
                headers={
                    **JULIUS_BAER_HEADERS,
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
        except JuliusBaerSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Julius Baer Switzerland Workday request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Julius Baer Switzerland vacancy parsing failed"
            ) from exc

        swiss_records = [record for record in records if is_swiss_record(record)]
        jobs = [self.normalize_job(record) for record in swiss_records]
        if request.deduplicate:
            jobs = deduplicate_julius_baer_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Julius Baer Switzerland vacancies "
                f"from {total} Workday facet records across {pages_fetched} page "
                "requests"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
        *,
        records: list[dict[str, Any]],
        seen_paths: set[str],
    ) -> tuple[int, int]:
        total: int | None = None
        offsets = [0]
        pages_fetched = 0

        for offset in offsets:
            response = client.post(
                self.listing_api_url,
                json={
                    "appliedFacets": {
                        "Location_Country": [SWITZERLAND_COUNTRY_FACET],
                    },
                    "limit": WORKDAY_RESULTS_PER_PAGE,
                    "offset": offset,
                    "searchText": "",
                },
            )
            response.raise_for_status()
            pages_fetched += 1
            page_total, postings = parse_listing_payload(response.json())

            if total is None:
                total = page_total
                offsets.extend(page_offsets(total)[1:])
                if len(offsets) > self.max_pages:
                    raise JuliusBaerSwitzerlandParseError(
                        f"Julius Baer Switzerland exposes {len(offsets)} pages, "
                        f"above the configured limit of {self.max_pages}"
                    )
            elif page_total not in {0, total}:
                raise JuliusBaerSwitzerlandParseError(
                    "Julius Baer Switzerland changed its vacancy total during "
                    "pagination"
                )

            if offset < (total or 0) and not postings:
                raise JuliusBaerSwitzerlandParseError(
                    f"Julius Baer Switzerland Workday page at offset {offset} was "
                    "unexpectedly empty"
                )
            for posting in postings:
                external_path = optional_text(posting.get("externalPath"))
                if external_path in seen_paths:
                    raise JuliusBaerSwitzerlandParseError(
                        "Julius Baer Switzerland Workday catalog contains duplicate "
                        "vacancy paths"
                    )
                seen_paths.add(external_path or "")
                record = dict(posting)
                record["listing_offset"] = offset
                record["total_available"] = total
                records.append(record)

        if len(records) != (total or 0):
            raise JuliusBaerSwitzerlandParseError(
                f"Julius Baer Switzerland yielded {len(records)} unique vacancies "
                f"of {total or 0} catalog records"
            )
        return total or 0, pages_fetched

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
        external_path = optional_text(record.get("externalPath"))
        public_url = canonical_public_url(posting_info.get("externalUrl")) or (
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
            company="Julius Baer",
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
        raise JuliusBaerSwitzerlandParseError(
            "Julius Baer Switzerland Workday response must be an object"
        )
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise JuliusBaerSwitzerlandParseError(
            "Julius Baer Switzerland Workday response has an invalid total"
        )
    postings = payload.get("jobPostings")
    if not isinstance(postings, list):
        raise JuliusBaerSwitzerlandParseError(
            "Julius Baer Switzerland Workday response has invalid jobPostings"
        )

    records: list[dict[str, Any]] = []
    for posting in postings:
        if not valid_listing_record(posting):
            raise JuliusBaerSwitzerlandParseError(
                "Julius Baer Switzerland Workday response contains an incomplete "
                "vacancy"
            )
        records.append(posting)
    return total, records


def valid_listing_record(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    title = optional_text(value.get("title"))
    external_path = optional_text(value.get("externalPath"))
    bullet_fields = value.get("bulletFields")
    return bool(
        title
        and external_path
        and EXTERNAL_PATH_PATTERN.fullmatch(external_path)
        and isinstance(bullet_fields, Sequence)
        and not isinstance(bullet_fields, (str, bytes))
        and len(bullet_fields) == 1
        and optional_text(bullet_fields[0])
    )


def page_offsets(total: int) -> list[int]:
    if total <= 0:
        return []
    return list(range(0, total, WORKDAY_RESULTS_PER_PAGE))


def is_swiss_record(record: dict[str, Any]) -> bool:
    detail = record.get("detail")
    if not isinstance(detail, dict) or not detail:
        return True
    posting_info = detail.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        return True
    country = posting_info.get("country")
    if isinstance(country, dict):
        if (
            optional_text(country.get("id")) == SWITZERLAND_COUNTRY_FACET
            and comparable_text(country.get("descriptor")) == "switzerland"
        ):
            return valid_detail_identity(posting_info, record)
        return False
    requisition_location = posting_info.get("jobRequisitionLocation")
    requisition_country = (
        requisition_location.get("country")
        if isinstance(requisition_location, dict)
        else None
    )
    return bool(
        isinstance(requisition_country, dict)
        and optional_text(requisition_country.get("id"))
        == SWITZERLAND_COUNTRY_FACET
        and comparable_text(requisition_country.get("alpha2Code")) == "ch"
        and valid_detail_identity(posting_info, record)
    )


def valid_detail_identity(
    posting_info: dict[str, Any],
    listing: dict[str, Any],
) -> bool:
    listing_path = optional_text(listing.get("externalPath"))
    public_url = canonical_public_url(posting_info.get("externalUrl"))
    bullet_fields = listing.get("bulletFields")
    listing_req_id = (
        optional_text(bullet_fields[0])
        if isinstance(bullet_fields, Sequence)
        and not isinstance(bullet_fields, (str, bytes))
        and bullet_fields
        else None
    )
    return bool(
        listing_path
        and public_url
        and urlsplit(public_url).path.endswith(listing_path)
        and comparable_text(posting_info.get("title"))
        == comparable_text(listing.get("title"))
        and optional_text(posting_info.get("jobReqId")) == listing_req_id
    )


def canonical_public_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "juliusbaer.wd3.myworkdayjobs.com"
        or parts.query
        or parts.fragment
        or not parts.path.startswith(f"/{JULIUS_BAER_SITE}/job/")
    ):
        return None
    return urlunsplit(("https", parts.hostname, parts.path, "", ""))


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
            r"\d+\s+Locations?", listing_location, re.IGNORECASE
        ):
            values.append(listing_location)
    if not values:
        external_path = optional_text(listing.get("externalPath"))
        path_parts = external_path.strip("/").split("/") if external_path else []
        if len(path_parts) >= 2 and path_parts[0] == "job":
            values.append(unquote(path_parts[1]).replace("-", " "))
    return ", ".join(dict.fromkeys(values)) or None


def extract_employment_type(
    posting_info: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    values = [
        optional_text(posting_info.get("timeType")),
        optional_text(posting_info.get("remoteType"))
        or optional_text(listing.get("remoteType")),
    ]
    return ", ".join(dict.fromkeys(value for value in values if value)) or None


def deduplicate_julius_baer_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(html.unescape(text))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip() or None
