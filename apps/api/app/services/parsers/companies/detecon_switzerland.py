from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

DETECON_SWITZERLAND_JOBS_URL = "https://www.detecon.com/de/jobs"
DETECON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/de/job/([a-z0-9][a-z0-9-]*)/?$")
SWISS_LOCATION_LABELS = {"Zürich", "Zurich", "Zuerich"}
APPLY_EMAIL = "recruiting-alpine@detecon.com"


class DeteconSwitzerlandParseError(DirectCompanyRequestError):
    pass


class DeteconSwitzerlandJobsParser:
    """Collect Detecon vacancies from the dedicated Switzerland catalog tab."""

    parser_id = "detecon_switzerland"

    def __init__(
        self,
        *,
        base_url: str = DETECON_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=DETECON_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_base_url=self.base_url,
                )
                self.enrich_records(client, records)
        except DeteconSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Detecon vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Detecon vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_detecon_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Detecon Switzerland vacancies from the "
                "complete official catalog"
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
                    expected_url=record["url"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, DeteconSwitzerlandParseError, ValueError) as exc:
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
            title=optional_text(record.get("title")) or optional_text(detail.get("title")),
            company="Detecon (Schweiz) AG",
            location="Zürich, Switzerland",
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            employment_type=None,
            seniority=None,
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("teaser"))
            ),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_base_url: str,
) -> list[dict[str, Any]]:
    if canonical_url(page_url) != canonical_url(expected_base_url):
        raise DeteconSwitzerlandParseError(
            "Detecon catalog redirected to an unexpected page"
        )

    page = Selector(page_html)
    tabs = page.css("#schweiz-tab")
    if len(tabs) != 1:
        raise DeteconSwitzerlandParseError(
            "Detecon listing is missing its Switzerland catalog tab"
        )
    tab = tabs[0]
    catalog = tab.css(".eael-post-list-posts-wrap")
    if len(catalog) != 1:
        raise DeteconSwitzerlandParseError(
            "Detecon listing is missing its Switzerland vacancy catalog"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in catalog.css(".eael-post-list-post"):
        title = selector_text(card, "h2.eael-post-list-title a")
        href = optional_text(card.css("h2.eael-post-list-title a::attr(href)").get())
        detail_url = canonical_url(urljoin(page_url, href)) if href else None
        job_id = extract_job_id(detail_url, expected_base_url=expected_base_url)
        location_label = normalize_location_label(
            selector_text(card, ".meta-cats-wrap a")
        )
        teaser = selector_text(card, ".eael-post-list-content p")
        if not title or not detail_url or not job_id or not teaser or not location_label:
            raise DeteconSwitzerlandParseError(
                "Detecon Switzerland listing contains an incomplete vacancy"
            )
        if location_label not in SWISS_LOCATION_LABELS:
            raise DeteconSwitzerlandParseError(
                "Detecon Switzerland listing contains an unexpected location"
            )
        if job_id in seen_ids:
            raise DeteconSwitzerlandParseError(
                "Detecon Switzerland listing contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": "Zürich, Switzerland",
                "location_label": location_label,
                "url": detail_url,
                "teaser": teaser,
                "listing_page_url": canonical_url(page_url),
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
) -> dict[str, Any]:
    page = Selector(page_html)
    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    public_url = canonical_url(urljoin(page_url, canonical)) if canonical else None
    if canonical_url(page_url) != canonical_url(expected_url) or public_url != canonical_url(
        expected_url
    ):
        raise DeteconSwitzerlandParseError(
            "Detecon detail page returned a different vacancy"
        )

    post_type = optional_text(page.css('meta[name="stc:post-type"]::attr(content)').get())
    roots = page.css('[data-elementor-post-type="job"]')
    title = selector_text(
        page,
        '[data-widget_type="theme-post-title.default"] h1.elementor-heading-title',
    )
    if (
        post_type != "job"
        or len(roots) != 1
        or not title
        or comparable_text(title) != comparable_text(expected_title)
    ):
        raise DeteconSwitzerlandParseError(
            "Detecon detail page returned a different vacancy title"
        )

    description = extract_description(roots[0])
    if not description:
        raise DeteconSwitzerlandParseError(
            "Detecon detail page is missing its job description"
        )
    apply_urls = {
        normalized
        for value in roots[0].css('a[href^="mailto:"]::attr(href)').getall()
        if (normalized := normalize_apply_url(str(value)))
    }
    if apply_urls != {f"mailto:{APPLY_EMAIL}"}:
        raise DeteconSwitzerlandParseError(
            "Detecon detail page is missing its official Switzerland apply email"
        )

    return {
        "id": extract_job_id(public_url, expected_base_url=expected_url),
        "title": title,
        "public_url": public_url,
        "apply_url": apply_urls.pop(),
        "description": description,
    }


def extract_description(root: Any) -> str | None:
    parts: list[str] = []
    for node in root.css("h2, h3, p, .elementor-icon-list-text"):
        text = optional_text(" ".join(str(value) for value in node.css("::text").getall()))
        if not text:
            continue
        if "elementor-icon-list-text" in str(node.attrib.get("class", "")):
            text = f"- {text}"
        if text not in parts:
            parts.append(text)
    return optional_multiline_text("\n".join(parts))


def extract_job_id(value: str | None, *, expected_base_url: str) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    expected = urlsplit(expected_base_url)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if parts.scheme != "https" or parts.netloc != expected.netloc or not match:
        return None
    return match.group(1)


def normalize_location_label(value: str | None) -> str | None:
    return optional_text(re.sub(r"^[^\wÄÖÜäöü]+", "", value or ""))


def normalize_apply_url(value: str | None) -> str | None:
    text = optional_text(value)
    if not text or not text.casefold().startswith("mailto:"):
        return None
    email = text.removeprefix("mailto:").split("?", 1)[0].strip().casefold()
    return f"mailto:{email}" if email == APPLY_EMAIL else None


def deduplicate_detecon_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def comparable_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").replace("\u00ad", "").casefold())


def selector_text(node: Any, selector: str) -> str | None:
    return optional_text(" ".join(str(value) for value in node.css(f"{selector} ::text").getall()))


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
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or None
