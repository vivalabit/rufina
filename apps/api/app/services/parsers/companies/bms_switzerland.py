from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BMS_SWITZERLAND_JOBS_BASE_URL = (
    "https://jobs.bms.com/careers?domain=bms.com&start=0&location=Switzerland&"
    "pid=137482241804&sort_by=distance&filter_include_remote=1&"
    "filter_include_relocation=0"
)
BMS_SWITZERLAND_JOBS_API_URL = "https://jobs.bms.com/api/pcsx/search"
BMS_SWITZERLAND_DETAILS_API_URL = "https://jobs.bms.com/api/pcsx/position_details"
BMS_DOMAIN = "bms.com"
BMS_LOCATION = "Switzerland"
BMS_PAGE_SIZE = 10
BMS_APPLY_HOST = "bristolmyerssquibb.wd5.myworkdayjobs.com"
BMS_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
POSITION_PATH_PATTERN = re.compile(r"^/careers/job/(?P<id>\d+)$")


class BmsSwitzerlandParseError(DirectCompanyRequestError):
    pass


class BmsSwitzerlandJobsParser:
    """Collect BMS vacancies with at least one verified Swiss location."""

    parser_id = "bms_switzerland"

    def __init__(
        self,
        *,
        base_url: str = BMS_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = BMS_SWITZERLAND_JOBS_API_URL,
        detail_api_url: str = BMS_SWITZERLAND_DETAILS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.detail_api_url = detail_api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def careers_origin(self) -> str:
        parts = urlsplit(self.base_url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**BMS_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except BmsSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("BMS Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("BMS Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bms_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified BMS Switzerland vacancies from "
                f"{total} Eightfold records across {pages_fetched} page requests"
            ),
        )

    def listing_params(self, *, offset: int) -> dict[str, str | int]:
        return {
            "domain": BMS_DOMAIN,
            "start": offset,
            "query": "",
            "location": BMS_LOCATION,
            "sort_by": "distance",
            "filter_include_remote": 1,
            "filter_include_relocation": 0,
        }

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.get(self.api_url, params=self.listing_params(offset=offset))
        response.raise_for_status()
        total, records = parse_listing_payload(response.json(), base_url=self.base_url)
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        requests_made = 0
        last_total = 0
        last_unique = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_page = self.fetch_listing_page(client, offset=0)
            requests_made += 1
            expected_total = first_page[1]
            last_total = expected_total
            required_pages = max(1, ceil(expected_total / BMS_PAGE_SIZE))
            if required_pages > self.max_pages:
                raise BmsSwitzerlandParseError(
                    f"BMS Switzerland exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            pages = [first_page]
            for offset in range(BMS_PAGE_SIZE, expected_total, BMS_PAGE_SIZE):
                pages.append(self.fetch_listing_page(client, offset=offset))
                requests_made += 1

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            record_count = 0
            for offset, page_total, records in pages:
                expected_size = min(BMS_PAGE_SIZE, max(0, expected_total - offset))
                if page_total != expected_total or len(records) != expected_size:
                    catalog_changed = True
                    break
                record_count += len(records)
                for record in records:
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(extract_job_id(record), normalized)

            last_unique = len(records_by_id)
            if not catalog_changed and record_count == expected_total == last_unique:
                return list(records_by_id.values()), requests_made, expected_total

        raise BmsSwitzerlandParseError(
            f"BMS Switzerland yielded only {last_unique} unique vacancies of "
            f"{last_total} after {self.max_catalog_passes} catalog passes"
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
            job_id = extract_job_id(record)
            try:
                response = client.get(
                    self.detail_api_url,
                    params={
                        "position_id": job_id,
                        "domain": BMS_DOMAIN,
                        "hl": "en",
                        "queried_location": BMS_LOCATION,
                    },
                )
                response.raise_for_status()
                return record, parse_detail_payload(
                    response.json(),
                    expected_record=record,
                    base_url=self.base_url,
                )
            except (httpx.HTTPError, BmsSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def build_job_url(self, record: dict[str, Any]) -> str:
        url = normalize_public_url(record.get("positionUrl"), base_url=self.base_url)
        return url or f"{self.careers_origin}/careers/job/{extract_job_id(record)}"

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        public_url = normalize_public_url(
            detail.get("publicUrl"), base_url=self.base_url
        ) or self.build_job_url(record)
        apply_url = normalize_apply_url(
            detail.get("apply_url"),
            expected_req_id=extract_requisition_id(record),
        )
        raw = dict(record)
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("name")) or optional_text(record.get("name")),
            company="Bristol Myers Squibb",
            location=extract_swiss_location(detail) or extract_swiss_location(record),
            url=public_url,
            apply_url=apply_url or public_url,
            posted_at=epoch_to_iso(detail.get("postedTs") or record.get("postedTs")),
            description=html_to_text(detail.get("jobDescription")),
            raw=raw,
        )


def parse_listing_payload(
    payload: Any,
    *,
    base_url: str,
) -> tuple[int, list[dict[str, Any]]]:
    data = parse_api_data(payload, context="jobs")
    total = data.get("count")
    positions = data.get("positions")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise BmsSwitzerlandParseError("BMS Switzerland jobs response has an invalid total")
    if not isinstance(positions, list):
        raise BmsSwitzerlandParseError("BMS Switzerland jobs response has invalid positions")
    if data.get("sortBy") != "distance":
        raise BmsSwitzerlandParseError("BMS Switzerland jobs response has invalid sorting")
    applied_filters = data.get("appliedFilters")
    if applied_filters != {"includeRemote": ["1"], "includeRelocation": ["0"]}:
        raise BmsSwitzerlandParseError("BMS Switzerland jobs response has invalid filters")

    records: list[dict[str, Any]] = []
    for item in positions:
        if not isinstance(item, dict) or not valid_listing_record(item, base_url=base_url):
            raise BmsSwitzerlandParseError(
                "BMS Switzerland jobs response contains an invalid vacancy"
            )
        records.append(item)
    return total, records


def valid_listing_record(record: dict[str, Any], *, base_url: str) -> bool:
    job_id = extract_job_id(record)
    req_id = extract_requisition_id(record)
    public_url = normalize_public_url(record.get("positionUrl"), base_url=base_url)
    locations = sequence_text(record.get("locations"))
    standardized = sequence_text(record.get("standardizedLocations"))
    return bool(
        job_id
        and req_id
        and optional_text(record.get("name"))
        and optional_text(record.get("displayJobId")) == req_id
        and optional_text(record.get("atsJobId")) == req_id
        and public_url
        and extract_url_job_id(public_url) == job_id
        and locations
        and len(locations) == len(standardized)
        and any(is_swiss_standardized_location(value) for value in standardized)
        and optional_text(record.get("department"))
        and epoch_to_iso(record.get("postedTs"))
        and epoch_to_iso(record.get("creationTs"))
    )


def parse_detail_payload(
    payload: Any,
    *,
    expected_record: dict[str, Any],
    base_url: str,
) -> dict[str, Any]:
    data = parse_api_data(payload, context="detail")
    expected_job_id = extract_job_id(expected_record)
    expected_req_id = extract_requisition_id(expected_record)
    public_url = normalize_public_url(data.get("publicUrl"), base_url=base_url)
    position_url = normalize_public_url(data.get("positionUrl"), base_url=base_url)
    actions = data.get("positionUserActions")
    apply_action = actions.get("applyAction") if isinstance(actions, dict) else None
    apply_url = (
        normalize_apply_url(apply_action.get("applyUrl"), expected_req_id=expected_req_id)
        if isinstance(apply_action, dict) and apply_action.get("status") == "link_off"
        else None
    )
    if (
        extract_job_id(data) != expected_job_id
        or optional_text(data.get("displayJobId")) != expected_req_id
        or optional_text(data.get("atsJobId")) != expected_req_id
        or comparable_text(data.get("name")) != comparable_text(expected_record.get("name"))
        or not public_url
        or public_url != position_url
        or extract_url_job_id(public_url) != expected_job_id
        or sequence_text(data.get("locations")) != sequence_text(expected_record.get("locations"))
        or sequence_text(data.get("standardizedLocations"))
        != sequence_text(expected_record.get("standardizedLocations"))
        or not extract_swiss_location(data)
        or not optional_text(data.get("jobDescription"))
        or not epoch_to_iso(data.get("postedTs"))
        or not apply_url
    ):
        raise BmsSwitzerlandParseError(
            "BMS Switzerland detail response contains an incomplete or mismatched vacancy"
        )
    sanitized = dict(data)
    removed: list[str] = []
    for key in ("positionExtraDetails", "jdHighlight"):
        if key in sanitized:
            sanitized.pop(key)
            removed.append(key)
    sanitized["apply_url"] = apply_url
    if removed:
        sanitized["raw_fields_removed"] = removed
    return sanitized


def parse_api_data(payload: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("status") != 200:
        raise BmsSwitzerlandParseError(f"BMS Switzerland {context} response has an invalid status")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BmsSwitzerlandParseError(f"BMS Switzerland {context} response has invalid data")
    return data


def normalize_public_url(value: Any, *, base_url: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    expected = urlsplit(base_url)
    parts = urlsplit(text)
    if not parts.scheme and not parts.netloc:
        parts = urlsplit(f"{expected.scheme}://{expected.netloc}{parts.path}")
    if (
        parts.scheme != "https"
        or parts.hostname != expected.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port != expected.port
        or parts.query
        or parts.fragment
        or not POSITION_PATH_PATTERN.fullmatch(parts.path)
    ):
        return None
    return urlunsplit(("https", expected.netloc.casefold(), parts.path, "", ""))


def normalize_apply_url(value: Any, *, expected_req_id: str) -> str | None:
    text = optional_text(value)
    if not text or not expected_req_id:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.hostname != BMS_APPLY_HOST
        or parts.username is not None
        or parts.password is not None
        or parts.port is not None
        or parts.fragment
        or not parts.path.startswith("/BMS/job/")
        or not parts.path.endswith("/apply")
        or f"_{expected_req_id}/apply" not in parts.path
        or set(query) - {"source", "utm_campaign"}
        or query.get("source") != ["Eightfold"]
    ):
        return None
    return urlunsplit(("https", BMS_APPLY_HOST, parts.path, parts.query, ""))


def extract_swiss_location(record: dict[str, Any]) -> str | None:
    standardized = sequence_text(record.get("standardizedLocations"))
    swiss = [
        format_swiss_location(value)
        for value in standardized
        if is_swiss_standardized_location(value)
    ]
    return "; ".join(dict.fromkeys(swiss)) or None


def is_swiss_standardized_location(value: str) -> bool:
    return bool(re.search(r",\s*CH$", value, re.IGNORECASE))


def format_swiss_location(value: str) -> str:
    return re.sub(r",\s*CH$", ", Switzerland", value, flags=re.IGNORECASE)


def extract_job_id(record: dict[str, Any]) -> str:
    value = record.get("id")
    if value is None or isinstance(value, bool):
        return ""
    text = str(value).strip()
    return text if text.isdigit() else ""


def extract_url_job_id(value: str) -> str:
    match = POSITION_PATH_PATTERN.fullmatch(urlsplit(value).path)
    return match.group("id") if match else ""


def extract_requisition_id(record: dict[str, Any]) -> str:
    value = optional_text(record.get("atsJobId")) or optional_text(record.get("displayJobId"))
    return value if value and re.fullmatch(r"R\d+", value) else ""


def epoch_to_iso(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def deduplicate_bms_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or job.url or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def html_to_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(html.unescape(text)))


def sequence_text(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [text for item in value if (text := optional_text(item))]


def comparable_text(value: Any) -> str:
    return " ".join((optional_text(value) or "").casefold().split())


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
