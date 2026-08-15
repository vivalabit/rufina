from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from scrapling.fetchers import StealthyFetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

CYON_JOBS_BASE_URL = "https://www.cyon.ch/ueber-cyon/jobs"
CYON_COMPANY = "cyon AG"
CYON_PAGE_TITLE = "Arbeiten bei cyon | Freude, Passion und Teamgeist"
CYON_APPLICATION_PATH_PATTERN = re.compile(
    r"^/job/([0-9a-f]{32})/cyon-ag/([a-z0-9]+(?:-[a-z0-9]+)*)$"
)
CYON_SECTION_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CyonParseError(DirectCompanyRequestError):
    pass


class CyonJobsParser:
    """Collect cyon's complete JavaScript-protected careers catalog."""

    parser_id = "cyon"

    def __init__(
        self,
        *,
        base_url: str = CYON_JOBS_BASE_URL,
        timeout_seconds: float = 45.0,
        max_jobs: int = 100,
        fetch_page: Callable[[str], ScraplingResponse] | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.fetch_page = fetch_page or self._fetch_with_browser

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            page = self.fetch_page(self.base_url)
            records = parse_careers_page(
                page,
                page_url=self.base_url,
                max_jobs=self.max_jobs,
            )
        except CyonParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError("cyon vacancy request failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_cyon_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} cyon vacancies from the complete "
                "JavaScript-protected careers catalog"
            ),
        )

    def _fetch_with_browser(self, url: str) -> ScraplingResponse:
        options = {
            "headless": True,
            "disable_resources": True,
            "timeout": round(self.timeout_seconds * 1000),
            "wait_selector": "main",
            "locale": "de-CH",
            "timezone_id": "Europe/Zurich",
            "google_search": True,
        }
        first_error: Exception | None = None
        for real_chrome in (False, True):
            try:
                response = StealthyFetcher.fetch(url, real_chrome=real_chrome, **options)
                status = int(getattr(response, "status", 0) or 0)
                if not 200 <= status < 300:
                    raise CyonParseError(f"cyon returned HTTP {status}")
                return response
            except Exception as exc:
                if not real_chrome:
                    first_error = exc
                    continue
                if isinstance(exc, CyonParseError):
                    raise
                raise CyonParseError("cyon browser fetch failed") from exc
        raise CyonParseError("cyon browser fetch failed") from first_error


def parse_careers_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    canonical_url = canonical_careers_url(page_url)
    if canonical_url is None:
        raise CyonParseError("cyon careers URL is outside the expected scope")

    canonicals = set(page.css('link[rel="canonical"]::attr(href)').getall())
    languages = set(page.css("html::attr(lang)").getall())
    titles = set(page.css("title::text").getall())
    catalog_headings = {optional_text(value) for value in page.css("main h3::text").getall()}
    if (
        canonicals != {canonical_url}
        or languages != {"de-CH"}
        or titles != {CYON_PAGE_TITLE}
        or "Offene Stellen bei cyon" not in catalog_headings
    ):
        raise CyonParseError("cyon careers page has an unexpected identity")

    catalogs = page.css('main div[x-data="cyon_accordion"]')
    if len(catalogs) != 1:
        raise CyonParseError("cyon careers page is missing its official catalog")
    sections = catalogs[0].css(':scope > section[x-data="cyon_accordion_item"]')
    if len(sections) > max_jobs:
        raise CyonParseError(
            f"cyon exposes {len(sections)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_sections: set[str] = set()
    for section in sections:
        section_id = optional_text(section.css(":scope::attr(id)").get())
        title = selector_text(section, ':scope > div[x-bind="toggle"] h2')
        workload = selector_text(section, ':scope > div[x-bind="toggle"] p')
        metadata = [
            optional_text(value)
            for value in section.css(
                ':scope > div[x-show="expanded"] > ul > li span::text'
            ).getall()
        ]
        metadata = [value for value in metadata if value]
        description = selector_text(section, ".prose-job")
        application_urls = {
            canonical_application_url(value)
            for value in section.css('a[href*="my.jobalino.ch/job/"]::attr(href)').getall()
        }
        application_urls.discard(None)
        application_url = next(iter(application_urls)) if len(application_urls) == 1 else None
        job_id = extract_application_id(application_url)

        metadata_by_label: dict[str, str] = {}
        for value in metadata:
            if ":" not in value:
                continue
            label, item_value = value.split(":", 1)
            normalized_value = optional_text(item_value)
            if normalized_value:
                metadata_by_label[comparable_text(label)] = normalized_value
        employment_type = metadata_by_label.get("pensum")
        location = metadata_by_label.get("arbeitsort")
        starts_at = next((value for value in metadata if ":" not in value), None)

        if (
            not section_id
            or not CYON_SECTION_ID_PATTERN.fullmatch(section_id)
            or not title
            or not workload
            or comparable_text(workload) != comparable_text(employment_type)
            or not location
            or "schweiz" not in comparable_text(location)
            or not starts_at
            or not description
            or len(description) < 100
            or not application_url
            or not job_id
        ):
            raise CyonParseError("cyon careers page contains an incomplete or out-of-scope vacancy")
        if job_id in seen_ids or section_id in seen_sections:
            raise CyonParseError("cyon careers page contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        seen_sections.add(section_id)
        records.append(
            {
                "id": job_id,
                "section_id": section_id,
                "title": title,
                "company": CYON_COMPANY,
                "location": location,
                "starts_at": starts_at,
                "employment_type": employment_type,
                "description": description,
                "url": f"{canonical_url}#{section_id}",
                "apply_url": application_url,
            }
        )
    return records


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    public_url = optional_text(record.get("url"))
    title = optional_text(record.get("title"))
    return ParsedJob(
        source="cyon",
        title=title,
        company=CYON_COMPANY,
        location=optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(record.get("apply_url")) or public_url,
        employment_type=optional_text(record.get("employment_type")),
        seniority="Senior" if comparable_text(title).startswith("senior ") else None,
        description=optional_text(record.get("description")),
        raw=dict(record),
    )


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.cyon.ch"
        or parts.path.rstrip("/") != "/ueber-cyon/jobs"
        or parts.query
        or parts.fragment
    ):
        return None
    return CYON_JOBS_BASE_URL


def canonical_application_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "my.jobalino.ch"
        or not CYON_APPLICATION_PATH_PATTERN.fullmatch(parts.path.rstrip("/"))
        or parts.query
        or parts.fragment != "application"
    ):
        return None
    return urlunsplit(("https", "my.jobalino.ch", parts.path.rstrip("/"), "", "application"))


def extract_application_id(value: Any) -> str | None:
    url = canonical_application_url(value)
    match = CYON_APPLICATION_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def deduplicate_cyon_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    return optional_text(" ".join(selected[0].css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", html.unescape(str(value))).strip() or None
