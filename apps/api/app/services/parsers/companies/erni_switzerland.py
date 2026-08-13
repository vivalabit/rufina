from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ERNI_SWITZERLAND_JOBS_URL = "https://www.betterask.erni/ch-en/job-opportunities/"
ERNI_TEAMTAILOR_JOBS_URL = "https://weareerniswjobs.teamtailor.com/jobs"
ERNI_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "ERNI Schweiz AG"
SCHEMA_COMPANY = "ERNI"
ERNI_HOST = "www.betterask.erni"
TEAMTAILOR_HOST = "weareerniswjobs.teamtailor.com"
CATALOG_PATH_PATTERN = re.compile(r"^/ch-(?:en|de)/job-opportunities/$")
JOB_PATH_PATTERN = re.compile(r"^/ch-(?:en|de)/switzerland-jobs/(\d+)/$")
TEAMTAILOR_JOB_PATH_PATTERN = re.compile(r"^/jobs/(\d+)-[a-z0-9][a-z0-9-]*$")
TEAMTAILOR_APPLY_PATH_PATTERN = re.compile(r"^/jobs/(\d+)-[a-z0-9][a-z0-9-]*/applications/new$")
SWISS_OFFICES = {
    "Basel",
    "Bern",
    "Lucerne",
    "Luzern",
    "Zurich",
    "Zürich",
}


class ErniSwitzerlandParseError(DirectCompanyRequestError):
    pass


class ErniSwitzerlandJobsParser:
    """Collect ERNI Switzerland jobs and cross-check them against Teamtailor."""

    parser_id = "erni_switzerland"

    def __init__(
        self,
        *,
        base_url: str = ERNI_SWITZERLAND_JOBS_URL,
        catalog_url: str = ERNI_TEAMTAILOR_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(10, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=ERNI_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(response.text, page_url=str(response.url))

                catalog_response = client.get(
                    self.catalog_url,
                    headers={"Referer": self.base_url},
                )
                catalog_response.raise_for_status()
                catalog_ids = parse_teamtailor_catalog_html(
                    catalog_response.text,
                    page_url=str(catalog_response.url),
                    expected_url=self.catalog_url,
                )
                listing_ids = {str(record["id"]) for record in records}
                if catalog_ids != listing_ids:
                    raise ErniSwitzerlandParseError(
                        "ERNI Switzerland catalog does not match Teamtailor"
                    )

                self.enrich_records(client, records)
        except ErniSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("ERNI Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("ERNI Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_erni_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} ERNI Switzerland vacancies from the complete "
                "official catalog cross-checked against Teamtailor"
            ),
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
            try:
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
            except (httpx.HTTPError, ErniSwitzerlandParseError, ValueError) as exc:
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
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=optional_text(detail.get("location")) or optional_text(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=optional_text(detail.get("employment_type"))
            or optional_text(record.get("work_model")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    if canonical_catalog_url(page_url) is None:
        raise ErniSwitzerlandParseError("ERNI Switzerland catalog redirected unexpectedly")

    page = Selector(page_html)
    canonical = canonical_catalog_url(page.css('link[rel="canonical"]::attr(href)').get())
    if canonical is None:
        raise ErniSwitzerlandParseError("ERNI Switzerland catalog has no valid canonical URL")

    catalogs = page.css("#shortcut-wrapper .offer-list-wrapper")
    if len(catalogs) != 1:
        raise ErniSwitzerlandParseError(
            "ERNI Switzerland listing is missing its official vacancy catalog"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in catalogs[0].css(".offer-wrapper"):
        job_id = optional_text(card.css("::attr(data-id-job)").get())
        title = selector_text(card, ".details .title")
        summary = selector_text(card, ".details p")
        href = optional_text(card.css("a.offer-btn::attr(href)").get())
        url = canonical_job_url(urljoin(page_url, href or ""))
        url_id = extract_job_id(url)
        location, department, work_model = parse_listing_summary(summary)
        data_search = optional_text(card.css("::attr(data-search)").get())
        expected_search = f"{title} - {summary}" if title and summary else None
        if (
            not job_id
            or not job_id.isdigit()
            or job_id != url_id
            or not title
            or not summary
            or not url
            or not location
            or not work_model
            or comparable_text(data_search) != comparable_text(expected_search)
        ):
            raise ErniSwitzerlandParseError(
                "ERNI Switzerland listing contains an incomplete vacancy"
            )
        if job_id in seen_ids:
            raise ErniSwitzerlandParseError(
                "ERNI Switzerland listing contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": EXPECTED_COMPANY,
                "location": location,
                "department": department,
                "work_model": work_model,
                "summary": summary,
                "url": url,
            }
        )
    return records


def parse_teamtailor_catalog_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> set[str]:
    if canonical_teamtailor_catalog_url(page_url) != canonical_teamtailor_catalog_url(expected_url):
        raise ErniSwitzerlandParseError("ERNI Teamtailor catalog redirected unexpectedly")

    page = Selector(page_html)
    ids: list[str] = []
    for href in page.css('a[href*="weareerniswjobs.teamtailor.com/jobs/"]::attr(href)').getall():
        job_id = extract_teamtailor_job_id(href)
        if job_id:
            ids.append(job_id)
    if len(ids) != len(set(ids)):
        raise ErniSwitzerlandParseError("ERNI Teamtailor catalog contains duplicate vacancies")
    return set(ids)


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"))
    if canonical_job_url(page_url) != expected_url:
        raise ErniSwitzerlandParseError("ERNI detail page returned a different vacancy")

    page = Selector(page_html)
    canonical = canonical_job_url(page.css('link[rel="canonical"]::attr(href)').get())
    title = selector_text(page, ".page-header h1.entry-title")
    summary = selector_text(page, ".page-header .col-xl-6 > p b")
    if (
        canonical != expected_url
        or comparable_text(title) != comparable_text(expected_record.get("title"))
        or comparable_text(summary) != comparable_text(expected_record.get("summary"))
    ):
        raise ErniSwitzerlandParseError("ERNI detail page contains a mismatched vacancy")

    metadata = extract_jobposting_metadata(page, expected_record=expected_record)
    description = extract_description(page)
    apply_url = extract_apply_url(page, expected_id=str(expected_record.get("id")))
    if not description or not apply_url:
        raise ErniSwitzerlandParseError("ERNI detail page contains an incomplete vacancy")
    return {
        "id": expected_record.get("id"),
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": metadata["location"],
        "public_url": expected_url,
        "apply_url": apply_url,
        "posted_at": metadata["posted_at"],
        "employment_type": metadata["employment_type"],
        "department": metadata["department"],
        "description": description,
        "jobposting": metadata["schema"],
    }


def extract_jobposting_metadata(
    page: Any,
    *,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    schemas = [
        candidate
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        for candidate in parse_json_objects(raw)
        if candidate.get("@type") == "JobPosting"
    ]
    if len(schemas) != 1:
        raise ErniSwitzerlandParseError("ERNI detail page must contain one JobPosting record")
    schema = schemas[0]
    title = optional_text(schema.get("title"))
    company = nested_text(schema, "hiringOrganization", "name")
    posted_at = normalize_date(schema.get("datePosted"))
    employment_type = optional_text(schema.get("employmentType"))
    department = optional_text(schema.get("industry"))
    location = nested_text(schema, "jobLocation", "address", "addressLocality")
    if (
        comparable_text(title) != comparable_text(expected_record.get("title"))
        or company != SCHEMA_COMPANY
        or not posted_at
        or not employment_type
        or not location
        or not is_swiss_location(location)
        or comparable_text(location) != comparable_text(expected_record.get("location"))
        or comparable_text(department) != comparable_text(expected_record.get("department"))
        or comparable_text(employment_type) != comparable_text(expected_record.get("work_model"))
    ):
        raise ErniSwitzerlandParseError(
            "ERNI JobPosting data is incomplete, non-Swiss, or mismatched"
        )
    return {
        "posted_at": posted_at,
        "employment_type": employment_type,
        "department": department,
        "location": location,
        "schema": schema,
    }


def extract_description(page: Any) -> str | None:
    content = page.css(".page-content .col-lg-6.text")
    if len(content) != 1:
        return None
    parts: list[str] = []
    for node in content[0].css(":scope > h2, :scope > p, :scope > ul > li"):
        text = selector_text(node)
        if text:
            parts.append(f"- {text}" if node.tag == "li" else text)
    return optional_multiline_text("\n".join(parts))


def extract_apply_url(page: Any, *, expected_id: str) -> str | None:
    iframes = page.css("#modalJob iframe::attr(src)").getall()
    if len(iframes) != 1:
        return None
    text = optional_text(iframes[0])
    if not text:
        return None
    parts = urlsplit(html.unescape(text))
    match = TEAMTAILOR_APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != TEAMTAILOR_HOST
        or not match
        or match.group(1) != expected_id
        or parts.query not in {"", "iframe=true"}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", TEAMTAILOR_HOST, parts.path, "", ""))


def parse_listing_summary(value: Any) -> tuple[str | None, str | None, str | None]:
    text = optional_text(value)
    if not text:
        return None, None, None
    parts = [part.strip() for part in text.split(" · ") if part.strip()]
    if len(parts) not in {2, 3}:
        return None, None, None
    location = parts[0]
    department = parts[1] if len(parts) == 3 else None
    work_model = parts[-1]
    if not is_swiss_location(location):
        return None, None, None
    return location, department, work_model


def is_swiss_location(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    offices = [office.strip() for office in text.split(",") if office.strip()]
    return bool(offices) and all(office in SWISS_OFFICES for office in offices)


def parse_json_objects(value: str) -> list[dict[str, Any]]:
    try:
        document = json.loads(html.unescape(value))
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(document, dict):
        return [document]
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    return []


def canonical_catalog_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != ERNI_HOST
        or not CATALOG_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", ERNI_HOST, parts.path, "", ""))


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != ERNI_HOST
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", ERNI_HOST, parts.path, "", ""))


def extract_job_id(value: Any) -> str | None:
    url = canonical_job_url(value)
    if not url:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path)
    return match.group(1) if match else None


def canonical_teamtailor_catalog_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != TEAMTAILOR_HOST
        or parts.path.rstrip("/") != "/jobs"
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://{TEAMTAILOR_HOST}/jobs"


def extract_teamtailor_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = TEAMTAILOR_JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != TEAMTAILOR_HOST
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def nested_text(value: Any, *keys: str) -> str | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return optional_text(current)


def deduplicate_erni_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    if not selected:
        return None
    values = selected[0].css("::text").getall()
    return optional_text(" ".join(values))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(value).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line)).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", html.unescape(str(value))).strip() or None
