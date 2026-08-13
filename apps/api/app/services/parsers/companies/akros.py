from __future__ import annotations

import html
import re
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AKROS_JOBS_URL = "https://www.akros.ch/jobs/"
AKROS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "AKROS AG"
EXPECTED_SITE_NAME = "AKROS"
LOCATION_COLUMNS = {
    1: ("biel", "Biel/Bienne, Switzerland"),
    2: ("zurich", "Zürich, Switzerland"),
    3: ("luzern", "Luzern, Switzerland"),
    4: ("bern", "Bern, Switzerland"),
}
EXPECTED_HEADERS = {"Biel (BI)", "Zürich (ZH)", "Luzern (LU)", "Bern (BE)"}
JOB_PATH_PATTERN = re.compile(r"^/jobs/([a-z0-9]+(?:-[a-z0-9]+)*)/(biel|zurich|luzern|bern)/?$")
PDF_PATH_PATTERN = re.compile(r"^/jobs/pdf/(\d+)/(biel|zurich|luzern|bern)/?$")
WORKLOAD_PATTERN = re.compile(r"(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%$")


class AkrosParseError(DirectCompanyRequestError):
    pass


class AkrosJobsParser:
    """Collect AKROS AG's complete location-specific Swiss vacancy catalog."""

    parser_id = "akros"

    def __init__(
        self,
        *,
        base_url: str = AKROS_JOBS_URL,
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
                headers={**AKROS_HEADERS, "Referer": self.base_url},
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
        except AkrosParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("AKROS vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("AKROS vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_akros_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} AKROS Switzerland vacancies from the official catalog",
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
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
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                    expected_location_slug=record["location_slug"],
                )
            except (httpx.HTTPError, AkrosParseError, ValueError) as exc:
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
            company=EXPECTED_COMPANY,
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=None,
            employment_type=(
                optional_text(detail.get("employment_type"))
                or optional_text(record.get("employment_type"))
            ),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise AkrosParseError("AKROS listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    tables = page.css("#jobsall > table")
    rows = tables[0].css(":scope > tr") if len(tables) == 1 else []
    headers = {
        value
        for node in page.css("#jobsall > table > tr > th")
        if (value := html_to_text(node.get()))
    }
    if not rows or headers != EXPECTED_HEADERS:
        raise AkrosParseError("AKROS listing is missing its complete vacancy table")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    category: str | None = None
    for row in rows[1:]:
        classes = set(str(row.attrib.get("class", "")).split())
        if "subHeadTableRow" in classes:
            category = selector_text(row, ".jobsTableSubtitle")
            if not category:
                raise AkrosParseError("AKROS listing contains an invalid category")
            continue

        cells = row.css(":scope > td")
        title = optional_text(row.css(":scope > td:first-child::text").get())
        if len(cells) != 5 or not title or not category:
            raise AkrosParseError("AKROS listing contains an incomplete vacancy row")

        desktop_urls: set[str] = set()
        for column, (expected_location_slug, location) in LOCATION_COLUMNS.items():
            links = cells[column].css("a::attr(href)")
            if not links:
                continue
            if len(links) != 1:
                raise AkrosParseError("AKROS listing contains an ambiguous location link")
            detail_url = urljoin(page_url, optional_text(links[0].get()) or "")
            parsed = parse_job_url(detail_url, expected_host=expected_host)
            if not parsed or parsed[1] != expected_location_slug:
                raise AkrosParseError("AKROS listing contains an invalid location link")
            role_slug, location_slug = parsed
            job_id = f"{role_slug}-{location_slug}"
            if job_id in seen_ids:
                raise AkrosParseError("AKROS listing contains duplicate vacancy IDs")
            seen_ids.add(job_id)
            desktop_urls.add(detail_url)
            records.append(
                {
                    "id": job_id,
                    "role_slug": role_slug,
                    "location_slug": location_slug,
                    "title": title,
                    "company": EXPECTED_COMPANY,
                    "category": category,
                    "location": location,
                    "employment_type": workload_from_title(title),
                    "url": detail_url,
                    "listing_page_url": page_url,
                }
            )

        all_urls = [
            urljoin(page_url, value)
            for raw in row.css("a::attr(href)").getall()
            if (value := optional_text(raw))
        ]
        counts = Counter(all_urls)
        if not desktop_urls or set(counts) != desktop_urls or set(counts.values()) != {2}:
            raise AkrosParseError("AKROS listing mobile and desktop vacancy links disagree")

    if not records:
        raise AkrosParseError("AKROS listing contains no vacancies")
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_location_slug: str,
) -> dict[str, Any]:
    parsed_url = parse_job_url(page_url, expected_host=urlsplit(expected_url).netloc.casefold())
    if (
        not same_url(page_url, expected_url)
        or not parsed_url
        or f"{parsed_url[0]}-{parsed_url[1]}" != expected_job_id
        or parsed_url[1] != expected_location_slug
    ):
        raise AkrosParseError("AKROS detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    title_value = selector_text(page, "title")
    page_title = title_value.removesuffix(" | AKROS").strip() if title_value else None
    location = location_for_slug(expected_location_slug)
    description = parse_description(page)

    pdf_urls = {
        urljoin(page_url, value)
        for raw in page.css('a[href*="/jobs/pdf/"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    pdf_url = pdf_urls.pop() if len(pdf_urls) == 1 else None
    posting_id = parse_pdf_url(
        pdf_url,
        expected_host=urlsplit(expected_url).netloc.casefold(),
        expected_location_slug=expected_location_slug,
    )
    forms = page.css("form#job-form")
    form_action = (
        urljoin(page_url, optional_text(forms[0].attrib.get("action")) or "")
        if len(forms) == 1
        else None
    )
    apply_buttons = page.css("#applyforjob")
    if (
        not page_title
        or not location
        or not description
        or not posting_id
        or not form_action
        or not same_url(form_action, expected_url)
        or len(apply_buttons) != 1
        or selector_text(page, "#applyforjob") != "Jetzt bewerben!"
    ):
        raise AkrosParseError("AKROS detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "posting_id": posting_id,
        "title": expected_title,
        "page_title": page_title,
        "company": EXPECTED_COMPANY,
        "location": location,
        "employment_type": workload_from_title(expected_title),
        "apply_url": expected_url,
        "pdf_url": pdf_url,
        "description": description,
    }


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    languages = {
        value for raw in page.css("html::attr(lang)").getall() if (value := optional_text(raw))
    }
    site_names = {
        value
        for raw in page.css('meta[property="og:site_name"]::attr(content)').getall()
        if (value := optional_text(raw))
    }
    canonicals = {
        urljoin(expected_url, value)
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    if (
        languages != {"de"}
        or site_names != {EXPECTED_SITE_NAME}
        or len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
    ):
        raise AkrosParseError("AKROS page has an unexpected identity")


def parse_description(page: Selector) -> str | None:
    intros = page.css(".pageWrapper .jobintro")
    heroes = page.css(".pageWrapper .jobHeroInner")
    if len(intros) != 1 or len(heroes) != 1:
        return None

    parts = [value for node in intros if (value := html_to_text(node.get()))]
    headings: set[str] = set()
    for node in heroes[0].css(":scope > *"):
        raw_html = str(node.get())
        text = html_to_text(raw_html)
        if raw_html.lstrip().lower().startswith("<h3"):
            if text == "Kontakt":
                break
            if text:
                headings.add(text)
        if text:
            parts.append(text)
    required_headings = {"Deine Aufgaben", "Unser Versprechen"}
    profile_headings = {"Deine Skills", "Dein Profil"}
    allowed_headings = required_headings | profile_headings
    if (
        not required_headings.issubset(headings)
        or not headings.intersection(profile_headings)
        or not headings.issubset(allowed_headings)
    ):
        return None
    return optional_multiline_text("\n\n".join(parts))


def parse_job_url(value: Any, *, expected_host: str) -> tuple[str, str] | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1), match.group(2)


def parse_pdf_url(
    value: Any,
    *,
    expected_host: str,
    expected_location_slug: str,
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = PDF_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or not match
        or match.group(2) != expected_location_slug
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def location_for_slug(value: str) -> str | None:
    return next(
        (location for slug, location in LOCATION_COLUMNS.values() if slug == value),
        None,
    )


def workload_from_title(value: Any) -> str | None:
    text = optional_text(value)
    match = WORKLOAD_PATTERN.search(text) if text else None
    if not match:
        return None
    lower, upper = (int(item) for item in match.groups())
    return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None


def same_url(value: str, expected: str) -> bool:
    actual = urlsplit(value)
    target = urlsplit(expected)
    return (
        actual.scheme.casefold() == target.scheme.casefold()
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and parse_qs(actual.query, keep_blank_values=True)
        == parse_qs(target.query, keep_blank_values=True)
        and actual.fragment == target.fragment
    )


def deduplicate_akros_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str) -> str | None:
    nodes = selector.css(css)
    return html_to_text(nodes[0].get()) if len(nodes) == 1 else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|strong)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = optional_multiline_text(html.unescape(text).replace("\xa0", " "))
    return re.sub(r"(?m)(^- .*)\n\n(?=- )", r"\1\n", normalized) if normalized else None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
