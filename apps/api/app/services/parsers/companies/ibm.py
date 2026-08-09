from __future__ import annotations

import html
import re
from collections.abc import Iterable
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

IBM_JOBS_BASE_URL = "https://www.ibm.com/de-de/careers/search?field_keyword_05[0]=Switzerland"
IBM_JOBS_API_URL = "https://www-api.ibm.com/search/api/v1/ibmcom/appid/careers/responseFormat/json"
IBM_RESULTS_PER_PAGE = 30
IBM_SWITZERLAND_FILTER = "field_keyword_05:Switzerland"
IBM_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_ID_PATTERN = re.compile(r"^\d+$")


class IbmParseError(DirectCompanyRequestError):
    pass


class IbmJobsParser:
    """Collect IBM vacancies targeted to Switzerland from IBM Search."""

    parser_id = "ibm"

    def __init__(
        self,
        *,
        base_url: str = IBM_JOBS_BASE_URL,
        api_url: str = IBM_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**IBM_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
        except IbmParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("IBM vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("IBM vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ibm_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} IBM Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} API page requests"
            ),
        )

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        offset: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        response = client.get(
            self.api_url,
            params={
                "scope": "careers2",
                "rmdt": "ALL",
                "appid": "careers",
                "fr": offset,
                "nr": IBM_RESULTS_PER_PAGE,
                "page": (offset // IBM_RESULTS_PER_PAGE) + 1,
                "query": "",
                "filter": IBM_SWITZERLAND_FILTER,
            },
        )
        response.raise_for_status()
        start_index, total, records = parse_listing_payload(response.json())
        if start_index != offset:
            raise IbmParseError(
                f"IBM returned start index {start_index} for requested offset {offset}"
            )
        return offset, total, records

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        pages_fetched = 0
        last_total = 0
        last_unique = 0

        for catalog_pass in range(self.max_catalog_passes):
            initial_page = self.fetch_listing_page(client, offset=0)
            pages_fetched += 1
            expected_total = initial_page[1]
            last_total = expected_total
            required_pages = max(1, ceil(expected_total / IBM_RESULTS_PER_PAGE))
            if required_pages > self.max_pages:
                raise IbmParseError(
                    f"IBM exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [initial_page]
            for offset in range(
                IBM_RESULTS_PER_PAGE,
                expected_total,
                IBM_RESULTS_PER_PAGE,
            ):
                page_results.append(self.fetch_listing_page(client, offset=offset))
                pages_fetched += 1

            records_by_id: dict[str, dict[str, Any]] = {}
            catalog_changed = False
            pass_records = 0
            for offset, page_total, records in page_results:
                if page_total != expected_total:
                    catalog_changed = True
                    break
                if offset < expected_total and not records:
                    catalog_changed = True
                    break
                pass_records += len(records)
                for record in records:
                    job_id = extract_job_id(record)
                    if not job_id:
                        continue
                    normalized = dict(record)
                    normalized["attributes"] = flatten_docattributes(record.get("docattributes"))
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)

            last_unique = len(records_by_id)
            if catalog_changed or pass_records != expected_total:
                continue
            if last_unique == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total

        raise IbmParseError(
            f"IBM yielded only {last_unique} unique vacancies of {last_total} "
            f"after {self.max_catalog_passes} catalog passes"
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        attributes = record.get("attributes")
        attributes = (
            attributes
            if isinstance(attributes, dict)
            else flatten_docattributes(record.get("docattributes"))
        )
        job_id = extract_job_id(record)
        public_url = build_job_url(job_id) if job_id else optional_text(record.get("url"))

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company="IBM",
            location=optional_text(attributes.get("field_keyword_19")),
            url=public_url,
            apply_url=public_url,
            posted_at=(
                optional_text(attributes.get("effectivedate"))
                or optional_text(attributes.get("dcdate"))
            ),
            employment_type=optional_text(attributes.get("field_keyword_17")),
            seniority=optional_text(attributes.get("field_keyword_18")),
            description=html_to_text(
                optional_text(attributes.get("raw_body"))
                or optional_text(record.get("description"))
                or ""
            ),
            raw=dict(record),
        )


def parse_listing_payload(
    payload: Any,
) -> tuple[int, int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise IbmParseError("IBM jobs response must be an object")
    resultset = payload.get("resultset")
    resultset = resultset if isinstance(resultset, dict) else {}
    searchresults = resultset.get("searchresults")
    if not isinstance(searchresults, dict):
        raise IbmParseError("IBM jobs response has invalid search results")

    total = searchresults.get("totalresults")
    start_index = searchresults.get("startindex")
    num_results = searchresults.get("numresults")
    records = searchresults.get("searchresultlist")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise IbmParseError("IBM jobs response has an invalid total")
    if isinstance(start_index, bool) or not isinstance(start_index, int) or start_index < 0:
        raise IbmParseError("IBM jobs response has an invalid start index")
    if isinstance(num_results, bool) or not isinstance(num_results, int):
        raise IbmParseError("IBM jobs response has an invalid result count")
    if not isinstance(records, list) or num_results != len(records):
        raise IbmParseError("IBM jobs response has invalid vacancies")

    normalized: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            raise IbmParseError("IBM jobs response contains an invalid vacancy")
        attributes = flatten_docattributes(item.get("docattributes"))
        if (
            not extract_job_id(item)
            or not optional_text(item.get("title"))
            or not optional_text(item.get("url"))
            or optional_text(attributes.get("country")) != "ch"
            or optional_text(attributes.get("field_keyword_05")) != "Switzerland"
        ):
            raise IbmParseError("IBM jobs response contains an incomplete or non-Swiss vacancy")
        normalized.append(item)
    return start_index, total, normalized


def flatten_docattributes(value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        raise IbmParseError("IBM vacancy has invalid document attributes")
    attributes: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict) or len(item) != 1:
            raise IbmParseError("IBM vacancy has invalid document attributes")
        key, item_value = next(iter(item.items()))
        if key in attributes:
            raise IbmParseError("IBM vacancy has duplicate document attributes")
        attributes[str(key)] = item_value
    return attributes


def extract_job_id(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    try:
        attributes = flatten_docattributes(record.get("docattributes"))
    except IbmParseError:
        attributes = {}
    attribute_id = optional_text(attributes.get("field_text_01"))
    url = optional_text(record.get("url"))
    query_id = None
    if url:
        query_id = optional_text(parse_qs(urlsplit(url).query).get("jobId", [None])[0])
    if attribute_id and query_id and attribute_id != query_id:
        return None
    job_id = attribute_id or query_id
    return job_id if job_id and JOB_ID_PATTERN.fullmatch(job_id) else None


def build_job_url(job_id: str) -> str:
    query = urlencode({"jobId": job_id, "source": "WEB_Search_EMEA"})
    return f"https://careers.ibm.com/de_DE/careers/JobDetail?{query}"


def deduplicate_ibm_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = extract_job_id_from_url(job.url)
        key = job_id or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def extract_job_id_from_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    job_id = optional_text(parse_qs(urlsplit(text).query).get("jobId", [None])[0])
    return job_id if job_id and JOB_ID_PATTERN.fullmatch(job_id) else None


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
