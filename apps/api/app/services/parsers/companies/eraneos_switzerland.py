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

ERANEOS_SWITZERLAND_JOBS_BASE_URL = (
    "https://eraneos.wd3.myworkdayjobs.com/Eraneos_External_Career_Site"
)
ERANEOS_TENANT = "eraneos"
ERANEOS_SITE = "Eraneos_External_Career_Site"
SWITZERLAND_COUNTRY_ID = "187134fccb084a0ea9b4b95f23890dbe"
WORKDAY_RESULTS_PER_PAGE = 20
ERANEOS_SWITZERLAND_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class EraneosSwitzerlandParseError(DirectCompanyRequestError):
    pass


class EraneosSwitzerlandJobsParser:
    """Collect every vacancy from Eraneos' Switzerland-only Workday site."""

    parser_id = "eraneos_switzerland"

    def __init__(
        self,
        *,
        base_url: str = ERANEOS_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    @property
    def api_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/wday/cxs/{ERANEOS_TENANT}/{ERANEOS_SITE}"

    @property
    def site_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/{ERANEOS_SITE}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.api_base_url}/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        records: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        try:
            with httpx.Client(
                headers={
                    **ERANEOS_SWITZERLAND_HEADERS,
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
        except EraneosSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Eraneos Switzerland Workday request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Eraneos Switzerland vacancy parsing failed") from exc

        verified_records = [record for record in records if is_swiss_record(record)]
        jobs = [self.normalize_job(record) for record in verified_records]
        if request.deduplicate:
            jobs = deduplicate_eraneos_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Eraneos Switzerland vacancies "
                f"from {total} Workday site records across {pages_fetched} page requests"
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
                    raise EraneosSwitzerlandParseError(
                        f"Eraneos Switzerland exposes {len(offsets)} pages, "
                        f"above the configured limit of {self.max_pages}"
                    )
            elif page_total not in {0, total}:
                raise EraneosSwitzerlandParseError(
                    "Eraneos Switzerland changed its vacancy total during pagination"
                )

            if offset < (total or 0) and not postings:
                raise EraneosSwitzerlandParseError(
                    f"Eraneos Switzerland Workday page at offset {offset} was unexpectedly empty"
                )

            for posting in postings:
                external_path = optional_text(posting.get("externalPath"))
                if not is_safe_external_path(external_path):
                    raise EraneosSwitzerlandParseError(
                        "Eraneos Switzerland returned an unsafe vacancy path"
                    )
                if external_path in seen_paths:
                    continue
                seen_paths.add(external_path)
                record = dict(posting)
                record["listing_offset"] = offset
                record["total_available"] = total
                records.append(record)

        if len(records) != (total or 0):
            raise EraneosSwitzerlandParseError(
                f"Eraneos Switzerland yielded {len(records)} unique vacancies "
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
            if not is_safe_external_path(external_path):
                return record, None
            try:
                response = client.get(f"{self.api_base_url}{external_path}")
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise EraneosSwitzerlandParseError("Eraneos detail response must be an object")
                return record, payload
            except (httpx.HTTPError, ValueError, EraneosSwitzerlandParseError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
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
        constructed_url = (
            f"{self.site_base_url}{external_path}"
            if is_safe_external_path(external_path)
            else self.base_url
        )
        candidate_url = optional_text(posting_info.get("externalUrl"))
        public_url = (
            candidate_url
            if is_public_job_url(candidate_url, expected_host=urlsplit(self.base_url).netloc)
            else constructed_url
        )
        description_html = optional_text(posting_info.get("jobDescription"))

        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(posting_info.get("title")) or optional_text(record.get("title")),
            company=optional_text(organization.get("name")) or "Eraneos Switzerland AG",
            location=extract_location(posting_info, record),
            url=public_url,
            apply_url=public_url,
            posted_at=optional_text(posting_info.get("startDate"))
            or optional_text(posting_info.get("postedOn"))
            or optional_text(record.get("postedOn")),
            employment_type=extract_employment_type(posting_info, record),
            description=html_to_text(description_html) if description_html else None,
            raw=raw,
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise EraneosSwitzerlandParseError("Eraneos Switzerland Workday response must be an object")
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise EraneosSwitzerlandParseError(
            "Eraneos Switzerland Workday response has an invalid total"
        )
    postings = payload.get("jobPostings")
    if not isinstance(postings, list):
        raise EraneosSwitzerlandParseError(
            "Eraneos Switzerland Workday response has invalid jobPostings"
        )

    records: list[dict[str, Any]] = []
    for posting in postings:
        if (
            not isinstance(posting, dict)
            or not optional_text(posting.get("title"))
            or not optional_text(posting.get("externalPath"))
        ):
            raise EraneosSwitzerlandParseError(
                "Eraneos Switzerland Workday response contains an incomplete vacancy"
            )
        records.append(posting)
    return total, records


def page_offsets(total: int) -> list[int]:
    if total <= 0:
        return []
    return list(range(0, total, WORKDAY_RESULTS_PER_PAGE))


def is_swiss_record(record: dict[str, Any]) -> bool:
    if record.get("detail_error") and "detail" not in record:
        return True
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    posting_info = detail.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        return False

    country = posting_info.get("country")
    if is_swiss_country(country):
        return True
    requisition_location = posting_info.get("jobRequisitionLocation")
    if isinstance(requisition_location, dict):
        return is_swiss_country(requisition_location.get("country"))
    return False


def is_swiss_country(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    country_id = optional_text(value.get("id"))
    alpha2 = optional_text(value.get("alpha2Code"))
    descriptor = optional_text(value.get("descriptor"))
    return bool(
        country_id == SWITZERLAND_COUNTRY_ID
        or (alpha2 and alpha2.casefold() == "ch")
        or (
            descriptor and descriptor.casefold() in {"switzerland", "schweiz", "suisse", "svizzera"}
        )
    )


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
    unique = list(dict.fromkeys(values))
    return ", ".join(unique) if unique else None


def extract_employment_type(
    posting_info: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    values = [
        optional_text(posting_info.get("timeType")),
        optional_text(posting_info.get("remoteType")) or optional_text(listing.get("remoteType")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def is_safe_external_path(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return bool(
        not parts.scheme
        and not parts.netloc
        and parts.path.startswith("/job/")
        and len(parts.path.strip("/").split("/")) >= 3
        and not parts.query
        and not parts.fragment
    )


def is_public_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return bool(
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host.casefold()
        and parts.path.startswith(f"/{ERANEOS_SITE}/job/")
        and not parts.fragment
    )


def deduplicate_eraneos_switzerland_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
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
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(html.unescape(text)).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
