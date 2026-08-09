from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

S_PEERS_JOBS_BASE_URL = "https://s-peers.com/karriere-jobs/stellenausschreibungen/"
S_PEERS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
POST_ID_PATTERN = re.compile(r"(?:^|\s)post-(\d+)(?:\s|$)")
JOB_PATH_PATTERN = re.compile(r"/job/[^/?#]+/?$")
APPLICATION_COPY_PREFIX = "bitte achte darauf"


class SPeersParseError(DirectCompanyRequestError):
    pass


class SPeersJobsParser:
    """Collect the complete catalog published on the s-peers careers page."""

    parser_id = "s_peers"

    def __init__(
        self,
        *,
        base_url: str = S_PEERS_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=S_PEERS_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(response.text, page_url=str(response.url))
                self.enrich_records(client, records)
        except SPeersParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("s-peers vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("s-peers vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_s_peers_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} s-peers vacancies from the full catalog page"),
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
                    expected_job_id=record["id"],
                    expected_title=optional_text(record.get("title")),
                )
            except (httpx.HTTPError, SPeersParseError, ValueError) as exc:
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
        public_url = optional_text(detail.get("public_url")) or optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="s-peers AG",
            location="Switzerland",
            url=public_url,
            apply_url=public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=extract_employment_type(
                optional_text(detail.get("title")) or optional_text(record.get("title"))
            ),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("teaser"))
            ),
            raw=dict(record),
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    catalog = page.css(".elementor-widget-speers-post-list .content-grid-container")
    if not catalog.get():
        raise SPeersParseError("s-peers listing page is missing its vacancy catalog")

    cards = catalog.css("div.entry-post.job.type-job.status-publish")
    if not cards:
        raise SPeersParseError("s-peers vacancy catalog does not contain any vacancies")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        job_id = extract_post_id(card.attrib.get("id"))
        path = optional_text(card.css(".post-title a::attr(href)").get())
        detail_url = urljoin(page_url, path) if path else None
        title = optional_text(" ".join(card.css(".post-title h3::text").getall()))
        teaser_html = card.css(".post-grid-excerpt").get()
        teaser = html_to_text(teaser_html)
        if not job_id or not title or not detail_url or not is_job_url(detail_url):
            raise SPeersParseError("s-peers listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise SPeersParseError("s-peers listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "teaser": teaser,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str | None,
    expected_title: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    wrapper = page.css(
        'div[data-elementor-type="single-post"].elementor-location-single.job'
        ".type-job.status-publish"
    )
    if not wrapper.get():
        raise SPeersParseError("s-peers detail page is missing its vacancy content")

    job_id = extract_post_id(wrapper.first.attrib.get("class"))
    title = optional_text(" ".join(wrapper.css("h1.elementor-heading-title::text").getall()))
    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    public_url = urljoin(page_url, canonical) if canonical else page_url
    if not job_id or not title or not is_job_url(public_url):
        raise SPeersParseError("s-peers detail page contains an incomplete vacancy")
    if expected_job_id and job_id != expected_job_id:
        raise SPeersParseError("s-peers detail page returned a different vacancy")
    if expected_title and title.casefold() != expected_title.casefold():
        raise SPeersParseError("s-peers detail page returned a different vacancy title")

    post_content = wrapper.css('div[data-elementor-post-type="job"]')
    description_parts: list[str] = []
    for node in post_content.css(".elementor-widget-text-editor > .elementor-widget-container"):
        node_html = node.get()
        text = html_to_text(node_html)
        if not text:
            continue
        if text.casefold().startswith(APPLICATION_COPY_PREFIX):
            break
        description_parts.append(text)
    description_parts = list(dict.fromkeys(description_parts))
    if not description_parts:
        raise SPeersParseError("s-peers detail page is missing its vacancy description")

    return {
        "id": job_id,
        "title": title,
        "public_url": public_url,
        "posted_at": extract_date_published(page),
        "description": "\n\n".join(description_parts),
    }


def extract_date_published(page: Selector) -> str | None:
    for raw_json in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in walk_json(payload):
            if item.get("@type") == "WebPage":
                return optional_text(item.get("datePublished"))
    return None


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_post_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = POST_ID_PATTERN.search(f" {text} ")
    return match.group(1) if match else None


def is_job_url(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and JOB_PATH_PATTERN.fullmatch(urlsplit(text).path))


def extract_employment_type(title: str | None) -> str | None:
    if not title:
        return None
    match = re.search(r"\b(\d{1,3})\s*%?\s*[-–]\s*(\d{1,3})\s*%", title)
    if match:
        return f"{match.group(1)}%-{match.group(2)}%"
    match = re.search(r"(?:^|\s)(\d{1,3})\s*%", title)
    return f"{match.group(1)}%" if match else None


def deduplicate_s_peers_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
