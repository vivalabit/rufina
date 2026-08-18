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

ARCON_JOBS_URL = "https://www.arcon.ch/ict-und-abacus-jobs/#OffeneStellen"
ARCON_COMPANY = "Arcon Informatik AG"
ARCON_LOCATION = "Steinhausen, Switzerland"
ARCON_PAGE_TITLE = "ICT und Abacus Jobs | Offene Stellen"
ARCON_CATALOG_HEADING = "Unsere offenen ICT und Abacus Jobs"
ARCON_TENANT_ID = "77844ac7-0da4-4fcd-9fdc-5fdd7119d642"
INITIATIVE_TITLE = "Initiativbewerbung"
INITIATIVE_DESCRIPTION = (
    "Keine passende Stelle gefunden? Dann schick uns deine Initiativbewerbung und "
    "zeig uns deine Skills!"
)
ARCON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
JOB_PATH_PATTERN = re.compile(r"^/([a-z0-9]+(?:-[a-z0-9]+)*)/$", re.IGNORECASE)
APPLICATION_PATH_PATTERN = re.compile(
    rf"^/application-process/({UUID_PATTERN})/({UUID_PATTERN})$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%(?!\d)")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RANK_MATH_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*class=["\'][^"\']*rank-math-schema[^"\']*["\'][^>]*>'
    r"(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class ArconParseError(DirectCompanyRequestError):
    pass


class ArconJobsParser:
    """Collect Arcon's complete visible WordPress vacancy catalog."""

    parser_id = "arcon"

    def __init__(
        self,
        *,
        base_url: str = ARCON_JOBS_URL,
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
                headers=ARCON_HEADERS,
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
        except ArconParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Arcon vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Arcon vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_arcon_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Arcon vacancies from the complete visible official catalog"
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
            if record.get("kind") == "initiative":
                try:
                    response = client.get(record["url"], headers={"Referer": self.base_url})
                    response.raise_for_status()
                    application = parse_application_html(
                        response.text,
                        page_url=str(response.url),
                        expected_url=record["url"],
                        expected_title=record["base_title"],
                    )
                    return record, {
                        **application,
                        "description": record["listing_description"],
                        "url": record["url"],
                        "apply_url": record["url"],
                    }
                except (httpx.HTTPError, ArconParseError, ValueError) as exc:
                    record["detail_error"] = str(exc)
                    return record, None

            try:
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
            except (httpx.HTTPError, ArconParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

            try:
                application_response = client.get(
                    detail["apply_url"],
                    headers={"Referer": record["url"]},
                )
                application_response.raise_for_status()
                application = parse_application_html(
                    application_response.text,
                    page_url=str(application_response.url),
                    expected_url=detail["apply_url"],
                    expected_title=record["base_title"],
                )
                detail["application"] = application
                detail["posted_at"] = application["posted_at"]
                detail["location"] = application["location"]
            except (httpx.HTTPError, ArconParseError, ValueError) as exc:
                record["application_error"] = str(exc)
            return record, detail

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
        raise ArconParseError("Arcon careers page returned an unexpected page")

    page = Selector(page_html)
    canonical_urls = {
        canonical_listing_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    schema = parse_rank_math_schema(page_html)
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de"
        or selector_text(page, "title") != ARCON_PAGE_TITLE
        or optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        != ARCON_PAGE_TITLE
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != ARCON_COMPANY
        or canonical_urls != {expected}
        or not validate_rank_math_identity(
            schema,
            expected_url=expected,
            expected_title=ARCON_PAGE_TITLE,
        )
    ):
        raise ArconParseError("Arcon careers page has an unexpected identity")

    sections = page.css("#OffeneStellen")
    if len(sections) != 1:
        raise ArconParseError("Arcon careers page is missing its vacancy section")
    section = sections[0]
    headings = {value for node in section.css("h2") if (value := selector_text(node))}
    visible_lists = [
        node
        for node in section.css(".elementor-widget-icon-list")
        if not any(
            class_name.startswith("elementor-hidden-") for class_name in element_classes(node)
        )
    ]
    if ARCON_CATALOG_HEADING not in headings or len(visible_lists) != 1:
        raise ArconParseError("Arcon careers page is missing its visible vacancy catalog")

    cards = visible_lists[0].css("li.elementor-icon-list-item")
    if len(cards) > max_jobs:
        raise ArconParseError(
            f"Arcon exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )
    marker_values = {value for node in section.css("h3") if (value := selector_text(node))}
    if INITIATIVE_DESCRIPTION not in marker_values:
        raise ArconParseError("Arcon careers page is missing its initiative marker")

    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    initiative_count = 0
    for index, card in enumerate(cards):
        links = card.css(":scope > a[href]")
        title_nodes = card.css(".elementor-icon-list-text")
        if len(links) != 1 or len(title_nodes) != 1:
            raise ArconParseError("Arcon catalog contains an incomplete vacancy card")
        link = links[0]
        raw_url = urljoin(page_url, optional_text(link.css("::attr(href)").get()) or "")
        raw_title = selector_text(title_nodes[0])
        title = normalize_title(raw_title)
        if not title or optional_text(link.css("::attr(target)").get()) != "_blank":
            raise ArconParseError("Arcon catalog contains an invalid vacancy card")

        application_url = canonical_application_url(raw_url)
        if application_url:
            if title != INITIATIVE_TITLE:
                raise ArconParseError("Arcon catalog has an unexpected direct application card")
            initiative_count += 1
            job_id = application_id_from_url(application_url)
            record = {
                "id": job_id,
                "base_title": INITIATIVE_TITLE,
                "title": INITIATIVE_TITLE,
                "company": ARCON_COMPANY,
                "location": ARCON_LOCATION,
                "employment_type": None,
                "url": application_url,
                "kind": "initiative",
                "listing_description": INITIATIVE_DESCRIPTION,
                "catalog_index": index,
            }
        else:
            detail_url = canonical_job_url(raw_url)
            job_id = job_slug_from_url(detail_url)
            base_title = title_without_workload(title)
            employment_type = normalize_workload(title)
            if not detail_url or not job_id or not base_title or not employment_type:
                raise ArconParseError("Arcon catalog contains an invalid vacancy link")
            record = {
                "id": job_id,
                "base_title": base_title,
                "title": title,
                "company": ARCON_COMPANY,
                "location": ARCON_LOCATION,
                "employment_type": employment_type,
                "url": detail_url,
                "kind": "vacancy",
                "catalog_index": index,
            }
        if not job_id or record["url"] in seen_urls or job_id in seen_ids:
            raise ArconParseError("Arcon catalog contains duplicate vacancies")
        seen_urls.add(record["url"])
        seen_ids.add(job_id)
        records.append(record)

    if initiative_count != 1:
        raise ArconParseError("Arcon catalog has an invalid initiative application count")

    footer_text = comparable_text(selector_text(page, "footer"))
    if not all(
        value in footer_text
        for value in (
            "arcon informatik ag",
            "hinterbergstrasse 24",
            "6312 steinhausen",
        )
    ):
        raise ArconParseError("Arcon careers page is missing its Swiss company address")
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"))
    expected_title = optional_text(expected_record.get("title"))
    expected_base_title = optional_text(expected_record.get("base_title"))
    if (
        not expected_url
        or not expected_title
        or not expected_base_title
        or canonical_job_url(page_url) != expected_url
    ):
        raise ArconParseError("Arcon detail page returned a different vacancy")

    page = Selector(page_html)
    schema = parse_rank_math_schema(page_html)
    document_title = selector_text(page, "title")
    canonical_urls = {
        canonical_job_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de"
        or not document_title
        or optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        != document_title
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != ARCON_COMPANY
        or canonical_urls != {expected_url}
        or not validate_rank_math_identity(
            schema,
            expected_url=expected_url,
            expected_title=document_title,
        )
    ):
        raise ArconParseError("Arcon detail page has an unexpected identity")

    roots = page.css('div[data-elementor-type="wp-page"][data-elementor-post-type="page"]')
    root = roots[0] if len(roots) == 1 else None
    root_id = optional_text(root.css("::attr(data-elementor-id)").get()) if root else None
    body_classes = element_classes(page.css("body")[0]) if page.css("body") else set()
    titles = root.css("h1") if root else []
    visible_title = selector_text(titles[0]) if len(titles) == 1 else None
    normalized_title_values = {
        normalize_title(selector_text(node))
        for node in (root.css("p") if root else [])
        if normalize_title(selector_text(node))
    }
    if (
        not root
        or not root_id
        or f"page-id-{root_id}" not in body_classes
        or visible_title != expected_base_title
        or expected_title not in normalized_title_values
    ):
        raise ArconParseError("Arcon detail page does not match its visible vacancy")

    job_sections = root.css("#neuerJob")
    if len(job_sections) != 1:
        raise ArconParseError("Arcon detail page is missing its vacancy description")
    description, description_headings, bullet_count = extract_detail_description(job_sections[0])
    if (
        not description
        or len(description) < 500
        or bullet_count < 5
        or not {"Über die Stelle", "Deine Aufgaben", "Was du mitbringst"}.issubset(
            description_headings
        )
    ):
        raise ArconParseError("Arcon detail page has an incomplete vacancy description")

    apply_urls = {
        value
        for raw in root.css('a[href*="application-process"]::attr(href)').getall()
        if (value := canonical_application_url(raw))
    }
    if len(apply_urls) != 1:
        raise ArconParseError("Arcon detail page is missing its direct application link")

    page_published_at = rank_math_date_published(schema)
    return {
        "id": expected_record["id"],
        "title": expected_title,
        "base_title": expected_base_title,
        "company": ARCON_COMPANY,
        "location": expected_record.get("location"),
        "employment_type": expected_record.get("employment_type"),
        "description": description,
        "page_published_at": page_published_at,
        "url": expected_url,
        "apply_url": apply_urls.pop(),
    }


def parse_application_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
) -> dict[str, Any]:
    expected = canonical_application_url(expected_url)
    expected_id = application_id_from_url(expected)
    if not expected or not expected_id or canonical_application_url(page_url) != expected:
        raise ArconParseError("Arcon application page returned a different vacancy")

    page = Selector(page_html)
    postings = extract_job_postings(page_html)
    if (
        selector_text(page, "title") != "Bewerbungsprozess - Portal"
        or optional_text(page.css('meta[property="page-type"]::attr(content)').get())
        != "application-process"
        or len(postings) != 1
    ):
        raise ArconParseError("Arcon application page has an unexpected identity")
    posting = postings[0]
    identifier = posting.get("identifier")
    organization = posting.get("hiringOrganization")
    job_location = posting.get("jobLocation")
    address = job_location.get("address") if isinstance(job_location, dict) else None
    title = normalize_application_title(posting.get("title"))
    posted_at = optional_text(posting.get("datePosted"))
    identifier_name = (
        optional_text(identifier.get("name")) if isinstance(identifier, dict) else None
    )
    identifier_value = (
        optional_text(identifier.get("value")) if isinstance(identifier, dict) else None
    )
    company = optional_text(organization.get("name")) if isinstance(organization, dict) else None
    if (
        title != normalize_application_title(expected_title)
        or company != ARCON_COMPANY
        or identifier_name != ARCON_COMPANY
        or identifier_value != expected_id
        or not posted_at
        or not DATE_PATTERN.fullmatch(posted_at)
        or not isinstance(address, dict)
        or optional_text(address.get("addressCountry")) != "CH"
        or optional_text(address.get("addressLocality")) != "Steinhausen"
        or optional_text(address.get("addressRegion")) != "ZG"
        or optional_text(address.get("postalCode")) != "6312"
        or optional_text(address.get("streetAddress")) != "Hinterbergstrasse"
    ):
        raise ArconParseError("Arcon application page has incomplete JobPosting data")
    return {
        "application_id": expected_id,
        "title": expected_title,
        "company": ARCON_COMPANY,
        "location": ARCON_LOCATION,
        "posted_at": posted_at,
        "job_posting": posting,
    }


def parse_rank_math_schema(page_html: str) -> list[dict[str, Any]]:
    matches = RANK_MATH_SCRIPT_PATTERN.findall(page_html)
    if len(matches) != 1:
        return []
    try:
        payload = json.loads(matches[0])
    except (json.JSONDecodeError, TypeError):
        return []
    graph = payload.get("@graph") if isinstance(payload, dict) else None
    return [item for item in graph if isinstance(item, dict)] if isinstance(graph, list) else []


def validate_rank_math_identity(
    schema: list[dict[str, Any]],
    *,
    expected_url: str,
    expected_title: str,
) -> bool:
    organizations = [item for item in schema if item.get("@type") == "Organization"]
    webpages = [item for item in schema if item.get("@type") == "WebPage"]
    articles = [item for item in schema if item.get("@type") == "Article"]
    if len(organizations) != 1 or len(webpages) != 1 or len(articles) != 1:
        return False
    organization = organizations[0]
    webpage = webpages[0]
    article = articles[0]
    schema_url = canonical_arcon_content_url(webpage.get("url"))
    expected_canonical = canonical_arcon_content_url(expected_url)
    return bool(
        optional_text(organization.get("name")) == ARCON_COMPANY
        and schema_url == expected_canonical
        and optional_text(webpage.get("name")) == expected_title
        and optional_text(article.get("name")) == expected_title
        and rank_math_date_published(schema)
    )


def rank_math_date_published(schema: list[dict[str, Any]]) -> str | None:
    webpages = [item for item in schema if item.get("@type") == "WebPage"]
    if len(webpages) != 1:
        return None
    value = optional_text(webpages[0].get("datePublished"))
    date_value = value.split("T", 1)[0] if value and "T" in value else None
    return date_value if date_value and DATE_PATTERN.fullmatch(date_value) else None


def extract_job_postings(page_html: str) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for raw in LD_JSON_SCRIPT_PATTERN.findall(page_html):
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        postings.extend(
            value
            for value in values
            if isinstance(value, dict) and value.get("@type") == "JobPosting"
        )
    return postings


def extract_detail_description(section: Any) -> tuple[str | None, set[str], int]:
    headings = {value for node in section.css("h2,h3") if (value := selector_text(node))}
    bullet_values = [
        value for node in section.css(".elementor-icon-list-text") if (value := selector_text(node))
    ]
    parts: list[str] = []
    for node in section.css("h2,h3,p,.elementor-icon-list-text"):
        value = selector_text(node)
        if value and (not parts or value != parts[-1]):
            parts.append(f"- {value}" if value in bullet_values else value)
    return optional_multiline_text("\n".join(parts)), headings, len(bullet_values)


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    description = optional_multiline_text(detail.get("description")) or optional_multiline_text(
        record.get("listing_description")
    )
    return ParsedJob(
        source="arcon",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=ARCON_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority=None,
        description=description,
        raw=dict(record),
    )


def canonical_listing_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.arcon.ch"
        or parts.path.rstrip("/") != "/ict-und-abacus-jobs"
        or parts.query
        or (parts.fragment and parts.fragment != "OffeneStellen")
    ):
        return None
    return "https://www.arcon.ch/ict-und-abacus-jobs/"


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = f"{parts.path.rstrip('/')}/"
    match = JOB_PATH_PATTERN.fullmatch(path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.arcon.ch"
        or not match
        or match.group(1) == "ict-und-abacus-jobs"
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.arcon.ch", path, "", ""))


def canonical_arcon_content_url(value: Any) -> str | None:
    return canonical_listing_url(value) or canonical_job_url(value)


def canonical_application_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLICATION_PATH_PATTERN.fullmatch(parts.path.rstrip("/"))
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "app.jobportal.abaservices.ch"
        or not match
        or match.group(1).casefold() != ARCON_TENANT_ID
        or query not in ({}, {"jp": ["ABACUS"]})
        or parts.fragment
    ):
        return None
    path = parts.path.rstrip("/")
    return urlunsplit(("https", "app.jobportal.abaservices.ch", path, "", ""))


def application_id_from_url(value: Any) -> str | None:
    url = canonical_application_url(value)
    if not url:
        return None
    match = APPLICATION_PATH_PATTERN.fullmatch(urlsplit(url).path)
    return match.group(2).casefold() if match else None


def job_slug_from_url(value: Any) -> str | None:
    url = canonical_job_url(value)
    if not url:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path)
    return match.group(1).casefold() if match else None


def normalize_title(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = re.sub(r"\s+%", "%", text)
    return WORKLOAD_PATTERN.sub(lambda match: f"{match.group(1)}–{match.group(2)}%", text)


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    match = WORKLOAD_PATTERN.search(text) if text else None
    return f"{match.group(1)}–{match.group(2)}%" if match else None


def title_without_workload(value: Any) -> str | None:
    text = normalize_title(value)
    if not text:
        return None
    workload = normalize_workload(text)
    if not workload:
        return None
    return optional_text(re.sub(rf"\s+{re.escape(workload)}\s+\(m/w/d\)\s*$", "", text))


def normalize_application_title(value: Any) -> str | None:
    text = optional_text(value)
    return re.sub(r"/in$", "", text) if text else None


def deduplicate_arcon_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = canonical_job_url(job.url) or canonical_application_url(job.url) or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def element_classes(node: Any) -> set[str]:
    return set((optional_text(node.css("::attr(class)").get()) or "").split())


def selector_text(node: Any, selector: str | None = None) -> str | None:
    target = node.css(selector) if selector else node
    return optional_text(" ".join(target.css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u200b", "").replace("\r\n", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"[\s\u200b]+", " ", html.unescape(value)).strip() or None
