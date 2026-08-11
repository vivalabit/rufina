from __future__ import annotations

import html
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

NTT_GLOBAL_DATA_CENTERS_SWITZERLAND_JOBS_URL = (
    "https://nttglobaldatacenters.wd501.myworkdayjobs.com/en-US/External/jobs?"
    "locations=0416448655001000c28517e560890000"
)
NTT_TENANT = "nttglobaldatacenters"
NTT_SITE = "External"
ZURICH_LOCATION_FACET = "0416448655001000c28517e560890000"
ZURICH_LOCATION = "Zurich, Switzerland"
WORKDAY_RESULTS_PER_PAGE = 20
NTT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXTERNAL_PATH_PATTERN = re.compile(r"^/job/[^/?#]+/[^/?#]+_(JR\d+)$", re.IGNORECASE)


class NttGlobalDataCentersSwitzerlandParseError(DirectCompanyRequestError):
    pass


class NttGlobalDataCentersSwitzerlandJobsParser:
    """Collect NTT Global Data Centers roles exposed by its Zurich Workday facet."""

    parser_id = "ntt_global_data_centers_switzerland"

    def __init__(
        self,
        *,
        base_url: str = NTT_GLOBAL_DATA_CENTERS_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    @property
    def api_base_url(self) -> str:
        return f"{origin(self.base_url)}/wday/cxs/{NTT_TENANT}/{NTT_SITE}"

    @property
    def site_base_url(self) -> str:
        return f"{origin(self.base_url)}/{NTT_SITE}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.api_base_url}/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        records: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        try:
            with httpx.Client(
                headers={
                    **NTT_HEADERS,
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
        except NttGlobalDataCentersSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "NTT Global Data Centers Switzerland Workday request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "NTT Global Data Centers Switzerland vacancy parsing failed"
            ) from exc

        verified_records = [record for record in records if is_verified_record(record)]
        jobs = [self.normalize_job(record) for record in verified_records]
        if request.deduplicate:
            jobs = deduplicate_ntt_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified NTT Global Data Centers vacancies for "
                f"{ZURICH_LOCATION} from {total} Workday facet records across "
                f"{pages_fetched} page requests"
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
                    "appliedFacets": {"locations": [ZURICH_LOCATION_FACET]},
                    "limit": WORKDAY_RESULTS_PER_PAGE,
                    "offset": offset,
                    "searchText": "",
                },
            )
            pages_fetched += 1
            response.raise_for_status()
            payload = response.json()
            page_total, postings = parse_listing_payload(payload)

            if total is None:
                total = page_total
                validate_zurich_facet(payload, expected_total=total)
                offsets.extend(page_offsets(total)[1:])
                if len(offsets) > self.max_pages:
                    raise NttGlobalDataCentersSwitzerlandParseError(
                        f"NTT Global Data Centers exposes {len(offsets)} pages, "
                        f"above the configured limit of {self.max_pages}"
                    )
            elif page_total not in {0, total}:
                raise NttGlobalDataCentersSwitzerlandParseError(
                    "NTT Global Data Centers changed its vacancy total during pagination"
                )

            if offset < (total or 0) and not postings:
                raise NttGlobalDataCentersSwitzerlandParseError(
                    f"NTT Workday page at offset {offset} was unexpectedly empty"
                )

            for posting in postings:
                external_path = optional_text(posting.get("externalPath"))
                if not is_safe_external_path(external_path):
                    raise NttGlobalDataCentersSwitzerlandParseError(
                        "NTT Workday returned an unsafe vacancy path"
                    )
                requisition_id = extract_requisition_id(external_path)
                bullet_fields = posting.get("bulletFields")
                if not isinstance(bullet_fields, list) or [
                    optional_text(value) for value in bullet_fields
                ] != [requisition_id]:
                    raise NttGlobalDataCentersSwitzerlandParseError(
                        "NTT Workday returned an invalid requisition ID"
                    )
                if external_path in seen_paths:
                    continue
                seen_paths.add(external_path)
                record = dict(posting)
                record["listing_offset"] = offset
                record["total_available"] = total
                record["expected_host"] = urlsplit(self.base_url).netloc.casefold()
                records.append(record)

        if len(records) != (total or 0):
            raise NttGlobalDataCentersSwitzerlandParseError(
                f"NTT Global Data Centers yielded {len(records)} unique vacancies "
                f"of {total or 0} facet records"
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
                    raise NttGlobalDataCentersSwitzerlandParseError(
                        "NTT detail response must be an object"
                    )
                return record, payload
            except (
                httpx.HTTPError,
                ValueError,
                NttGlobalDataCentersSwitzerlandParseError,
            ) as exc:
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
            if public_url_matches(
                candidate_url,
                external_path=external_path,
                expected_host=urlsplit(self.base_url).netloc,
            )
            else constructed_url
        )
        description_html = optional_text(posting_info.get("jobDescription"))
        raw = dict(record)
        raw["detail"] = detail

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(posting_info.get("title")) or optional_text(record.get("title")),
            company=(optional_text(organization.get("name")) or "NTT Global Data Centers"),
            location=ZURICH_LOCATION,
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
        raise NttGlobalDataCentersSwitzerlandParseError("NTT Workday response must be an object")
    total = payload.get("total")
    postings = payload.get("jobPostings")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise NttGlobalDataCentersSwitzerlandParseError("NTT Workday response has an invalid total")
    if not isinstance(postings, list):
        raise NttGlobalDataCentersSwitzerlandParseError(
            "NTT Workday response has invalid jobPostings"
        )
    records: list[dict[str, Any]] = []
    for posting in postings:
        if (
            not isinstance(posting, dict)
            or not optional_text(posting.get("title"))
            or not optional_text(posting.get("externalPath"))
            or not optional_text(posting.get("locationsText"))
            or not optional_text(posting.get("postedOn"))
        ):
            raise NttGlobalDataCentersSwitzerlandParseError(
                "NTT Workday response contains an incomplete vacancy"
            )
        records.append(posting)
    return total, records


def validate_zurich_facet(payload: Any, *, expected_total: int) -> None:
    if not isinstance(payload, dict):
        raise NttGlobalDataCentersSwitzerlandParseError(
            "NTT Workday response is missing its Zurich facet"
        )
    matches: list[dict[str, Any]] = []
    for candidate in walk_json(payload.get("facets")):
        if candidate.get("facetParameter") != "locations":
            continue
        values = candidate.get("values")
        if not isinstance(values, list):
            continue
        matches.extend(
            value
            for value in values
            if isinstance(value, dict) and value.get("id") == ZURICH_LOCATION_FACET
        )
    if (
        len(matches) != 1
        or optional_text(matches[0].get("descriptor")) != ZURICH_LOCATION
        or matches[0].get("count") != expected_total
    ):
        raise NttGlobalDataCentersSwitzerlandParseError(
            "NTT Workday response is missing its verified Zurich facet"
        )


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def page_offsets(total: int) -> list[int]:
    return list(range(0, total, WORKDAY_RESULTS_PER_PAGE)) if total > 0 else []


def is_verified_record(record: dict[str, Any]) -> bool:
    if record.get("detail_error") and "detail" not in record:
        return True
    detail = record.get("detail")
    if not isinstance(detail, dict):
        return False
    posting_info = detail.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        return False
    external_path = optional_text(record.get("externalPath"))
    requisition_id = extract_requisition_id(external_path)
    expected_host = optional_text(record.get("expected_host"))
    return bool(
        requisition_id
        and expected_host
        and optional_text(posting_info.get("jobReqId")) == requisition_id
        and optional_text(posting_info.get("title")) == optional_text(record.get("title"))
        and posting_info.get("canApply") is True
        and posting_info.get("posted") is True
        and has_zurich_location(posting_info)
        and public_url_matches(
            posting_info.get("externalUrl"),
            external_path=external_path,
            expected_host=expected_host,
        )
    )


def has_zurich_location(posting_info: dict[str, Any]) -> bool:
    values = [optional_text(posting_info.get("location"))]
    additional = posting_info.get("additionalLocations")
    if isinstance(additional, Sequence) and not isinstance(additional, (str, bytes)):
        values.extend(optional_text(value) for value in additional)
    return any(value == ZURICH_LOCATION for value in values)


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


def extract_requisition_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = EXTERNAL_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1).upper() if match else None


def is_safe_external_path(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return bool(
        not parts.scheme
        and not parts.netloc
        and EXTERNAL_PATH_PATTERN.fullmatch(parts.path)
        and not parts.query
        and not parts.fragment
    )


def public_url_matches(
    value: Any,
    *,
    external_path: str | None,
    expected_host: str,
) -> bool:
    text = optional_text(value)
    if not text or not is_safe_external_path(external_path):
        return False
    parts = urlsplit(text)
    return bool(
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host.casefold()
        and parts.path == f"/{NTT_SITE}{external_path}"
        and not parts.query
        and not parts.fragment
    )


def deduplicate_ntt_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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


def origin(value: str) -> str:
    parts = urlsplit(value)
    return f"{parts.scheme}://{parts.netloc}"


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


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
