from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from curl_cffi.requests.exceptions import RequestException
from scrapling import Selector
from scrapling.fetchers import Fetcher

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SHARP_SWITZERLAND_JOBS_URL = "https://www.sharp.ch/de/jobs-bei-sharp"
SHARP_COMPANY = "Sharp Electronics (Schweiz) AG"
SHARP_APPLY_EMAIL = "hr.sez@sharp.eu"
SHARP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/de/([a-z0-9][a-z0-9-]*)/?$")
WORKLOAD_PATTERN = re.compile(r"^100\s*%$")


class SharpSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SharpSwitzerlandJobsParser:
    """Collect Sharp's complete server-rendered Swiss vacancy catalog."""

    parser_id = "sharp_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SHARP_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            if self.transport is None:
                page_html, page_url = self.fetch_live_page(self.base_url)
                records = parse_listing_html(
                    page_html,
                    page_url=page_url,
                    expected_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_live_records(records)
            else:
                with httpx.Client(
                    headers=SHARP_HEADERS,
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                    transport=self.transport,
                ) as client:
                    response = client.get(self.base_url)
                    response.raise_for_status()
                    records = parse_listing_html(
                        response.text,
                        page_url=str(response.url),
                        expected_url=self.base_url,
                        max_jobs=self.max_jobs,
                    )
                    self.enrich_records(client, records)
        except SharpSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Sharp Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Sharp Switzerland vacancy parsing failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Sharp Switzerland vacancy request failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_sharp_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Sharp Switzerland vacancies from the "
                "complete official careers catalog"
            ),
        )

    def fetch_live_page(self, url: str) -> tuple[str, str]:
        response = Fetcher.get(
            url,
            headers={**SHARP_HEADERS, "Referer": self.base_url},
            impersonate="chrome",
            timeout=self.timeout_seconds,
        )
        status = int(getattr(response, "status", 0) or 0)
        if status >= 400:
            raise SharpSwitzerlandParseError(f"Sharp returned HTTP {status}")
        body = getattr(response, "body", b"")
        page_html = body.decode("utf-8") if isinstance(body, bytes) else str(body)
        page_url = str(getattr(response, "url", url) or url)
        if not page_html.strip():
            raise SharpSwitzerlandParseError("Sharp returned an empty page")
        return page_html, page_url

    def enrich_live_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                page_html, page_url = self.fetch_live_page(record["url"])
                return record, parse_detail_html(
                    page_html,
                    page_url=page_url,
                    expected_url=record["url"],
                    expected_title=record["title"],
                )
            except (
                RequestException,
                SharpSwitzerlandParseError,
                OSError,
                TypeError,
                ValueError,
            ) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

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
            except (httpx.HTTPError, SharpSwitzerlandParseError, ValueError) as exc:
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
            company=SHARP_COMPANY,
            location=optional_text(detail.get("location")) or "Switzerland",
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url"))
                or optional_text(record.get("apply_url"))
                or public_url
            ),
            employment_type=optional_text(detail.get("workload")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if canonical_url(page_url) != canonical_url(expected_url):
        raise SharpSwitzerlandParseError("Sharp careers catalog returned an unexpected page")

    page = Selector(page_html)
    canonical = canonical_url(optional_text(page.css('link[rel="canonical"]::attr(href)').get()))
    language = optional_text(page.css("html::attr(lang)").get())
    page_title = selector_text(page, "main h1.h2")
    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    if (
        canonical != canonical_url(expected_url)
        or language != "de-ch"
        or page_title != "Jobs bei Sharp"
        or og_title != "Jobs bei Sharp"
    ):
        raise SharpSwitzerlandParseError("Sharp careers page has an unexpected identity")

    catalogs = [
        node
        for node in page.css("main .shp-full-width-text")
        if selector_text(node, "h3") == "Karriere bei Sharp"
    ]
    if len(catalogs) != 1:
        raise SharpSwitzerlandParseError("Sharp careers page is missing its vacancy catalog")
    bodies = catalogs[0].css(":scope .shp-content-wysiwyg")
    if len(bodies) != 1:
        raise SharpSwitzerlandParseError("Sharp careers page has an invalid vacancy catalog")
    body = bodies[0]
    apply_urls = {
        normalized
        for raw in body.css('a[href^="mailto:"]::attr(href)').getall()
        if (normalized := normalize_apply_url(raw))
    }
    if apply_urls != {f"mailto:{SHARP_APPLY_EMAIL}"}:
        raise SharpSwitzerlandParseError(
            "Sharp careers page is missing its official application email"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for link in body.css('a[href]:not([href^="mailto:"])'):
        href = optional_text(link.css("::attr(href)").get())
        detail_url = canonical_job_url(urljoin(page_url, href or ""))
        job_id = extract_job_id(detail_url)
        title = selector_text(link)
        if not detail_url or not job_id or not title:
            raise SharpSwitzerlandParseError(
                "Sharp careers catalog contains an invalid vacancy link"
            )
        if job_id in seen_ids:
            raise SharpSwitzerlandParseError(
                "Sharp careers catalog contains duplicate vacancy identifiers"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "url": detail_url,
                "listing_page_url": canonical_url(page_url),
                "apply_url": f"mailto:{SHARP_APPLY_EMAIL}",
            }
        )

    if len(records) > max_jobs:
        raise SharpSwitzerlandParseError(
            f"Sharp exposes {len(records)} jobs, above the configured limit of {max_jobs}"
        )
    if not records:
        catalog_text = selector_text(body) or ""
        if not re.search(
            r"(?:keine|keine aktuellen)\s+(?:offenen\s+)?stellen",
            catalog_text,
            re.IGNORECASE,
        ):
            raise SharpSwitzerlandParseError("Sharp careers page has no recognizable vacancy state")
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
) -> dict[str, Any]:
    if canonical_url(page_url) != canonical_url(expected_url):
        raise SharpSwitzerlandParseError("Sharp detail page returned a different vacancy")

    page = Selector(page_html)
    canonical = canonical_url(optional_text(page.css('link[rel="canonical"]::attr(href)').get()))
    og_titles = unique_attribute_values(page, 'meta[property="og:title"]', "content")
    dcterms_titles = unique_attribute_values(page, 'meta[name="dcterms.title"]', "content")
    heroes = page.css("main .shp-hero__content")
    if (
        canonical != canonical_url(expected_url)
        or len(og_titles) != 1
        or og_titles != dcterms_titles
    ):
        raise SharpSwitzerlandParseError("Sharp detail page has invalid vacancy metadata")
    if len(heroes) != 1:
        raise SharpSwitzerlandParseError("Sharp detail page is missing its vacancy header")

    title = selector_text(heroes[0], "h1")
    summary = selector_text(heroes[0], "p")
    if not title or role_signature(title) != role_signature(expected_title):
        raise SharpSwitzerlandParseError("Sharp detail page returned a different vacancy title")
    location, workload, starts_at = parse_summary(summary)
    if not location or not workload or starts_at != "ab sofort":
        raise SharpSwitzerlandParseError("Sharp detail page has invalid vacancy metadata")

    blocks: list[str] = []
    headings: set[str] = set()
    for block in page.css("main .shp-landing-page__content .shp-text-media__text-block"):
        heading = selector_text(block, "h2")
        bodies = block.css(":scope .shp-content-wysiwyg")
        body_text = selector_text(bodies[0]) if len(bodies) == 1 else None
        if not heading or not body_text:
            continue
        headings.add(heading.casefold())
        blocks.append(f"{heading}\n{body_text}")
    required_sections = (
        {"ihre aufgaben", "deine aufgaben"},
        {"ihr profil", "dein profil"},
        {"unser angebot"},
    )
    if not all(headings & alternatives for alternatives in required_sections):
        raise SharpSwitzerlandParseError("Sharp detail page is missing vacancy sections")

    apply_urls = {
        normalized
        for raw in page.css('main article a[href^="mailto:"]::attr(href)').getall()
        if (normalized := normalize_apply_url(raw))
    }
    if apply_urls != {f"mailto:{SHARP_APPLY_EMAIL}"}:
        raise SharpSwitzerlandParseError(
            "Sharp detail page is missing its official application email"
        )

    return {
        "id": extract_job_id(canonical),
        "title": title,
        "company": SHARP_COMPANY,
        "location": f"{location}, Switzerland",
        "workload": workload,
        "starts_at": starts_at,
        "url": canonical,
        "apply_url": apply_urls.pop(),
        "description": "\n\n".join(blocks),
        "metadata_title": next(iter(og_titles)),
    }


def parse_summary(value: Any) -> tuple[str | None, str | None, str | None]:
    text = optional_text(value)
    parts = [optional_text(part) for part in (text or "").split("|")]
    if len(parts) != 3 or any(part is None for part in parts):
        return None, None, None
    location, workload, starts_at = parts
    normalized_workload = re.sub(r"\s*%$", " %", workload or "")
    if not WORKLOAD_PATTERN.fullmatch(workload or ""):
        return None, None, None
    return location, normalized_workload, (starts_at or "").casefold()


def role_signature(value: Any) -> str:
    text = optional_text(value) or ""
    text = re.sub(r"\((?:[mwd]/){2}[mwd]\)", "", text, flags=re.IGNORECASE)
    text = re.split(r"[,|]", text, maxsplit=1)[0]
    text = re.sub(r"\b100\s*%", "", text)
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not text.casefold().startswith("mailto:"):
        return None
    email = text.split(":", 1)[1].split("?", 1)[0].strip().casefold()
    return f"mailto:{email}" if email == SHARP_APPLY_EMAIL else None


def canonical_job_url(value: Any) -> str | None:
    url = canonical_url(value)
    if not url:
        return None
    parts = urlsplit(url)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.sharp.ch"
        or not match
        or match.group(1) == "jobs-bei-sharp"
    ):
        return None
    return url


def extract_job_id(value: Any) -> str | None:
    url = canonical_job_url(value)
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def canonical_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment:
        return None
    return urlunsplit(("https", parts.netloc.casefold(), parts.path.rstrip("/") or "/", "", ""))


def unique_attribute_values(node: Any, selector: str, attribute: str) -> set[str]:
    return {
        value
        for raw in node.css(f"{selector}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


def deduplicate_sharp_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, selector: str | None = None) -> str | None:
    selected = node.css(selector) if selector else [node]
    if not selected:
        return None
    return optional_text(" ".join(str(value) for value in selected[0].css("::text").getall()))


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
