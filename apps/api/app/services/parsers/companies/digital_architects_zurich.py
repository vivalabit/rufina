from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

DIGITAL_ARCHITECTS_ZURICH_CAREERS_URL = "https://digital-architects-zurich.ch/career/"
DIGITAL_ARCHITECTS_ZURICH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Digital Architects Zurich GmbH"
EXPECTED_LOCATION = "Zürich / Basel / Bern, Switzerland"
EXPECTED_LOCATION_LABEL = "Zurich, Basel, Berne / 80-100%"
EXPECTED_LOGO_URL = (
    "https://digital-architects-zurich.ch/wp-content/uploads/2024/05/"
    "logo-DAZ-transparent-blau-weiss1.png"
)
JOB_PATH_PATTERN = re.compile(r"^/(job-[a-z0-9]+(?:-[a-z0-9]+)*)/$")
JOIN_PATH_PATTERN = re.compile(
    r"^/companies/digital-architects-zurich/[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$"
)


class DigitalArchitectsZurichParseError(DirectCompanyRequestError):
    pass


class DigitalArchitectsZurichJobsParser:
    """Collect the complete Digital Architects Zurich vacancy catalog."""

    parser_id = "digital_architects_zurich"

    def __init__(
        self,
        *,
        base_url: str = DIGITAL_ARCHITECTS_ZURICH_CAREERS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **DIGITAL_ARCHITECTS_ZURICH_HEADERS,
                    "Referer": self.base_url,
                },
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
                )
                self.enrich_records(client, records)
        except DigitalArchitectsZurichParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Digital Architects Zurich vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Digital Architects Zurich vacancy parsing failed"
            ) from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_digital_architects_zurich_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Digital Architects Zurich vacancies from the official catalog"
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
                verify_apply_url(client, record, detail)
                return record, detail
            except (
                httpx.HTTPError,
                DigitalArchitectsZurichParseError,
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


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise DigitalArchitectsZurichParseError(
            "Digital Architects Zurich career page returned unexpected content"
        )
    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    schemas = list(extract_json_objects(page))
    organizations = [item for item in schemas if item.get("@type") == "Organization"]
    organization_valid = any(
        optional_text(item.get("name")) == "Digital Architects Zurich"
        and same_url(item.get("url"), "https://digital-architects-zurich.ch/")
        and optional_text((item.get("logo") or {}).get("url"))
        == "https://digital-architects-zurich.ch/wp-content/uploads/2020/11/blue-logo.jpg"
        for item in organizations
        if isinstance(item.get("logo"), dict)
    )
    body_text = html_to_text(page.css("body")[0].get()) if page.css("body") else None
    logos = unique_attribute_values(
        page,
        'img[src*="logo-DAZ-transparent-blau-weiss1.png"]',
        "src",
    )
    heading = selector_text(page, ".et_pb_section_0 h1.et_pb_module_heading")
    if (
        canonicals != {expected_url}
        or og_urls != {expected_url}
        or languages != {"en-US"}
        or not organization_valid
        or EXPECTED_LOGO_URL not in logos
        or heading != "Career"
        or not body_text
        or EXPECTED_COMPANY not in body_text
    ):
        raise DigitalArchitectsZurichParseError(
            "Digital Architects Zurich career page has an unexpected identity"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("div.et_pb_toggle_item"):
        title = selector_text(card, "h5.et_pb_toggle_title")
        links = {
            normalize_detail_url(urljoin(expected_url, raw))
            for raw in card.css(".et_pb_toggle_content a::attr(href)").getall()
            if optional_text(raw)
        }
        links.discard(None)
        detail_url = next(iter(links)) if len(links) == 1 else None
        job_id = extract_job_id(detail_url)
        summary = html_to_text(
            card.css(".et_pb_toggle_content")[0].get() if card.css(".et_pb_toggle_content") else ""
        )
        if (
            not title
            or not job_id
            or job_id in seen_ids
            or not summary
            or "Full Job Description" not in summary
        ):
            raise DigitalArchitectsZurichParseError(
                "Digital Architects Zurich catalog contains an incomplete vacancy"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": EXPECTED_LOCATION,
                "workload": "80–100%",
                "url": detail_url,
                "summary": summary.removesuffix("Full Job Description").strip(),
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
    if not same_url(page_url, expected_url):
        raise DigitalArchitectsZurichParseError(
            "Digital Architects Zurich detail page returned a different vacancy"
        )
    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    schemas = list(extract_json_objects(page))
    web_pages = [item for item in schemas if item.get("@type") == "WebPage"]
    schema = web_pages[0] if len(web_pages) == 1 else {}
    organizations = [item for item in schemas if item.get("@type") == "Organization"]
    title = selector_text(page, ".et_pb_fullwidth_header h1.et_pb_module_header")
    location = selector_text(page, ".et_pb_fullwidth_header_subhead")
    employment_heading = selector_text(page, ".et_pb_section_1 h2")
    description_headings = {
        value for node in page.css(".et_pb_section_1 h3") if (value := html_to_text(node.get()))
    }
    description_parts = [
        value
        for node in page.css(".et_pb_section_1 .et_pb_text_inner")
        if (value := html_to_text(node.get()))
    ]
    description = optional_multiline_text("\n\n".join(description_parts))
    apply_urls = {
        value
        for raw in page.css(
            ".et_pb_fullwidth_header a.et_pb_button_one::attr(href), "
            ".et_pb_section_1 a.et_pb_button::attr(href)"
        ).getall()
        if (value := valid_join_apply_url(raw))
    }
    organization_valid = any(
        optional_text(item.get("name")) == "Digital Architects Zurich"
        and same_url(item.get("url"), "https://digital-architects-zurich.ch/")
        for item in organizations
    )
    posted_at = normalize_iso_date(schema.get("datePublished"))
    if (
        canonicals != {expected_url}
        or og_urls != {expected_url}
        or optional_text(schema.get("url")) != expected_url
        or optional_text(schema.get("inLanguage")) != "en-US"
        or not organization_valid
        or not posted_at
        or title != expected_title
        or location != EXPECTED_LOCATION_LABEL
        or employment_heading != "Fulltime Position"
        or description_headings != {"Job Description", "Your Career", "Your Skills"}
        or len(description_parts) != 4
        or not description
        or len(apply_urls) != 1
    ):
        raise DigitalArchitectsZurichParseError(
            "Digital Architects Zurich detail page contains an incomplete vacancy"
        )
    return {
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "apply_url": next(iter(apply_urls)),
        "posted_at": posted_at,
        "employment_type": "Full-time / Part-time · 80–100%",
        "description": description,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="digital_architects_zurich",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=(optional_text(detail.get("location")) or optional_text(record.get("location"))),
        url=optional_text(record.get("url")),
        apply_url=optional_text(detail.get("apply_url")) or optional_text(record.get("url")),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or f"Full-time / Part-time · {record.get('workload')}"
        ),
        description=(
            optional_multiline_text(detail.get("description"))
            or optional_multiline_text(record.get("summary"))
        ),
        raw=dict(record),
    )


def normalize_detail_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "digital-architects-zurich.ch"
        or parts.query
        or parts.fragment
    ):
        return None
    path = f"{parts.path.rstrip('/')}/"
    normalized = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return normalized if JOB_PATH_PATTERN.fullmatch(path) else None


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1) if match and normalize_detail_url(text) == text else None


def valid_join_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "join.com"
        or not JOIN_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return text


def verify_apply_url(
    client: httpx.Client,
    record: dict[str, Any],
    detail: dict[str, Any],
) -> None:
    apply_url = optional_text(detail.get("apply_url"))
    if not apply_url:
        detail["apply_url"] = record["url"]
        return
    try:
        response = client.head(apply_url, headers={"Referer": record["url"]})
        resolved_url = valid_join_apply_url(str(response.url))
        if response.is_success and resolved_url:
            detail["apply_url"] = resolved_url
            return
        record["apply_error"] = f"JOIN returned HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        record["apply_error"] = str(exc)
    detail["apply_url"] = record["url"]


def extract_json_objects(page: Selector) -> Iterator[dict[str, Any]]:
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            continue
        yield from walk_json(payload)


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and actual.query == target.query
        and not actual.fragment
    )


def deduplicate_digital_architects_zurich_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    nodes = selector.css(css)
    return optional_text(" ".join(nodes[0].css("::text").getall())) if len(nodes) == 1 else None


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f"{css}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
