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

BIOGEN_SWITZERLAND_JOBS_BASE_URL = (
    "https://biibhr.wd3.myworkdayjobs.com/external?locationCountry=187134fccb084a0ea9b4b95f23890dbe"
)
BIOGEN_TENANT = "biibhr"
BIOGEN_SITE = "external"
SWITZERLAND_COUNTRY_FACET = "187134fccb084a0ea9b4b95f23890dbe"
WORKDAY_RESULTS_PER_PAGE = 20
BIOGEN_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
EXTERNAL_PATH_PATTERN = re.compile(r"^/job/[^/?#]+/[^/?#]+$")
REQUISITION_PATTERN = re.compile(r"(?:^|_)REQ\d+(?:-\d+)?$")


class BiogenSwitzerlandParseError(DirectCompanyRequestError):
    pass


class BiogenSwitzerlandJobsParser:
    """Collect Biogen's complete country-filtered Swiss Workday catalog."""

    parser_id = "biogen_switzerland"

    def __init__(
        self,
        *,
        base_url: str = BIOGEN_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    @property
    def api_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/wday/cxs/{BIOGEN_TENANT}/{BIOGEN_SITE}"

    @property
    def site_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/{BIOGEN_SITE}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.api_base_url}/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **BIOGEN_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except BiogenSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Biogen Switzerland Workday request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Biogen Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_biogen_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Biogen Switzerland vacancies from "
                f"{total} Workday facet records across {pages_fetched} page requests"
            ),
        )

    def listing_payload(self, *, offset: int) -> dict[str, Any]:
        return {
            "appliedFacets": {
                "locationCountry": [SWITZERLAND_COUNTRY_FACET],
            },
            "limit": WORKDAY_RESULTS_PER_PAGE,
            "offset": offset,
            "searchText": "",
        }

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.post(
            self.listing_api_url,
            json=self.listing_payload(offset=offset),
        )
        response.raise_for_status()
        total, records = parse_listing_payload(response.json())
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
            offsets = page_offsets(expected_total)
            required_pages = max(1, len(offsets))
            if required_pages > self.max_pages:
                raise BiogenSwitzerlandParseError(
                    f"Biogen Switzerland exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            pages = [first_page]
            for offset in offsets[1:]:
                pages.append(self.fetch_listing_page(client, offset=offset))
                requests_made += 1

            records_by_path: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            record_count = 0
            for offset, page_total, records in pages:
                expected_size = min(
                    WORKDAY_RESULTS_PER_PAGE,
                    max(0, expected_total - offset),
                )
                if page_total not in {0, expected_total} or len(records) != expected_size:
                    catalog_changed = True
                    break
                record_count += len(records)
                for record in records:
                    external_path = extract_external_path(record)
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_path.setdefault(external_path, normalized)

            last_unique = len(records_by_path)
            if not catalog_changed and record_count == expected_total == last_unique:
                return list(records_by_path.values()), requests_made, expected_total

        raise BiogenSwitzerlandParseError(
            f"Biogen Switzerland yielded only {last_unique} unique vacancies of "
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
            external_path = extract_external_path(record)
            try:
                response = client.get(f"{self.api_base_url}{external_path}")
                response.raise_for_status()
                return record, parse_detail_payload(
                    response.json(),
                    expected_record=record,
                    base_url=self.base_url,
                )
            except (httpx.HTTPError, BiogenSwitzerlandParseError, ValueError) as exc:
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
        posting_info = detail.get("jobPostingInfo")
        posting_info = posting_info if isinstance(posting_info, dict) else {}
        external_path = extract_external_path(record)
        public_url = (
            canonical_public_url(
                posting_info.get("externalUrl"),
                base_url=self.base_url,
            )
            or f"{self.site_base_url}{external_path}"
        )
        description_html = optional_text(posting_info.get("jobDescription"))
        raw = dict(record)
        return ParsedJob(
            source=self.parser_id,
            title=(optional_text(posting_info.get("title")) or optional_text(record.get("title"))),
            company="Biogen",
            location=extract_swiss_locations(posting_info, record) or "Switzerland",
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
        raise BiogenSwitzerlandParseError("Biogen Switzerland Workday response must be an object")
    total = payload.get("total")
    postings = payload.get("jobPostings")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise BiogenSwitzerlandParseError(
            "Biogen Switzerland Workday response has an invalid total"
        )
    if not isinstance(postings, list):
        raise BiogenSwitzerlandParseError(
            "Biogen Switzerland Workday response has invalid jobPostings"
        )
    records: list[dict[str, Any]] = []
    for posting in postings:
        if not valid_listing_record(posting):
            raise BiogenSwitzerlandParseError(
                "Biogen Switzerland Workday response contains an incomplete vacancy"
            )
        records.append(posting)
    return total, records


def valid_listing_record(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    title = optional_text(value.get("title"))
    external_path = optional_text(value.get("externalPath"))
    bullet_fields = value.get("bulletFields")
    req_id = (
        optional_text(bullet_fields[0])
        if isinstance(bullet_fields, Sequence)
        and not isinstance(bullet_fields, (str, bytes))
        and len(bullet_fields) == 1
        else None
    )
    return bool(
        title
        and external_path
        and EXTERNAL_PATH_PATTERN.fullmatch(external_path)
        and req_id
        and re.fullmatch(r"REQ\d+", req_id)
        and REQUISITION_PATTERN.search(external_path.rsplit("/", maxsplit=1)[-1])
        and req_id in external_path.rsplit("/", maxsplit=1)[-1]
        and optional_text(value.get("postedOn"))
        and optional_text(value.get("remoteType"))
        and optional_text(value.get("locationsText"))
    )


def parse_detail_payload(
    payload: Any,
    *,
    expected_record: dict[str, Any],
    base_url: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BiogenSwitzerlandParseError("Biogen detail response must be an object")
    posting_info = payload.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        raise BiogenSwitzerlandParseError("Biogen detail response is missing jobPostingInfo")
    external_path = extract_external_path(expected_record)
    bullet_fields = expected_record.get("bulletFields")
    expected_req_id = optional_text(bullet_fields[0]) if isinstance(bullet_fields, list) else None
    public_url = canonical_public_url(
        posting_info.get("externalUrl"),
        base_url=base_url,
    )
    if (
        not public_url
        or urlsplit(public_url).path != f"/{BIOGEN_SITE}{external_path}"
        or comparable_text(posting_info.get("title"))
        != comparable_text(expected_record.get("title"))
        or optional_text(posting_info.get("jobReqId")) != expected_req_id
        or posting_info.get("jobPostingSiteId") != BIOGEN_SITE
        or posting_info.get("canApply") is not True
        or posting_info.get("posted") is not True
        or not optional_text(posting_info.get("startDate"))
        or not optional_text(posting_info.get("timeType"))
        or not optional_text(posting_info.get("jobDescription"))
        or not extract_swiss_locations(posting_info, expected_record)
    ):
        raise BiogenSwitzerlandParseError(
            "Biogen detail response contains an incomplete or mismatched vacancy"
        )
    return dict(payload)


def canonical_public_url(value: Any, *, base_url: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(base_url)
    path_prefix = f"/{BIOGEN_SITE}/job/"
    if (
        parts.scheme != "https"
        or parts.hostname != expected.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port != expected.port
        or parts.query
        or parts.fragment
        or not parts.path.startswith(path_prefix)
        or not EXTERNAL_PATH_PATTERN.fullmatch(parts.path[len(f"/{BIOGEN_SITE}") :])
    ):
        return None
    return urlunsplit(("https", expected.netloc.casefold(), parts.path, "", ""))


def extract_swiss_locations(
    posting_info: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    values: list[str] = []
    primary = optional_text(posting_info.get("location"))
    country = posting_info.get("country")
    requisition_location = posting_info.get("jobRequisitionLocation")
    requisition_country = (
        requisition_location.get("country") if isinstance(requisition_location, dict) else None
    )
    if primary and (is_swiss_country(country) or is_swiss_country(requisition_country)):
        values.append(primary)

    additional = posting_info.get("additionalLocations")
    if isinstance(additional, Sequence) and not isinstance(additional, (str, bytes)):
        values.extend(
            text
            for item in additional
            if (text := optional_text(item)) and is_swiss_location_text(text)
        )

    if not posting_info:
        listing_location = optional_text(listing.get("locationsText"))
        if listing_location and is_swiss_location_text(listing_location):
            values.append(listing_location)
        external_path = optional_text(listing.get("externalPath"))
        if not values and external_path:
            path_location = unquote(external_path.strip("/").split("/")[1]).replace("-", " ")
            if is_swiss_location_text(path_location):
                values.append(path_location)
    return ", ".join(dict.fromkeys(values)) or None


def is_swiss_country(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return bool(
        optional_text(value.get("id")) == SWITZERLAND_COUNTRY_FACET
        and comparable_text(value.get("descriptor")) == "switzerland"
        and optional_text(value.get("alpha2Code")) in {None, "CH"}
    )


def is_swiss_location_text(value: str) -> bool:
    return value.casefold().endswith(", switzerland")


def extract_employment_type(
    posting_info: dict[str, Any],
    listing: dict[str, Any],
) -> str | None:
    values = [
        optional_text(posting_info.get("timeType")),
        optional_text(posting_info.get("remoteType")) or optional_text(listing.get("remoteType")),
    ]
    return ", ".join(dict.fromkeys(value for value in values if value)) or None


def extract_external_path(record: dict[str, Any]) -> str:
    value = optional_text(record.get("externalPath"))
    return value if value and EXTERNAL_PATH_PATTERN.fullmatch(value) else ""


def page_offsets(total: int) -> list[int]:
    if total <= 0:
        return []
    return list(range(0, total, WORKDAY_RESULTS_PER_PAGE))


def deduplicate_biogen_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_external_path(job.raw) or job.url or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(html.unescape(text)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def comparable_text(value: Any) -> str:
    return " ".join((optional_text(value) or "").casefold().split())


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
