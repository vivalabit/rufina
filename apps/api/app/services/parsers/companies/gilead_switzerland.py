from __future__ import annotations

import html
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

GILEAD_SWITZERLAND_JOBS_BASE_URL = (
    "https://gilead.wd1.myworkdayjobs.com/gileadcareers?"
    "locations=173342972c1201e6f4862b77b074df3b"
)
GILEAD_TENANT = "gilead"
GILEAD_SITE = "gileadcareers"
GILEAD_SWITZERLAND_LOCATION = "173342972c1201e6f4862b77b074df3b"
GILEAD_SWITZERLAND_LOCATION_NAME = "Switzerland - Zug"
SWITZERLAND_COUNTRY_ID = "187134fccb084a0ea9b4b95f23890dbe"
EXPECTED_COMPANY = "Gilead Sciences Switzerland"
WORKDAY_RESULTS_PER_PAGE = 20
GILEAD_SWITZERLAND_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}


class GileadSwitzerlandParseError(DirectCompanyRequestError):
    pass


class GileadSwitzerlandJobsParser:
    """Collect the complete Gilead Workday catalog for its Swiss location."""

    parser_id = "gilead_switzerland"

    def __init__(
        self,
        *,
        base_url: str = GILEAD_SWITZERLAND_JOBS_BASE_URL,
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
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    @property
    def api_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return (
            f"{parts.scheme}://{parts.netloc}/wday/cxs/"
            f"{GILEAD_TENANT}/{GILEAD_SITE}"
        )

    @property
    def site_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/{GILEAD_SITE}"

    @property
    def listing_api_url(self) -> str:
        return f"{self.api_base_url}/jobs"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **GILEAD_SWITZERLAND_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, total, pages_fetched, catalog_passes = (
                    self.collect_listing_records(client)
                )
                self.enrich_records(client, records)
        except GileadSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Gilead Switzerland Workday request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Gilead Switzerland vacancy parsing failed"
            ) from exc

        verified_records = [record for record in records if is_verified_record(record)]
        jobs = [self.normalize_job(record) for record in verified_records]
        if request.deduplicate:
            jobs = deduplicate_gilead_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} verified Gilead Switzerland vacancies from "
                f"{total} Workday location records across {pages_fetched} page "
                f"requests in {catalog_passes} catalog pass(es)"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_response = client.post(
                self.listing_api_url,
                json=listing_request_payload(offset=0),
            )
            first_response.raise_for_status()
            first_payload = first_response.json()
            total, first_postings = parse_listing_payload(first_payload)
            validate_location_facet(first_payload, expected_total=total)
            pages_fetched += 1

            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise GileadSwitzerlandParseError(
                    "Gilead Switzerland changed its vacancy total during pagination"
                )

            offsets = page_offsets(total)
            if len(offsets) > self.max_pages:
                raise GileadSwitzerlandParseError(
                    f"Gilead Switzerland exposes {len(offsets)} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            page_results = [(0, first_postings)]
            catalog_changed = len(first_postings) != min(
                WORKDAY_RESULTS_PER_PAGE, total
            )
            for offset in offsets[1:]:
                response = client.post(
                    self.listing_api_url,
                    json=listing_request_payload(offset=offset),
                )
                response.raise_for_status()
                page_total, postings = parse_listing_payload(response.json())
                pages_fetched += 1
                if page_total not in {0, total}:
                    catalog_changed = True
                if len(postings) != min(WORKDAY_RESULTS_PER_PAGE, total - offset):
                    catalog_changed = True
                page_results.append((offset, postings))

            records_by_path: dict[str, dict[str, Any]] = {}
            for offset, postings in page_results:
                for posting in postings:
                    external_path = optional_text(posting.get("externalPath"))
                    if not is_safe_external_path(external_path):
                        raise GileadSwitzerlandParseError(
                            "Gilead Switzerland returned an unsafe vacancy path"
                        )
                    normalized = dict(posting)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = total
                    records_by_path.setdefault(external_path, normalized)

            if not catalog_changed and len(records_by_path) == total:
                return list(records_by_path.values()), total, pages_fetched, catalog_pass

        raise GileadSwitzerlandParseError(
            f"Gilead Switzerland yielded {len(records_by_path)} unique vacancies "
            f"of {expected_total or 0} catalog records"
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
            external_path = optional_text(record.get("externalPath"))
            if not is_safe_external_path(external_path):
                return record, None
            try:
                response = client.get(f"{self.api_base_url}{external_path}")
                response.raise_for_status()
                payload = response.json()
                validate_detail_payload(payload, expected_path=external_path)
                return record, payload
            except GileadSwitzerlandParseError as exc:
                record["detail_validation_error"] = str(exc)
                return record, None
            except (httpx.HTTPError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, payload = future.result()
                if payload is not None:
                    record["detail"] = payload

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        posting_info = detail.get("jobPostingInfo")
        posting_info = posting_info if isinstance(posting_info, dict) else {}
        external_path = optional_text(record.get("externalPath"))
        constructed_url = (
            f"{self.site_base_url}{external_path}"
            if is_safe_external_path(external_path)
            else self.base_url
        )
        candidate_url = optional_text(posting_info.get("externalUrl"))
        public_url = (
            candidate_url
            if is_public_job_url(
                candidate_url,
                expected_host=urlsplit(self.base_url).netloc,
            )
            else constructed_url
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
            company=EXPECTED_COMPANY,
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


def listing_request_payload(*, offset: int) -> dict[str, Any]:
    return {
        "appliedFacets": {
            "locations": [GILEAD_SWITZERLAND_LOCATION],
        },
        "limit": WORKDAY_RESULTS_PER_PAGE,
        "offset": offset,
        "searchText": "",
    }


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland Workday response must be an object"
        )
    total = payload.get("total")
    postings = payload.get("jobPostings")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland Workday response has an invalid total"
        )
    if not isinstance(postings, list):
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland Workday response has invalid jobPostings"
        )
    records: list[dict[str, Any]] = []
    for posting in postings:
        if (
            not isinstance(posting, dict)
            or not optional_text(posting.get("title"))
            or not optional_text(posting.get("externalPath"))
        ):
            raise GileadSwitzerlandParseError(
                "Gilead Switzerland Workday response contains an incomplete vacancy"
            )
        records.append(posting)
    return total, records


def iter_facet_nodes(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if "facetParameter" in value:
            yield value
        for child in value.values():
            yield from iter_facet_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_facet_nodes(child)


def validate_location_facet(payload: Any, *, expected_total: int) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("facets"), list):
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland Workday response is missing its facets"
        )
    location_facets = [
        facet
        for facet in iter_facet_nodes(payload["facets"])
        if facet.get("facetParameter") == "locations"
    ]
    if not location_facets:
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland Workday response is missing its location facet"
        )
    matches: list[dict[str, Any]] = []
    for facet in location_facets:
        values = facet.get("values")
        if not isinstance(values, list):
            continue
        matches.extend(
            item
            for item in values
            if isinstance(item, dict)
            and item.get("id") == GILEAD_SWITZERLAND_LOCATION
        )
    if expected_total == 0 and not matches:
        return
    if (
        len(matches) != 1
        or optional_text(matches[0].get("descriptor"))
        != GILEAD_SWITZERLAND_LOCATION_NAME
        or matches[0].get("count") != expected_total
    ):
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland Workday response is missing its verified location facet"
        )


def validate_detail_payload(payload: Any, *, expected_path: str) -> None:
    if not isinstance(payload, dict):
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland detail response must be an object"
        )
    posting_info = payload.get("jobPostingInfo")
    organization = payload.get("hiringOrganization")
    organization_name = (
        optional_text(organization.get("name"))
        if isinstance(organization, dict)
        else None
    )
    if (
        not isinstance(posting_info, dict)
        or not optional_text(posting_info.get("title"))
        or not organization_name
        or "gilead" not in organization_name.casefold()
        or not is_swiss_posting(posting_info)
    ):
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland detail response has an unexpected identity"
        )
    external_url = optional_text(posting_info.get("externalUrl"))
    if external_url and urlsplit(external_url).path != f"/{GILEAD_SITE}{expected_path}":
        raise GileadSwitzerlandParseError(
            "Gilead Switzerland detail response changed its vacancy path"
        )


def is_verified_record(record: dict[str, Any]) -> bool:
    if record.get("detail_error") and "detail" not in record:
        return True
    detail = record.get("detail")
    if not isinstance(detail, dict):
        return False
    posting_info = detail.get("jobPostingInfo")
    organization = detail.get("hiringOrganization")
    organization_name = (
        optional_text(organization.get("name"))
        if isinstance(organization, dict)
        else None
    )
    return bool(
        isinstance(posting_info, dict)
        and organization_name
        and "gilead" in organization_name.casefold()
        and is_swiss_posting(posting_info)
    )


def is_swiss_posting(posting_info: dict[str, Any]) -> bool:
    if is_swiss_country(posting_info.get("country")):
        return True
    requisition_location = posting_info.get("jobRequisitionLocation")
    return bool(
        isinstance(requisition_location, dict)
        and is_swiss_country(requisition_location.get("country"))
    )


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
            descriptor
            and descriptor.casefold()
            in {"switzerland", "schweiz", "suisse", "svizzera"}
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
        optional_text(posting_info.get("remoteType"))
        or optional_text(listing.get("remoteType")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def page_offsets(total: int) -> list[int]:
    return list(range(0, total, WORKDAY_RESULTS_PER_PAGE)) if total > 0 else []


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
        and parts.path.startswith(f"/{GILEAD_SITE}/job/")
        and not parts.query
        and not parts.fragment
    )


def deduplicate_gilead_switzerland_jobs(
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
