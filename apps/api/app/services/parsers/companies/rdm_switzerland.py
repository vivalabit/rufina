from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

RDM_SWITZERLAND_JOBS_URL = "https://www.rdm.com/career/jobs/?mf-job_country%5B0%5D=ch"
RDM_CAREERS_CANONICAL_URL = "https://www.rdm.com/career/jobs/"
RDM_COMPANY = "Reichle & De-Massari AG"
RDM_PAGE_TITLE = "Vacancies at R&M - R&M"
RDM_HEADING = "Vacancies at R&M"
RDM_JOB_PATH_PATTERN = re.compile(r"^/jobs/([a-z0-9]+(?:-[a-z0-9]+)*)/$")
RDM_COUNTER_PATTERN = re.compile(r"^(\d+)\s+of\s+(\d+)\s+Jobs$")
RDM_POST_ID_PATTERN = re.compile(r"(?:^|\s)postid-(\d+)(?:\s|$)")


class RdmSwitzerlandParseError(DirectCompanyRequestError):
    pass


class RdmSwitzerlandJobsParser:
    """Collect R&M's complete Cloudflare-protected Swiss vacancy catalog."""

    parser_id = "rdm_switzerland"

    def __init__(
        self,
        *,
        base_url: str = RDM_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 45.0,
        max_jobs: int = 100,
        detail_workers: int = 6,
        fetch_page: Callable[[str], ScraplingResponse] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.fetch_page = fetch_page
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            records = (
                self._collect_with_injected_fetcher()
                if self.fetch_page is not None
                else self._collect_public_catalog()
            )
        except RdmSwitzerlandParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError(
                f"R&M Switzerland vacancy request failed: {exc}"
            ) from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_rdm_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} R&M Switzerland vacancies from the complete "
                "verified public careers catalog"
            ),
        )

    def _collect_with_injected_fetcher(self) -> list[dict[str, Any]]:
        assert self.fetch_page is not None
        page = self.fetch_page(self.base_url)
        records = parse_listing_page(
            page,
            page_url=self.base_url,
            expected_url=self.base_url,
            max_jobs=self.max_jobs,
        )
        self._enrich_with_injected_fetcher(records)
        return records

    def _enrich_with_injected_fetcher(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        assert self.fetch_page is not None

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                page = self.fetch_page(record["url"])
                return record, parse_detail_page(
                    page,
                    page_url=record["url"],
                    expected_url=record["url"],
                    expected_title=record["title"],
                )
            except Exception as exc:  # noqa: BLE001 - one detail must not discard the catalog
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["id"] = detail["id"]
                    record["detail"] = detail

    def _collect_public_catalog(self) -> list[dict[str, Any]]:
        # The unfiltered public catalog is accessible without the protected query string.
        # Reconcile every card with the global counter before selecting Swiss locations.
        with httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self.transport,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
            },
        ) as client:
            # A challenge can be transient; retry only access/service failures, not parsing.
            for attempt in range(3):
                response = client.get(RDM_CAREERS_CANONICAL_URL)
                if response.status_code not in {403, 429, 502, 503, 504} or attempt == 2:
                    break
            response.raise_for_status()
            records = parse_listing_page(
                Selector(response.text),
                page_url=str(response.url),
                expected_url=RDM_CAREERS_CANONICAL_URL,
                max_jobs=self.max_jobs,
                global_catalog=True,
            )

            def detail_fetch(url: str) -> ScraplingResponse:
                detail = client.get(url)
                detail.raise_for_status()
                if canonical_job_url(str(detail.url)) != canonical_job_url(url):
                    raise RdmSwitzerlandParseError("R&M detail returned an unexpected page")
                return Selector(detail.text)

            parser = RdmSwitzerlandJobsParser(
                fetch_page=detail_fetch, detail_workers=self.detail_workers
            )
            parser._enrich_with_injected_fetcher(records)
            return records


def parse_listing_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
    global_catalog: bool = False,
) -> list[dict[str, Any]]:
    canonicalizer = canonical_careers_url if global_catalog else canonical_filtered_catalog_url
    if not canonicalizer(page_url) or canonicalizer(page_url) != canonicalizer(expected_url):
        raise RdmSwitzerlandParseError("R&M catalog returned an unexpected page")

    canonical = canonical_careers_url(
        optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    )
    titles = {optional_text(value) for value in page.css("title::text").getall()}
    headings = {selector_text(node) for node in page.css("h1")}
    if (
        canonical != RDM_CAREERS_CANONICAL_URL
        or titles != {RDM_PAGE_TITLE}
        or headings != {RDM_HEADING}
    ):
        raise RdmSwitzerlandParseError("R&M careers page has an unexpected identity")

    counters = [
        match
        for raw in page.css(".col-6::text").getall()
        if (match := RDM_COUNTER_PATTERN.fullmatch(optional_text(raw) or ""))
    ]
    if len(counters) != 1:
        raise RdmSwitzerlandParseError("R&M careers page is missing its result counter")
    filtered_total = int(counters[0].group(1))
    global_total = int(counters[0].group(2))
    if filtered_total > global_total or (global_catalog and filtered_total != global_total):
        raise RdmSwitzerlandParseError("R&M careers page has an invalid result counter")
    if filtered_total > max_jobs:
        raise RdmSwitzerlandParseError(
            f"R&M exposes {filtered_total} jobs, above the configured limit of {max_jobs}"
        )

    links = page.css(".jobs.card-col > .card-wrapper.tiles-default > a[href]")
    if len(links) != filtered_total:
        raise RdmSwitzerlandParseError(
            "R&M careers catalog does not match its filtered result count"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for link in links:
        detail_url = canonical_job_url(
            urljoin(page_url, optional_text(link.css("::attr(href)").get()) or "")
        )
        job_id = extract_job_slug(detail_url)
        title = selector_text(link, ".card-text h3")
        category = selector_text(link, ".card-subtitle")
        location = selector_text(link, ".card-position")
        if (
            not detail_url
            or not job_id
            or not title
            or not category
            or not location
            or (not global_catalog and not is_swiss_location(location))
        ):
            raise RdmSwitzerlandParseError(
                "R&M careers catalog contains an incomplete or out-of-scope vacancy"
            )
        if job_id in seen_ids:
            raise RdmSwitzerlandParseError(
                "R&M careers catalog contains duplicate vacancy identifiers"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": RDM_COMPANY,
                "location": location,
                "category": category,
                "url": detail_url,
                "apply_url": detail_url,
                "listing_page_url": RDM_CAREERS_CANONICAL_URL,
                "filtered_total": filtered_total,
                "global_total": global_total,
            }
        )
    return [record for record in records if is_swiss_location(record["location"])]


def parse_detail_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
) -> dict[str, Any]:
    expected = canonical_job_url(expected_url)
    if canonical_job_url(page_url) != expected:
        raise RdmSwitzerlandParseError("R&M detail page returned a different vacancy")
    canonical = canonical_job_url(
        optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    )
    if canonical != expected:
        raise RdmSwitzerlandParseError("R&M detail page has invalid canonical metadata")

    body_classes = optional_text(page.css("body::attr(class)").get()) or ""
    post_match = RDM_POST_ID_PATTERN.search(body_classes)
    page_id = optional_text(page.css("body::attr(data-pageid)").get())
    job_id = post_match.group(1) if post_match else None
    title = selector_text(page, "h1")
    if not job_id or page_id != job_id or comparable_text(title) != comparable_text(expected_title):
        raise RdmSwitzerlandParseError("R&M detail page returned a different vacancy title")

    info_blocks = page.css(".job-info")
    descriptions = page.css(".main-content.wysiwyg")
    if len(info_blocks) != 1 or len(descriptions) != 1:
        raise RdmSwitzerlandParseError("R&M detail page is missing vacancy content")
    metadata = [
        value for node in info_blocks[0].css(":scope > p") if (value := selector_text(node))
    ]
    location = metadata[0] if metadata else None
    employment_type = metadata[1] if len(metadata) > 1 else None
    description = selector_text(descriptions[0])
    apply_buttons = info_blocks[0].css('a.default-button[popup="applicationForm"]')
    apply_hrefs = apply_buttons[0].css("::attr(href)").getall() if apply_buttons else []
    forms = page.css("#applicationForm")
    if (
        not is_swiss_location(location)
        or not employment_type
        or not description
        or len(description) < 100
        or len(apply_buttons) != 1
        or apply_hrefs
        or len(forms) != 1
    ):
        raise RdmSwitzerlandParseError("R&M detail page has incomplete vacancy metadata")

    return {
        "id": job_id,
        "slug": extract_job_slug(canonical),
        "title": title,
        "company": RDM_COMPANY,
        "location": location,
        "employment_type": employment_type,
        "description": description,
        "url": canonical,
        "apply_url": canonical,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="rdm_switzerland",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=RDM_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=(
            optional_text(detail.get("apply_url"))
            or optional_text(record.get("apply_url"))
            or public_url
        ),
        employment_type=optional_text(detail.get("employment_type")),
        description=optional_text(detail.get("description")),
        raw=dict(record),
    )


def canonical_filtered_catalog_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.rdm.com"
        or parts.path.rstrip("/") != "/career/jobs"
        or query != {"mf-job_country[0]": ["ch"]}
        or parts.fragment
    ):
        return None
    return RDM_SWITZERLAND_JOBS_URL


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.rdm.com"
        or parts.path.rstrip("/") != "/career/jobs"
        or parts.query
        or parts.fragment
    ):
        return None
    return RDM_CAREERS_CANONICAL_URL


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = f"{parts.path.rstrip('/')}/"
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.rdm.com"
        or not RDM_JOB_PATH_PATTERN.fullmatch(path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.rdm.com", path, "", ""))


def extract_job_slug(value: Any) -> str | None:
    url = canonical_job_url(value)
    match = RDM_JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def require_successful_response(response: Any, *, context: str) -> None:
    status = int(getattr(response, "status", 0) or 0)
    if not 200 <= status < 300:
        raise RdmSwitzerlandParseError(f"R&M {context} returned HTTP {status}")


def response_url(response: Any, fallback: str) -> str:
    return optional_text(getattr(response, "url", None)) or fallback


def is_swiss_location(value: Any) -> bool:
    location = comparable_text(value)
    return location.endswith(", switzerland")


def deduplicate_rdm_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    return optional_text(" ".join(str(value) for value in selected[0].css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip() or None
