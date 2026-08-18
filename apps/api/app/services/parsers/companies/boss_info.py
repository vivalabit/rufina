from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BOSS_INFO_JOBS_URL = "https://www.bossinfo.com/karriere/jobs/"
BOSS_INFO_COMPANY = "Boss Info AG"
BOSS_INFO_SITE_NAME = "Boss Info"
BOSS_INFO_PAGE_TITLE = "Offene Stellen bei Boss Info - Jobs im Bereich ICT und IT"
BOSS_INFO_CATALOG_HEADING = "Offene Stellen"
BOSS_INFO_APPLICATION_HOST = "forms.swisshrmonline.ch"
BOSS_INFO_APPLICATION_PATH = "/221313970241850"
BOSS_INFO_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/jobs/([a-z0-9]+(?:-[a-z0-9]+)*)/$")
APPLICATION_ID_PATTERN = re.compile(r"^JOB-\d+$", re.IGNORECASE)
WORKLOAD_PATTERN = re.compile(
    r"^(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?\s*%$",
    re.IGNORECASE,
)
YOAST_SCHEMA_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*'
    r'class=["\'][^"\']*yoast-schema-graph[^"\']*["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class BossInfoParseError(DirectCompanyRequestError):
    pass


class BossInfoJobsParser:
    """Collect the complete server-rendered Boss Info vacancy catalog."""

    parser_id = "boss_info"

    def __init__(
        self,
        *,
        base_url: str = BOSS_INFO_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=BOSS_INFO_HEADERS,
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
        except BossInfoParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Boss Info vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Boss Info vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_boss_info_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Boss Info vacancies from the complete "
                "official careers catalog"
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
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_title=record["title"],
                )
                return record, detail
            except (httpx.HTTPError, BossInfoParseError, ValueError) as exc:
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
    max_jobs: int,
) -> list[dict[str, Any]]:
    expected = canonical_listing_url(expected_url)
    if not expected or canonical_listing_url(page_url) != expected:
        raise BossInfoParseError("Boss Info careers page returned an unexpected page")

    page = Selector(page_html)
    canonical_urls = {
        canonical_listing_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    schema = parse_yoast_schema(page_html)
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de-DE"
        or selector_text(page, "title") != BOSS_INFO_PAGE_TITLE
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != BOSS_INFO_SITE_NAME
        or canonical_urls != {expected}
        or not validate_page_schema(
            schema,
            expected_url=expected,
            expected_name=BOSS_INFO_PAGE_TITLE,
        )
    ):
        raise BossInfoParseError("Boss Info careers page has an unexpected identity")

    sections = page.css("main #jobs")
    if len(sections) != 1:
        raise BossInfoParseError("Boss Info careers page is missing its vacancy section")
    section = sections[0]
    catalogs = section.css(".wpb_jobs_column .jobs")
    if selector_text(section, "h2") != BOSS_INFO_CATALOG_HEADING or len(catalogs) != 1:
        raise BossInfoParseError("Boss Info careers page is missing its vacancy catalog")

    cards = catalogs[0].css(":scope > .job")
    if len(cards) > max_jobs:
        raise BossInfoParseError(
            f"Boss Info exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )
    if not cards and not re.search(
        r"keine\s+(?:aktuellen\s+)?(?:offenen\s+)?stellen",
        selector_text(section) or "",
        re.IGNORECASE,
    ):
        raise BossInfoParseError("Boss Info careers page has no recognizable vacancy state")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, card in enumerate(cards):
        titles = card.css(":scope > h3")
        links = card.css(":scope > a.full[href]")
        if len(titles) != 1 or len(links) != 1:
            raise BossInfoParseError("Boss Info catalog contains an incomplete vacancy card")
        title = selector_text(titles[0])
        link_title = selector_text(links[0])
        url = canonical_job_url(
            urljoin(page_url, optional_text(links[0].css("::attr(href)").get()) or "")
        )
        job_id = job_id_from_url(url)
        if (
            not title
            or not link_title
            or title.casefold() not in link_title.casefold()
            or not url
            or not job_id
        ):
            raise BossInfoParseError("Boss Info catalog contains an invalid vacancy card")
        if job_id in seen_ids or url in seen_urls:
            raise BossInfoParseError("Boss Info catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(url)
        categories = sorted(
            value for value in element_classes(card) if value not in {"job", "vc_col-sm-12"}
        )
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": BOSS_INFO_COMPANY,
                "location": "Switzerland",
                "url": url,
                "catalog_index": index,
                "categories": categories,
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
    expected = canonical_job_url(expected_url)
    if not expected or canonical_job_url(page_url) != expected:
        raise BossInfoParseError("Boss Info detail page returned a different vacancy")

    page = Selector(page_html)
    canonical_urls = {
        canonical_job_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    schema = parse_yoast_schema(page_html)
    body_classes = element_classes(page.css("body")[0]) if page.css("body") else set()
    title = selector_text(page, "header h1")
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de-DE"
        or "single-jobs" not in body_classes
        or title != expected_title
        or canonical_urls != {expected}
        or not validate_page_schema(
            schema,
            expected_url=expected,
            expected_name=None,
        )
    ):
        raise BossInfoParseError("Boss Info detail page has an unexpected identity")

    summaries = page.css("main #job-kurzbeschreibung")
    role_rows = page.css("main #job-kurzbeschreibung + .vc_row")
    if len(summaries) != 1 or len(role_rows) != 1:
        raise BossInfoParseError("Boss Info detail page is missing its vacancy content")
    metadata = parse_detail_metadata(summaries[0])
    description = extract_role_description(role_rows[0])

    apply_urls = {
        value
        for raw in page.css('main a[href*="forms.swisshrmonline.ch"]::attr(href)').getall()
        if (value := canonical_application_url(raw))
    }
    if len(apply_urls) != 1:
        raise BossInfoParseError("Boss Info detail page is missing its direct SwissHRM application")
    apply_url = apply_urls.pop()
    application_id = application_id_from_url(apply_url)
    if not application_id:
        raise BossInfoParseError("Boss Info detail page has an invalid application identifier")

    published_at = schema_date_published(schema)
    return {
        "id": job_id_from_url(expected),
        "application_id": application_id,
        "title": title,
        "company": BOSS_INFO_COMPANY,
        "location": normalize_location(metadata["Hauptarbeitsort"]),
        "employment_type": normalize_workload(metadata["Pensum"]),
        "starts_at": metadata["Arbeitsbeginn"],
        "experience": metadata["Berufserfahrung"],
        "posted_at": published_at,
        "description": description,
        "url": expected,
        "apply_url": apply_url,
    }


def parse_detail_metadata(section: Any) -> dict[str, str]:
    expected_labels = {
        "Pensum",
        "Arbeitsbeginn",
        "Berufserfahrung",
        "Hauptarbeitsort",
    }
    metadata: dict[str, str] = {}
    for paragraph in section.css("p"):
        labels = paragraph.css("strong")
        label = (selector_text(labels[0]) or "").rstrip(": ") if len(labels) == 1 else None
        text = selector_text(paragraph)
        if not label or label not in expected_labels or not text:
            continue
        value = optional_text(re.sub(rf"^{re.escape(label)}\s*:\s*", "", text))
        if not value or label in metadata:
            raise BossInfoParseError("Boss Info detail page has invalid vacancy metadata")
        metadata[label] = value
    if set(metadata) != expected_labels or not normalize_workload(metadata["Pensum"]):
        raise BossInfoParseError("Boss Info detail page has incomplete vacancy metadata")
    return metadata


def extract_role_description(row: Any) -> str:
    blocks: list[str] = []
    headings: set[str] = set()
    for column in row.css(".wpb_content_element.wpb_text_column"):
        heading_values = [value for node in column.css("h4") if (value := selector_text(node))]
        if heading_values:
            if len(heading_values) != 1:
                continue
            heading = heading_values[0]
            if heading not in {"Das sind deine Aufgaben", "Das bringst du mit"}:
                continue
            headings.add(heading)
            items = [value for node in column.css("li") if (value := selector_text(node))]
            if items:
                blocks.append(f"{heading}\n" + "\n".join(f"- {item}" for item in items))
        elif not blocks:
            paragraphs = [
                value
                for node in column.css(":scope > .wpb_wrapper > p")
                if (value := selector_text(node))
            ]
            if paragraphs:
                blocks.append("\n".join(paragraphs))
    description = "\n\n".join(blocks)
    if (
        headings != {"Das sind deine Aufgaben", "Das bringst du mit"}
        or len(row.css("li")) < 5
        or len(description) < 300
    ):
        raise BossInfoParseError("Boss Info detail page has an incomplete vacancy description")
    return description


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="boss_info",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=BOSS_INFO_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=optional_text(detail.get("employment_type")),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def validate_page_schema(
    schema: list[dict[str, Any]],
    *,
    expected_url: str,
    expected_name: str | None,
) -> bool:
    organizations = [item for item in schema if item.get("@type") == "Organization"]
    webpages = [item for item in schema if item.get("@type") == "WebPage"]
    if len(organizations) != 1 or len(webpages) != 1:
        return False
    organization = organizations[0]
    webpage = webpages[0]
    name = optional_text(webpage.get("name"))
    return bool(
        optional_text(organization.get("name")) == BOSS_INFO_SITE_NAME
        and canonical_content_url(webpage.get("url")) == canonical_content_url(expected_url)
        and (expected_name is None or name == expected_name)
    )


def parse_yoast_schema(page_html: str) -> list[dict[str, Any]]:
    matches = YOAST_SCHEMA_PATTERN.findall(page_html)
    if len(matches) != 1:
        return []
    try:
        payload = json.loads(matches[0])
    except (json.JSONDecodeError, TypeError):
        return []
    graph = payload.get("@graph") if isinstance(payload, dict) else None
    return [item for item in graph if isinstance(item, dict)] if isinstance(graph, list) else []


def schema_date_published(schema: list[dict[str, Any]]) -> str | None:
    values = {
        value
        for item in schema
        if item.get("@type") == "WebPage"
        and (value := optional_text(item.get("datePublished")))
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^\s]+", value)
    }
    return next(iter(values)) if len(values) == 1 else None


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    match = WORKLOAD_PATTERN.fullmatch(text or "")
    if not match:
        return None
    lower = int(match.group(1))
    upper = int(match.group(2) or match.group(1))
    if not 1 <= lower <= upper <= 100:
        return None
    return f"{lower}–{upper}%" if lower != upper else f"{lower}%"


def normalize_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text or "boss info" not in text.casefold():
        raise BossInfoParseError("Boss Info detail page has an invalid Swiss location")
    return f"{text}, Switzerland"


def canonical_listing_url(value: Any) -> str | None:
    url = canonical_content_url(value)
    return url if url and urlsplit(url).path == "/karriere/jobs/" else None


def canonical_job_url(value: Any) -> str | None:
    url = canonical_content_url(value)
    if not url:
        return None
    parts = urlsplit(url)
    return url if JOB_PATH_PATTERN.fullmatch(parts.path) else None


def canonical_content_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = f"{parts.path.rstrip('/')}/" if parts.path != "/" else "/"
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.bossinfo.com"
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.bossinfo.com", path, "", ""))


def job_id_from_url(value: Any) -> str | None:
    url = canonical_job_url(value)
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def canonical_application_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    job_ids = query.get("xvnu", [])
    names = [value for value in query.get("xvna", []) if optional_text(value)]
    sources = query.get("xsou", [])
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != BOSS_INFO_APPLICATION_HOST
        or parts.path != BOSS_INFO_APPLICATION_PATH
        or parts.fragment
        or len(job_ids) != 1
        or not APPLICATION_ID_PATTERN.fullmatch(job_ids[0])
        or len(names) != 1
        or sources != ["%mediaName%"]
    ):
        return None
    return text


def application_id_from_url(value: Any) -> str | None:
    url = canonical_application_url(value)
    values = parse_qs(urlsplit(url).query, keep_blank_values=True).get("xvnu", []) if url else []
    return values[0].upper() if len(values) == 1 else None


def deduplicate_boss_info_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        detail = job.raw.get("detail")
        application_id = (
            optional_text(detail.get("application_id")) if isinstance(detail, dict) else None
        )
        key = application_id or optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def element_classes(node: Any) -> set[str]:
    return set((optional_text(node.css("::attr(class)").get()) or "").split())


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
