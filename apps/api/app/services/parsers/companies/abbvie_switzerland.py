from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ABBVIE_SWITZERLAND_JOBS_URL = (
    "https://careers.abbvie.com/en/jobs?q=&options=&page=1&la=47.3768866&"
    "lo=8.541694&ln=Z%C3%BCrich%2C+Switzerland&lr=100"
)
ABBVIE_CANONICAL_JOBS_URL = "https://careers.abbvie.com/en/jobs"
ABBVIE_COMPANY = "AbbVie AG"
ABBVIE_PAGE_TITLE = "Job Search | AbbVie"
ABBVIE_COUNTRY_FACET_ID = "17445"
ABBVIE_FILTER_VALUES = {
    "q": [""],
    "options": [""],
    "la": ["47.3768866"],
    "lo": ["8.541694"],
    "ln": ["Zürich, Switzerland"],
    "lr": ["100"],
}
ABBVIE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
ABBVIE_JOB_PATH_PATTERN = re.compile(r"^/en/job/([a-z0-9]+(?:-[a-z0-9]+)*)-jid-(\d+)$")
ABBVIE_TOTAL_PATTERN = re.compile(r"^(\d+)\s+result\(s\)$")
ABBVIE_EXTERNAL_ID_PATTERN = re.compile(r"^R\d+$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class AbbVieSwitzerlandParseError(DirectCompanyRequestError):
    pass


class AbbVieSwitzerlandJobsParser:
    """Collect the complete AbbVie catalog around Zürich, Switzerland."""

    parser_id = "abbvie_switzerland"

    def __init__(
        self,
        *,
        base_url: str = ABBVIE_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_jobs: int = 1_000,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(20, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=ABBVIE_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records = self.collect_listing(client)
                self.enrich_records(client, records)
        except AbbVieSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("AbbVie Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("AbbVie Switzerland vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_abbvie_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} AbbVie Switzerland vacancies from the "
                "complete Zürich-area Attrax catalog"
            ),
        )

    def collect_listing(self, client: httpx.Client) -> list[dict[str, Any]]:
        first_url = build_page_url(self.base_url, 1)
        first_response = client.get(first_url, headers={"Referer": ABBVIE_CANONICAL_JOBS_URL})
        first_response.raise_for_status()
        records, total = parse_listing_html(
            first_response.text,
            page_url=str(first_response.url),
            expected_url=first_url,
            page_number=1,
        )
        if total > self.max_jobs:
            raise AbbVieSwitzerlandParseError(
                f"AbbVie exposes {total} jobs, above the configured limit of {self.max_jobs}"
            )
        if total == 0:
            return []
        if not records:
            raise AbbVieSwitzerlandParseError(
                "AbbVie careers catalog has a positive total but no vacancies"
            )

        page_count = math.ceil(total / len(records))
        if page_count > self.max_pages:
            raise AbbVieSwitzerlandParseError(
                f"AbbVie catalog requires {page_count} pages, above the configured "
                f"limit of {self.max_pages}"
            )
        for page_number in range(2, page_count + 1):
            page_url = build_page_url(self.base_url, page_number)
            response = client.get(page_url, headers={"Referer": first_url})
            response.raise_for_status()
            page_records, page_total = parse_listing_html(
                response.text,
                page_url=str(response.url),
                expected_url=page_url,
                page_number=page_number,
            )
            if page_total != total:
                raise AbbVieSwitzerlandParseError("AbbVie catalog total changed during pagination")
            records.extend(page_records)

        internal_ids = [optional_text(record.get("internal_id")) for record in records]
        external_ids = [optional_text(record.get("id")) for record in records]
        if (
            len(records) != total
            or len(set(internal_ids)) != len(internal_ids)
            or len(set(external_ids)) != len(external_ids)
        ):
            raise AbbVieSwitzerlandParseError(
                "AbbVie catalog does not reconcile with its result total"
            )
        return records

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
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
                return record, detail
            except (httpx.HTTPError, AbbVieSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], int]:
    if canonical_search_url(page_url) != canonical_search_url(expected_url):
        raise AbbVieSwitzerlandParseError("AbbVie catalog returned an unexpected page")
    query = parse_qs(urlsplit(page_url).query, keep_blank_values=True)
    if query.get("page") != [str(page_number)]:
        raise AbbVieSwitzerlandParseError("AbbVie catalog returned a different page number")

    page = Selector(page_html)
    title = selector_text(page, "title")
    canonical = canonical_jobs_url(
        optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    )
    headings = {selector_text(node) for node in page.css("h1")}
    if (
        title != ABBVIE_PAGE_TITLE
        or canonical != ABBVIE_CANONICAL_JOBS_URL
        or headings != {"Job Results"}
    ):
        raise AbbVieSwitzerlandParseError("AbbVie careers page has an unexpected identity")

    expected_inputs = {
        "location-latitude": "47.3768866",
        "location-longitude": "8.541694",
        "location-name": "Zürich, Switzerland",
        "location-radius": "100",
    }
    for name, expected_value in expected_inputs.items():
        values = set(page.css(f'input[name="{name}"]::attr(value)').getall())
        if values != {expected_value}:
            raise AbbVieSwitzerlandParseError(
                "AbbVie careers page has an unexpected Zürich-area filter"
            )

    empty_message = "We are sorry but your search has returned no results."
    visible_text = " ".join(page.css("body ::text").getall())
    if empty_message in visible_text:
        if page.css(".attrax-vacancy-tile") or any(
            ABBVIE_TOTAL_PATTERN.fullmatch(optional_text(raw) or "")
            and int(ABBVIE_TOTAL_PATTERN.fullmatch(optional_text(raw) or "").group(1)) > 0
            for raw in page.css(".attrax-pagination__total-results::text").getall()
        ):
            raise AbbVieSwitzerlandParseError("AbbVie empty result contradicts its catalog")
        return [], 0

    total_values = {
        int(match.group(1))
        for raw in page.css(".attrax-pagination__total-results::text").getall()
        if (match := ABBVIE_TOTAL_PATTERN.fullmatch(optional_text(raw) or ""))
    }
    if len(total_values) != 1:
        raise AbbVieSwitzerlandParseError("AbbVie careers page is missing its result total")
    total = total_values.pop()

    country_facets = page.css(f'li[data-option-id="{ABBVIE_COUNTRY_FACET_ID}"]')
    if len(country_facets) != 1:
        raise AbbVieSwitzerlandParseError("AbbVie careers page is missing its Switzerland facet")
    country_name = selector_text(country_facets[0], ".filter-text")
    country_count = parse_parenthesized_count(selector_text(country_facets[0], ".filter-count"))
    if country_name != "Switzerland" or country_count != total:
        raise AbbVieSwitzerlandParseError(
            "AbbVie Switzerland facet does not match the result total"
        )

    records: list[dict[str, Any]] = []
    for tile in page.css(".attrax-vacancy-tile"):
        class_tokens = set((optional_text(tile.css("::attr(class)").get()) or "").split())
        internal_id = optional_text(tile.css("::attr(data-jobid)").get())
        title_links = tile.css("a.attrax-vacancy-tile__title[href]")
        title_value = selector_text(title_links[0]) if len(title_links) == 1 else None
        href = optional_text(title_links[0].css("::attr(href)").get()) if title_links else None
        detail_url = canonical_job_url(urljoin(page_url, href or ""))
        path_match = (
            ABBVIE_JOB_PATH_PATTERN.fullmatch(urlsplit(detail_url).path) if detail_url else None
        )
        location = selector_text(
            tile,
            ".attrax-vacancy-tile__location-freetext .attrax-vacancy-tile__item-value",
        )
        reference = selector_text(
            tile,
            ".attrax-vacancy-tile__reference .attrax-vacancy-tile__item-value",
        )
        external_id = selector_text(
            tile,
            ".attrax-vacancy-tile__externalreference .attrax-vacancy-tile__item-value",
        )
        employment_type = selector_text(
            tile,
            ".attrax-vacancy-tile__option-job-type .attrax-vacancy-tile__item-value",
        )
        function = selector_text(
            tile,
            ".attrax-vacancy-tile__option-function .attrax-vacancy-tile__item-value",
        )
        experience_level = selector_text(
            tile,
            ".attrax-vacancy-tile__option-experience-level .attrax-vacancy-tile__item-value",
        )
        work_location_type = selector_text(
            tile,
            ".attrax-vacancy-tile__option-work-location-type .attrax-vacancy-tile__item-value",
        )
        description = selector_text(
            tile,
            ".attrax-vacancy-tile__description .attrax-vacancy-tile__item-value",
        )
        if (
            "attrax-vacancy-tile--switzerland" not in class_tokens
            or "attrax-vacancy-tile--abbvie" not in class_tokens
            or not internal_id
            or not internal_id.isdigit()
            or not path_match
            or path_match.group(2) != internal_id
            or not title_value
            or not location
            or not reference
            or not UUID_PATTERN.fullmatch(reference)
            or not external_id
            or not ABBVIE_EXTERNAL_ID_PATTERN.fullmatch(external_id)
            or not employment_type
            or not function
            or not experience_level
            or not work_location_type
            or not description
        ):
            raise AbbVieSwitzerlandParseError(
                "AbbVie catalog contains an incomplete or out-of-scope vacancy"
            )
        records.append(
            {
                "id": external_id,
                "internal_id": internal_id,
                "reference": reference,
                "title": title_value,
                "company": ABBVIE_COMPANY,
                "location": swiss_location(location),
                "location_raw": location,
                "employment_type": employment_type,
                "function": function,
                "experience_level": experience_level,
                "work_location_type": work_location_type,
                "description": description,
                "url": detail_url,
                "page_number": page_number,
                "catalog_total": total,
            }
        )
    return records, total


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"))
    if canonical_job_url(page_url) != expected_url:
        raise AbbVieSwitzerlandParseError("AbbVie detail page returned a different vacancy")
    page = Selector(page_html)
    canonical = canonical_job_url(
        optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    )
    title = selector_text(page, "h1")
    if canonical != expected_url or comparable_text(title) != comparable_text(
        expected_record.get("title")
    ):
        raise AbbVieSwitzerlandParseError("AbbVie detail page has invalid vacancy identity")

    postings: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            candidate = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            postings.append(candidate)
    if len(postings) != 1:
        raise AbbVieSwitzerlandParseError("AbbVie detail page is missing its JobPosting metadata")
    posting = postings[0]
    organization = posting.get("hiringOrganization")
    organization = organization if isinstance(organization, dict) else {}
    identifier = posting.get("identifier")
    identifier = identifier if isinstance(identifier, dict) else {}
    industries = string_list(posting.get("industry"))
    employment_types = string_list(posting.get("employmentType"))
    localities = posting_localities(posting)
    description = html_to_text(optional_text(posting.get("description")) or "")
    if (
        canonical_job_url(posting.get("url")) != expected_url
        or comparable_text(posting.get("title")) != comparable_text(expected_record.get("title"))
        or optional_text(organization.get("name")) != "AbbVie"
        or comparable_text(identifier.get("name")) != "abbvie"
        or comparable_text(identifier.get("value"))
        != comparable_text(expected_record.get("reference"))
        or comparable_text(expected_record.get("function"))
        not in {comparable_text(value) for value in industries}
        or comparable_text(expected_record.get("employment_type"))
        not in {comparable_text(value) for value in employment_types}
        or {comparable_text(value) for value in localities}
        != {comparable_text(expected_record.get("location_raw"))}
        or len(description) < 100
    ):
        raise AbbVieSwitzerlandParseError("AbbVie detail page has invalid JobPosting metadata")

    apply_urls = {
        value
        for raw in page.css("a.jobApplyBtn[href]::attr(href)").getall()
        if (
            value := canonical_apply_url(
                urljoin(page_url, raw),
                expected_internal_id=optional_text(expected_record.get("internal_id")) or "",
            )
        )
    }
    if len(apply_urls) != 1:
        raise AbbVieSwitzerlandParseError(
            "AbbVie detail page is missing its direct application URL"
        )
    return {
        "title": title,
        "company": ABBVIE_COMPANY,
        "location": swiss_location(localities[0]),
        "employment_type": employment_types[0],
        "function": industries[0],
        "description": description,
        "url": canonical,
        "apply_url": apply_urls.pop(),
        "posted_at": optional_text(posting.get("datePosted")),
        "job_posting": posting,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="abbvie_switzerland",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=ABBVIE_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority=optional_text(record.get("experience_level")),
        description=(
            optional_multiline_text(detail.get("description"))
            or optional_multiline_text(record.get("description"))
        ),
        raw=dict(record),
    )


def build_page_url(base_url: str, page_number: int) -> str:
    parts = urlsplit(base_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["page"] = [str(page_number)]
    pairs = [(key, item) for key, values in query.items() for item in values]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), ""))


def canonical_search_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    page = query.pop("page", None)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "careers.abbvie.com"
        or parts.path.rstrip("/") != "/en/jobs"
        or query != ABBVIE_FILTER_VALUES
        or not page
        or len(page) != 1
        or not page[0].isdigit()
        or int(page[0]) < 1
        or parts.fragment
    ):
        return None
    return build_page_url(ABBVIE_SWITZERLAND_JOBS_URL, int(page[0]))


def canonical_jobs_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "careers.abbvie.com"
        or parts.path.rstrip("/") != "/en/jobs"
        or parts.query
        or parts.fragment
    ):
        return None
    return ABBVIE_CANONICAL_JOBS_URL


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "careers.abbvie.com"
        or not ABBVIE_JOB_PATH_PATTERN.fullmatch(path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "careers.abbvie.com", path, "", ""))


def canonical_apply_url(value: Any, *, expected_internal_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    workflow_ids = query.get("workflowId")
    vacancy_ids = query.get("vacancyId")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "careers.abbvie.com"
        or parts.path.casefold() != "/en/workflow"
        or set(query) != {"workflowId", "vacancyId"}
        or not workflow_ids
        or len(workflow_ids) != 1
        or not UUID_PATTERN.fullmatch(workflow_ids[0])
        or vacancy_ids != [expected_internal_id]
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "careers.abbvie.com", parts.path, parts.query, ""))


def posting_localities(posting: dict[str, Any]) -> list[str]:
    locations = posting.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    if not isinstance(locations, list):
        return []
    result: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if not isinstance(address, dict):
            continue
        locality = optional_text(address.get("addressLocality"))
        if locality:
            result.append(locality)
    return list(dict.fromkeys(result))


def string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item for raw in values if (item := optional_text(raw))]


def parse_parenthesized_count(value: Any) -> int | None:
    match = re.fullmatch(r"\((\d+)\)", optional_text(value) or "")
    return int(match.group(1)) if match else None


def swiss_location(value: Any) -> str | None:
    location = optional_text(value)
    if not location:
        return None
    if comparable_text(location).endswith("switzerland"):
        return location
    return f"{location}, Switzerland"


def deduplicate_abbvie_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text)) or ""


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    if not selected:
        return None
    return optional_text(" ".join(str(value) for value in selected[0].css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line) or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip() or None
