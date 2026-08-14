from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

PANTER_CAREERS_URL = "https://www.panter.ch/en/about-us/career/"
PANTER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Panter AG"
EXPECTED_LOCATION = "8005 Zürich, Switzerland"
JOB_PATH_PATTERN = re.compile(r"^/ueber-uns/karriere/([a-z0-9]+(?:-[a-z0-9]+)*)/$")


class PanterParseError(DirectCompanyRequestError):
    pass


class PanterJobsParser:
    """Collect Panter AG's complete server-rendered Zurich vacancy catalog."""

    parser_id = "panter"

    def __init__(
        self,
        *,
        base_url: str = PANTER_CAREERS_URL,
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
                headers={**PANTER_HEADERS, "Referer": self.base_url},
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
        except PanterParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Panter vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Panter vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_panter_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} Panter Switzerland vacancies from the official catalog",
        )

    def enrich_records(self, client: httpx.Client, records: list[dict[str, Any]]) -> None:
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
                    expected_workload=record["workload"],
                )
            except (httpx.HTTPError, PanterParseError, ValueError) as exc:
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
        raise PanterParseError("Panter career page returned unexpected content")
    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    organizations = [
        item for item in extract_json_objects(page) if item.get("@type") == "Organization"
    ]
    organization_valid = any(
        optional_text(item.get("legalName")) == EXPECTED_COMPANY
        and same_url(item.get("url"), "https://www.panter.ch/en/")
        and optional_text(item.get("email")) == "hello@panter.ch"
        and optional_text(item.get("telephone")) == "+41 44 500 29 04"
        for item in organizations
    )
    logos = unique_attribute_values(page, "#logo img", "src")
    contact_links = unique_attribute_values(page, 'a[href^="mailto:"]', "href")
    if (
        canonicals != {expected_url}
        or og_urls != {expected_url}
        or languages != {"en-US"}
        or not organization_valid
        or "https://www.panter.ch/wp-content/uploads/panter-logo-black.svg" not in logos
        or "mailto:jobs@panter.ch" not in contact_links
    ):
        raise PanterParseError("Panter career page has an unexpected identity")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css(".nectar-hor-list-item"):
        title = selector_text(card, "h2")
        facts = [
            value
            for node in card.css(":scope > .nectar-list-item:not([data-icon])")
            if (value := html_to_text(node.get())) and value != "Learn more"
        ]
        url = optional_text(card.css(":scope > a.full-link::attr(href)").get())
        job_id = extract_job_id(url)
        if not title or facts != ["Zürich / Remote, 60-100%"] or not job_id or job_id in seen_ids:
            raise PanterParseError("Panter catalog contains an incomplete vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": EXPECTED_LOCATION,
                "workplace_type": "Remote / Hybrid",
                "workload": "60–100%",
                "url": url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
    expected_workload: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise PanterParseError("Panter detail page returned a different vacancy")
    page = Selector(page_html)
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    schemas = [item for item in extract_json_objects(page) if item.get("@type") == "WebPage"]
    schema = schemas[0] if len(schemas) == 1 else {}
    title = optional_text(" ".join(page.css("h1::text").getall()))
    hero_facts = next(
        (
            value
            for node in page.css("p")
            if (value := html_to_text(node.get())) and "Pensum:" in value and "Standort:" in value
        ),
        None,
    )
    descriptions = [
        text
        for section_id in ("panter", "job", "profil")
        for node in page.css(f"#{section_id}")[:1]
        if (text := html_to_text(node.get()))
    ]
    description = optional_multiline_text("\n\n".join(descriptions))
    forms = page.css('form.wpforms-form[data-formid="12482"]')
    expected_path = urlsplit(expected_url).path
    form_action_valid = False
    form_title_valid = False
    if len(forms) == 1:
        action = urlsplit(optional_text(forms[0].attrib.get("action")) or "")
        form_action_valid = action.path == expected_path and parse_qs(action.query) == {
            "wpforms_form_id": ["12482"]
        }
        form_titles = {
            value
            for raw in forms[0]
            .css('input[type="hidden"][name="wpforms[fields][26]"]::attr(value)')
            .getall()
            if (value := optional_text(raw))
        }
        form_title_valid = len(form_titles) == 1 and next(iter(form_titles)).startswith(
            expected_title
        )
    posted_at = normalize_iso_date(schema.get("datePublished"))
    if (
        og_urls != {expected_url}
        or optional_text(schema.get("url")) != expected_url
        or optional_text(schema.get("inLanguage")) != "de"
        or not posted_at
        or not title
        or not title.startswith(expected_title)
        or not hero_facts
        or f"Pensum: {expected_workload.replace('–', '-')}" not in hero_facts
        or "Standort: Zürich, hybrid" not in hero_facts
        or not description
        or not form_action_valid
        or not form_title_valid
    ):
        raise PanterParseError("Panter detail page contains an incomplete vacancy")
    return {
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "apply_url": f"{expected_url}#bewerben",
        "posted_at": posted_at,
        "employment_type": f"Part-time / Full-time · {expected_workload}",
        "description": description,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="panter",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=optional_text(record.get("url")),
        apply_url=optional_text(detail.get("apply_url")) or optional_text(record.get("url")),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or f"Part-time / Full-time · {record.get('workload')}"
        ),
        seniority="Senior" if optional_text(record.get("title")).startswith("Senior") else None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.panter.ch"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


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


def deduplicate_panter_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
