from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import (
    DirectCompanyRequestError,
    ScraplingResponse,
)

ARTIFICIALY_JOBS_BASE_URL = "https://www.artificialy.com/career"
ARTIFICIALY_COMPANY = "Artificialy SA"
ARTIFICIALY_ALLOWED_LOCATIONS = {
    "lugano",
    "zurich",
    "zürich",
    "switzerland",
    "remote",
}
ARTIFICIALY_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,it-CH;q=0.7",
    "Referer": "https://www.google.com/",
}
LINKEDIN_JOB_PATH_PATTERN = re.compile(r"^/jobs/view/(\d+)/?$", re.IGNORECASE)


class ArtificialyParseError(DirectCompanyRequestError):
    pass


class ArtificialyJobsParser:
    """Collect Artificialy's complete server-rendered careers catalog."""

    parser_id = "artificialy"

    def __init__(
        self,
        *,
        base_url: str = ARTIFICIALY_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        fetch_page: Callable[[str], ScraplingResponse] | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.fetch_page = fetch_page or self._fetch_with_scrapling

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            page = self.fetch_page(self.base_url)
            records = parse_careers_page(
                page,
                page_url=self.base_url,
                max_jobs=self.max_jobs,
            )
        except ArtificialyParseError:
            raise
        except Exception as exc:
            raise DirectCompanyRequestError("Artificialy vacancy request failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_artificialy_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Artificialy vacancies from the complete "
                "server-rendered careers catalog"
            ),
        )

    def _fetch_with_scrapling(self, url: str) -> ScraplingResponse:
        response = Fetcher.get(
            url,
            headers=ARTIFICIALY_HEADERS,
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        status = int(getattr(response, "status", 0) or 0)
        if status >= 400:
            raise ArtificialyParseError(f"Artificialy returned HTTP {status}")
        return response


def parse_careers_page(
    page: ScraplingResponse,
    *,
    page_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if canonical_careers_url(page_url) is None:
        raise ArtificialyParseError("Artificialy careers URL is outside the expected scope")
    if selector_text(page, "main h1") != "Shape the Future of AI with Us":
        raise ArtificialyParseError("Artificialy careers page has an unexpected identity")
    sections = page.css("#section-careers_openings")
    if len(sections) != 1 or selector_text(sections[0], "h2") != "Open Positions":
        raise ArtificialyParseError("Artificialy careers page is missing its official catalog")

    grids = sections[0].css(".grid")
    if not grids:
        section_text = selector_text(sections[0]) or ""
        if re.search(
            r"\b(?:no|without)\s+(?:current\s+)?open\s+positions\b",
            section_text,
            re.IGNORECASE,
        ):
            return []
        raise ArtificialyParseError("Artificialy careers page has no recognizable jobs state")
    if len(grids) != 1:
        raise ArtificialyParseError("Artificialy careers page contains multiple vacancy catalogs")

    cards = grids[0].css(":scope > div")
    if len(cards) > max_jobs:
        raise ArtificialyParseError(
            f"Artificialy exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        metadata = card.css(":scope > div.flex.items-center.justify-between")
        links = card.css(':scope a[href*="linkedin.com/jobs/view/"]')
        title = selector_text(card, ":scope > h3")
        description = selector_text(card, ":scope > p")
        location = selector_text(metadata[0], ":scope > div span") if len(metadata) == 1 else None
        employment_type = (
            selector_text(metadata[0], ":scope > span") if len(metadata) == 1 else None
        )
        linkedin_url = canonical_linkedin_job_url(
            links[0].css("::attr(href)").get() if len(links) == 1 else None
        )
        job_id = extract_linkedin_job_id(linkedin_url)
        link_text = selector_text(links[0]) if len(links) == 1 else None
        link_target = links[0].css("::attr(target)").get() if len(links) == 1 else None
        link_rel = optional_text(links[0].css("::attr(rel)").get()) if len(links) == 1 else None
        if (
            not title
            or not description
            or not location
            or location.casefold() not in ARTIFICIALY_ALLOWED_LOCATIONS
            or not employment_type
            or not linkedin_url
            or not job_id
            or comparable_text(link_text) != "view on linkedin"
            or link_target != "_blank"
            or set((link_rel or "").split()) != {"noopener", "noreferrer"}
        ):
            raise ArtificialyParseError(
                "Artificialy careers page contains an incomplete or out-of-scope vacancy"
            )
        if job_id in seen_ids:
            raise ArtificialyParseError("Artificialy careers page contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": ARTIFICIALY_COMPANY,
                "location": location,
                "employment_type": employment_type,
                "description": description,
                "url": linkedin_url,
                "apply_url": linkedin_url,
            }
        )
    return records


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="artificialy",
        title=optional_text(record.get("title")),
        company=ARTIFICIALY_COMPANY,
        location=optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(record.get("apply_url")) or public_url,
        employment_type=optional_text(record.get("employment_type")),
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
        or parts.hostname != "www.artificialy.com"
        or parts.path.rstrip("/") != "/career"
        or parts.query
        or parts.fragment
    ):
        return None
    return ARTIFICIALY_JOBS_BASE_URL


def canonical_linkedin_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.linkedin.com"
        or not LINKEDIN_JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.linkedin.com", parts.path.rstrip("/"), "", ""))


def extract_linkedin_job_id(value: Any) -> str | None:
    url = canonical_linkedin_job_url(value)
    match = LINKEDIN_JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def deduplicate_artificialy_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
