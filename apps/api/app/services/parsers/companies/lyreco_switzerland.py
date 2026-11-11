"""Complete Swiss vacancies from Lyreco's official Workday career portal."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

SWISS_COUNTRY_ID = "187134fccb084a0ea9b4b95f23890dbe"
WORKDAY_ORIGIN = "https://lyreco.wd3.myworkdayjobs.com"
WORKDAY_SITE = "Lyreco_Careers"
LYRECO_SWITZERLAND_JOBS_URL = f"{WORKDAY_ORIGIN}/{WORKDAY_SITE}?locationCountry={SWISS_COUNTRY_ID}"
WORKDAY_API = f"{WORKDAY_ORIGIN}/wday/cxs/lyreco/{WORKDAY_SITE}"
LYRECO_COMPANY = "Lyreco Switzerland AG"
PAGE_SIZE = 20
JOB_PATH = re.compile(r"^/job/[^/?#]+/[^/?#]+_(JR-\d+)(?:-\d+)?$")


class LyrecoSwitzerlandParseError(DirectCompanyRequestError):
    pass


class LyrecoSwitzerlandJobsParser:
    parser_id = "lyreco_switzerland"
    handles_request_retries = True

    def __init__(
        self,
        *,
        base_url: str = LYRECO_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_jobs: int = 1000,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # Migrate saved Drupal URLs as well as fresh installations. The employer
        # links this public Workday portal from its own careers page.
        self.base_url = (
            LYRECO_SWITZERLAND_JOBS_URL
            if urlsplit(base_url).hostname in {"www.lyreco.com", "lyreco.com"}
            else base_url
        )
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(4, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        if urlsplit(self.base_url).hostname != urlsplit(WORKDAY_ORIGIN).hostname:
            raise LyrecoSwitzerlandParseError("Lyreco has an unexpected Workday host")
        try:
            with CareerHttpClient(
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                    "Origin": WORKDAY_ORIGIN,
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records = self.collect_listing(client)
                self.enrich_records(client, records)
        except LyrecoSwitzerlandParseError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise DirectCompanyRequestError(f"Lyreco Workday request failed: {exc}") from exc
        jobs = [normalize_job(record) for record in records]
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} Lyreco Switzerland vacancies from the complete Workday country catalog",
        )

    def collect_listing(self, client: CareerHttpClient) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        total: int | None = None
        offset = 0
        while total is None or offset < total:
            response = client.post_catalog(
                WORKDAY_API + "/jobs",
                json={
                    "appliedFacets": {"locationCountry": [SWISS_COUNTRY_ID]},
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                },
            )
            response.raise_for_status()
            payload = response.json()
            page_total, page_records = parse_listing_payload(payload, expected_total=total)
            if total is None:
                total = page_total
                if (
                    total > self.max_jobs
                    or max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) > self.max_pages
                ):
                    raise LyrecoSwitzerlandParseError("Lyreco catalog exceeds its configured limit")
            if total != page_total or len(page_records) != min(PAGE_SIZE, total - offset):
                raise LyrecoSwitzerlandParseError(
                    "Lyreco catalog changed or returned an incomplete page"
                )
            for record in page_records:
                if record["id"] in seen:
                    raise LyrecoSwitzerlandParseError(
                        "Lyreco catalog contains duplicate vacancy IDs"
                    )
                seen.add(record["id"])
                records.append(record)
            offset += PAGE_SIZE
        return records

    def enrich_records(self, client: CareerHttpClient, records: list[dict[str, Any]]) -> None:
        def fetch(record: dict[str, Any]) -> None:
            try:
                response = client.get(WORKDAY_API + record["externalPath"])
                response.raise_for_status()
                record["detail"] = parse_detail_payload(response.json(), record)
            except (httpx.HTTPError, ValueError, LyrecoSwitzerlandParseError) as exc:
                record["detail_error"] = str(exc)

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records) or 1)) as pool:
            for future in as_completed([pool.submit(fetch, record) for record in records]):
                future.result()


def parse_listing_payload(
    payload: Any, *, expected_total: int | None = None
) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise LyrecoSwitzerlandParseError("Lyreco catalog must be an object")
    total, postings = payload.get("total"), payload.get("jobPostings")
    if type(total) is not int or total < 0 or not isinstance(postings, list):
        raise LyrecoSwitzerlandParseError("Lyreco catalog has an invalid total or postings")
    # Subsequent Workday pages omit aggregates, returning total=0, facets=[].
    metadata_omitted = expected_total is not None and total == 0 and payload.get("facets") == []
    if metadata_omitted:
        total = expected_total

    def country_counts(nodes: Any) -> list[int]:
        counts: list[int] = []
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if node.get("facetParameter") == "locationCountry":
                    counts.extend(
                        value.get("count")
                        for value in node.get("values", [])
                        if isinstance(value, dict) and value.get("id") == SWISS_COUNTRY_ID
                    )
                counts.extend(country_counts(node.get("values")))
        return counts

    counts = country_counts(payload.get("facets"))
    if not metadata_omitted and (
        (total and counts != [total]) or (not total and counts not in ([], [0]))
    ):
        raise LyrecoSwitzerlandParseError("Lyreco Switzerland facet does not match its total")
    records = []
    for item in postings:
        if not isinstance(item, dict):
            raise LyrecoSwitzerlandParseError("Lyreco catalog has an invalid vacancy")
        path = item.get("externalPath")
        match = JOB_PATH.fullmatch(path) if isinstance(path, str) else None
        title = text(item.get("title"))
        if not match or not title or "Switzerland" not in item.get("bulletFields", []):
            raise LyrecoSwitzerlandParseError("Lyreco catalog has an invalid or non-Swiss vacancy")
        records.append(
            {
                **item,
                "id": match[1],
                "title": title,
                "url": f"{WORKDAY_ORIGIN}/{WORKDAY_SITE}{path}",
                "location": text(item.get("locationsText")),
                "catalog_total": total,
            }
        )
    return total, records


def parse_detail_payload(payload: Any, record: dict[str, Any]) -> dict[str, Any]:
    detail = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        raise LyrecoSwitzerlandParseError("Lyreco detail is missing jobPostingInfo")
    country = detail.get("country")
    requisition = detail.get("jobRequisitionLocation")
    req_country = requisition.get("country") if isinstance(requisition, dict) else None
    if (
        detail.get("jobReqId") != record["id"]
        or text(detail.get("title")) != record["title"]
        or detail.get("externalUrl") != record["url"]
        or detail.get("jobPostingSiteId") != WORKDAY_SITE
        or not isinstance(country, dict)
        or country.get("id") != SWISS_COUNTRY_ID
        or not isinstance(req_country, dict)
        or req_country.get("id") != SWISS_COUNTRY_ID
    ):
        raise LyrecoSwitzerlandParseError("Lyreco detail has a different vacancy or country")
    description = html_to_text(detail.get("jobDescription"))
    if not description:
        raise LyrecoSwitzerlandParseError("Lyreco detail has no description")
    return {**detail, "description": description}


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail") or {}
    location = text(detail.get("location")) or record.get("location")
    public_url = record["url"]
    return ParsedJob(
        source="lyreco_switzerland",
        title=record["title"],
        company=LYRECO_COMPANY,
        location=f"{location}, Switzerland" if location else "Switzerland",
        url=public_url,
        apply_url=public_url + "/apply",
        posted_at=text(detail.get("startDate")),
        employment_type=text(detail.get("timeType")) or text(record.get("timeType")),
        description=detail.get("description"),
        raw=dict(record),
    )


def text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def html_to_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    page = Selector(value)
    return "\n".join(part.strip() for part in page.css("::text").getall() if part.strip()) or None
