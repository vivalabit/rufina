from __future__ import annotations

import html
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

UNISYS_SWITZERLAND_JOBS_BASE_URL = (
    "https://unisys.wd5.myworkdayjobs.com/External?locationCountry=187134fccb084a0ea9b4b95f23890dbe"
)
UNISYS_TENANT = "unisys"
UNISYS_SITE = "External"
SWITZERLAND_COUNTRY_FACET = "187134fccb084a0ea9b4b95f23890dbe"
WORKDAY_RESULTS_PER_PAGE = 20
UNISYS_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
EXTERNAL_PATH_PATTERN = re.compile(r"^/job/[^/?#]+/[^/?#]+$")
REQUISITION_PATTERN = re.compile(r"_REQ\d+$")


class UnisysSwitzerlandParseError(DirectCompanyRequestError):
    pass


class UnisysSwitzerlandJobsParser:
    """Collect Unisys vacancies from its country-filtered Swiss Workday catalog."""

    parser_id = "unisys_switzerland"

    def __init__(
        self,
        *,
        base_url: str = UNISYS_SWITZERLAND_JOBS_BASE_URL,
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
        return f"{parts.scheme}://{parts.netloc}/wday/cxs/{UNISYS_TENANT}/{UNISYS_SITE}"

    @property
    def site_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/{UNISYS_SITE}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.api_base_url}/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **UNISYS_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except UnisysSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Unisys Switzerland Workday request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Unisys Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_unisys_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Unisys Switzerland vacancies from "
                f"{total} Workday country records across {pages_fetched} page requests"
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
        payload = response.json()
        total, records = parse_listing_payload(payload)
        if offset == 0:
            validate_country_facet(payload, expected_total=total)
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
                raise UnisysSwitzerlandParseError(
                    f"Unisys Switzerland exposes {required_pages} pages, above the "
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

        raise UnisysSwitzerlandParseError(
            f"Unisys Switzerland yielded only {last_unique} unique vacancies of "
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
            except (httpx.HTTPError, UnisysSwitzerlandParseError, ValueError) as exc:
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
        description_html = optional_text(posting_info.get("jobDescription")) or optional_text(
            record.get("jobDescription")
        )
        raw = dict(record)
        return ParsedJob(
            source=self.parser_id,
            title=(optional_text(posting_info.get("title")) or optional_text(record.get("title"))),
            company="Unisys",
            location=extract_swiss_location(posting_info, record) or "Switzerland",
            url=public_url,
            apply_url=public_url,
            posted_at=(
                optional_text(posting_info.get("startDate"))
                or optional_text(posting_info.get("postedOn"))
                or optional_text(record.get("postedOn"))
            ),
            employment_type=optional_text(posting_info.get("timeType")),
            description=html_to_text(description_html) if description_html else None,
            raw=raw,
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise UnisysSwitzerlandParseError("Unisys Switzerland Workday response must be an object")
    total = payload.get("total")
    postings = payload.get("jobPostings")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise UnisysSwitzerlandParseError(
            "Unisys Switzerland Workday response has an invalid total"
        )
    if not isinstance(postings, list):
        raise UnisysSwitzerlandParseError(
            "Unisys Switzerland Workday response has invalid jobPostings"
        )
    records: list[dict[str, Any]] = []
    for posting in postings:
        if not valid_listing_record(posting):
            raise UnisysSwitzerlandParseError(
                "Unisys Switzerland Workday response contains an incomplete vacancy"
            )
        records.append(posting)
    return total, records


def valid_listing_record(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
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
        optional_text(value.get("title"))
        and external_path
        and EXTERNAL_PATH_PATTERN.fullmatch(external_path)
        and req_id
        and re.fullmatch(r"REQ\d+", req_id)
        and REQUISITION_PATTERN.search(external_path.rsplit("/", maxsplit=1)[-1])
        and req_id in external_path.rsplit("/", maxsplit=1)[-1]
        and optional_text(value.get("postedOn"))
        and optional_text(value.get("locationsText"))
    )


def iter_facet_nodes(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if "facetParameter" in value:
            yield value
        for child in value.values():
            yield from iter_facet_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_facet_nodes(child)


def validate_country_facet(payload: Any, *, expected_total: int) -> None:
    facets = payload.get("facets") if isinstance(payload, dict) else None
    if not isinstance(facets, list):
        raise UnisysSwitzerlandParseError(
            "Unisys Switzerland Workday response is missing its country facets"
        )
    country_facets = [
        facet
        for facet in iter_facet_nodes(facets)
        if facet.get("facetParameter") == "locationCountry"
    ]
    matches: list[dict[str, Any]] = []
    for facet in country_facets:
        values = facet.get("values")
        if isinstance(values, list):
            matches.extend(
                value
                for value in values
                if isinstance(value, dict) and value.get("id") == SWITZERLAND_COUNTRY_FACET
            )
    if expected_total == 0 and country_facets and not matches:
        return
    if (
        len(matches) != 1
        or comparable_text(matches[0].get("descriptor")) != "switzerland"
        or matches[0].get("count") != expected_total
    ):
        raise UnisysSwitzerlandParseError(
            "Unisys Switzerland Workday response is missing its verified country facet"
        )


def parse_detail_payload(
    payload: Any,
    *,
    expected_record: dict[str, Any],
    base_url: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise UnisysSwitzerlandParseError("Unisys detail response must be an object")
    posting_info = payload.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        raise UnisysSwitzerlandParseError("Unisys detail response is missing jobPostingInfo")
    external_path = extract_external_path(expected_record)
    bullet_fields = expected_record.get("bulletFields")
    expected_req_id = optional_text(bullet_fields[0]) if isinstance(bullet_fields, list) else None
    public_url = canonical_public_url(
        posting_info.get("externalUrl"),
        base_url=base_url,
    )
    if (
        not public_url
        or urlsplit(public_url).path != f"/{UNISYS_SITE}{external_path}"
        or comparable_text(posting_info.get("title"))
        != comparable_text(expected_record.get("title"))
        or optional_text(posting_info.get("jobReqId")) != expected_req_id
        or optional_text(posting_info.get("jobPostingId"))
        != external_path.rsplit("/", maxsplit=1)[-1]
        or posting_info.get("jobPostingSiteId") != UNISYS_SITE
        or posting_info.get("canApply") is not True
        or posting_info.get("posted") is not True
        or not optional_text(posting_info.get("startDate"))
        or not optional_text(posting_info.get("timeType"))
        or not optional_text(posting_info.get("jobDescription"))
        or not extract_swiss_location(posting_info, expected_record)
    ):
        raise UnisysSwitzerlandParseError(
            "Unisys detail response contains an incomplete or mismatched vacancy"
        )
    return dict(payload)


def canonical_public_url(value: Any, *, base_url: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(base_url)
    path_prefix = f"/{UNISYS_SITE}/job/"
    if (
        parts.scheme != "https"
        or parts.hostname != expected.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port != expected.port
        or parts.query
        or parts.fragment
        or not parts.path.startswith(path_prefix)
        or not EXTERNAL_PATH_PATTERN.fullmatch(parts.path[len(f"/{UNISYS_SITE}") :])
    ):
        return None
    return urlunsplit(("https", expected.netloc.casefold(), parts.path, "", ""))


def extract_swiss_location(
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


def extract_external_path(record: dict[str, Any]) -> str:
    value = optional_text(record.get("externalPath"))
    return value if value and EXTERNAL_PATH_PATTERN.fullmatch(value) else ""


def page_offsets(total: int) -> list[int]:
    if total <= 0:
        return []
    return list(range(0, total, WORKDAY_RESULTS_PER_PAGE))


def deduplicate_unisys_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
