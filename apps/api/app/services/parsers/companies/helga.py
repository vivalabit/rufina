from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

HELGA_JOBS_BASE_URL = "https://www.helga.ch/jobs"
HELGA_COMPANY = "Helga Digitalagentur GmbH"
HELGA_ORGANIZATION = "Helga Digitalagentur"
HELGA_APPLY_EMAIL = "jobs@helga.ch"
HELGA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/jobs/([a-z0-9][a-z0-9-]*)/?$")
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")


class HelgaParseError(DirectCompanyRequestError):
    pass


class HelgaJobsParser:
    """Collect Helga's complete visible careers catalog and vacancy details."""

    parser_id = "helga"

    def __init__(
        self,
        *,
        base_url: str = HELGA_JOBS_BASE_URL,
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
                headers=HELGA_HEADERS,
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
        except HelgaParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Helga vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Helga vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_helga_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Helga vacancies from the complete visible "
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
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_title=record["title"],
                    expected_location=record["location"],
                    expected_workload=record["workload"],
                )
            except (httpx.HTTPError, HelgaParseError, ValueError) as exc:
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
            company=HELGA_COMPANY,
            location=(
                optional_text(detail.get("location"))
                or format_location(record.get("location"))
            ),
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url"))
                or optional_text(record.get("apply_url"))
                or public_url
            ),
            employment_type=(
                optional_text(detail.get("workload"))
                or optional_text(record.get("workload"))
            ),
            description=(
                optional_multiline_text(detail.get("description"))
                or optional_multiline_text(record.get("listing_description"))
            ),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if canonical_careers_url(page_url) != canonical_careers_url(expected_url):
        raise HelgaParseError("Helga careers catalog returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url, listing=True)
    articles = page.css("main article")
    if len(articles) != 1:
        raise HelgaParseError("Helga careers page is missing its main content")
    article = articles[0]
    markers = {
        selector_text(node)
        for node in article.css("helga-section-title")
        if selector_text(node)
    }
    if "Offene Stellen" not in markers:
        raise HelgaParseError("Helga careers page is missing its vacancy catalog")

    apply_urls = {
        normalized
        for raw in article.css('a[href^="mailto:"]::attr(href)').getall()
        if (normalized := normalize_apply_url(raw))
    }
    if apply_urls != {f"mailto:{HELGA_APPLY_EMAIL}"}:
        raise HelgaParseError(
            "Helga careers page is missing its official application email"
        )

    links = [
        link
        for link in article.css('a.c-button[href^="/jobs/"]')
        if canonical_job_url(urljoin(page_url, link.attrib.get("href", "")))
    ]
    if len(links) > max_jobs:
        raise HelgaParseError(
            f"Helga exposes {len(links)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, link in enumerate(links):
        detail_url = canonical_job_url(urljoin(page_url, link.attrib.get("href", "")))
        job_id = extract_job_id(detail_url)
        link_title = selector_text(link)
        editors = link.xpath(
            "ancestor::div[contains(concat(' ', normalize-space(@class), ' '), "
            "' c-call-to-action ')][1]/preceding-sibling::div["
            "contains(concat(' ', normalize-space(@class), ' '), ' c-editor ')][1]"
        )
        if (
            not detail_url
            or not job_id
            or link_title != "Zur Stellenausschreibung"
            or len(editors) != 1
        ):
            raise HelgaParseError("Helga careers catalog contains an invalid vacancy")

        card = editors[0]
        title = selector_text(card, "h2")
        summary = selector_text(card, "p")
        card_text = selector_text(card)
        location = extract_labeled_value(
            card_text,
            label="Standort",
            next_labels=("Stellenprozent", "Lohnspanne", "Wann"),
        )
        workload = extract_workload(card_text)
        salary = extract_labeled_value(
            card_text,
            label="Lohnspanne",
            next_labels=("Wann",),
            required=False,
        )
        starts_at = extract_labeled_value(
            card_text,
            label="Wann",
            next_labels=(),
        )
        if (
            not title
            or not summary
            or len(summary) < 40
            or not location
            or "Bern" not in location
            or not workload
            or not starts_at
        ):
            raise HelgaParseError(
                "Helga careers catalog contains an incomplete vacancy card"
            )
        if job_id in seen_ids or detail_url in seen_urls:
            raise HelgaParseError("Helga careers catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(detail_url)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": HELGA_COMPANY,
                "location": location,
                "workload": workload,
                "salary": salary,
                "starts_at": starts_at,
                "listing_description": summary,
                "url": detail_url,
                "apply_url": f"mailto:{HELGA_APPLY_EMAIL}",
                "catalog_index": index,
                "listing_page_url": canonical_careers_url(page_url),
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
    expected_location: str,
    expected_workload: str,
) -> dict[str, Any]:
    if canonical_job_url(page_url) != canonical_job_url(expected_url):
        raise HelgaParseError("Helga detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url, listing=False)
    articles = page.css("main article")
    if len(articles) != 1:
        raise HelgaParseError("Helga detail page is missing its vacancy content")
    article = articles[0]

    title = selector_text(article, "h1.c-page-intro__title")
    lead = selector_text(article, ".c-page-intro__lead")
    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    locality = optional_text(page.css('meta[property="og:locality"]::attr(content)').get())
    country = optional_text(page.css('meta[property="og:country_name"]::attr(content)').get())
    description = article_text(article)
    markers = {
        selector_text(node)
        for node in article.css("helga-section-title")
        if selector_text(node)
    }
    apply_urls = {
        normalized
        for raw in article.css('a[href^="mailto:"]::attr(href)').getall()
        if (normalized := normalize_apply_url(raw))
    }
    if (
        title != optional_text(expected_title)
        or og_title != f"Werde {optional_text(expected_title)} bei Helga"
        or locality != "Bern"
        or country != "Schweiz"
        or not lead
        or optional_text(expected_workload) not in lead
        or "Bern" not in lead
        or "Bern" not in optional_text(expected_location)
        or not description
        or len(description) < 300
        or not {"Deine Wirkung", "Dein Profil", "Bewerbung"}.issubset(markers)
        or apply_urls != {f"mailto:{HELGA_APPLY_EMAIL}"}
    ):
        raise HelgaParseError(
            "Helga detail page contains an incomplete or inconsistent vacancy"
        )

    return {
        "id": extract_job_id(expected_url),
        "title": title,
        "company": HELGA_COMPANY,
        "location": format_location(expected_location),
        "workload": optional_text(expected_workload),
        "url": canonical_job_url(expected_url),
        "apply_url": f"mailto:{HELGA_APPLY_EMAIL}",
        "description": description,
        "lead": lead,
        "metadata_title": og_title,
    }


def validate_page_identity(
    page: Selector,
    *,
    expected_url: str,
    listing: bool,
) -> None:
    expected = canonical_careers_url(expected_url) if listing else canonical_job_url(expected_url)
    canonical = canonical_url(page.css('link[rel="canonical"]::attr(href)').get())
    og_url = canonical_url(page.css('meta[property="og:url"]::attr(content)').get())
    language = optional_text(page.css("html::attr(lang)").get())
    site_name = optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
    rights = optional_text(page.css('meta[name="rights"]::attr(content)').get())
    organization = extract_organization(page)
    if (
        not expected
        or canonical != expected
        or og_url != expected
        or language != "de"
        or site_name != HELGA_ORGANIZATION
        or not rights
        or HELGA_COMPANY not in rights
        or organization != (HELGA_ORGANIZATION, "CH")
    ):
        raise HelgaParseError("Helga page has an unexpected identity")
    if listing:
        title = selector_text(page, "title")
        og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        if title != "Werde Teil von Helga!" or og_title != title:
            raise HelgaParseError("Helga careers page has an unexpected identity")


def extract_organization(page: Selector) -> tuple[str, str] | None:
    organizations: list[tuple[str, str]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        values = payload.get("@graph", []) if isinstance(payload, dict) else []
        if isinstance(payload, dict) and payload.get("@type") == "Organization":
            values = [payload]
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict) or value.get("@type") != "Organization":
                continue
            address = value.get("address")
            country = address.get("addressCountry") if isinstance(address, dict) else None
            name = optional_text(value.get("name"))
            country_text = optional_text(country)
            if name and country_text:
                organizations.append((name, country_text))
    return organizations[0] if len(organizations) == 1 else None


def extract_labeled_value(
    value: Any,
    *,
    label: str,
    next_labels: tuple[str, ...],
    required: bool = True,
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    stop = "|".join(re.escape(item) for item in next_labels)
    suffix = rf"(?=\s+(?:{stop})\s*:|$)" if stop else r"$"
    match = re.search(rf"\b{re.escape(label)}\s*:\s*(.+?){suffix}", text)
    result = optional_text(match.group(1)) if match else None
    return result if result or not required else None


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := WORKLOAD_PATTERN.search(text)):
        return None
    return optional_text(re.sub(r"\s*[–-]\s*", "–", match.group(0)))


def format_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    return text if text.casefold().endswith("switzerland") else f"{text}, Switzerland"


def normalize_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not text.casefold().startswith("mailto:"):
        return None
    email = text.split(":", 1)[1].split("?", 1)[0].strip().casefold()
    return f"mailto:{email}" if email == HELGA_APPLY_EMAIL else None


def canonical_job_url(value: Any) -> str | None:
    url = canonical_url(value)
    if not url:
        return None
    parts = urlsplit(url)
    if parts.netloc != "www.helga.ch" or JOB_PATH_PATTERN.fullmatch(parts.path) is None:
        return None
    return url


def canonical_careers_url(value: Any) -> str | None:
    url = canonical_url(value)
    if not url:
        return None
    parts = urlsplit(url)
    return url if parts.netloc == "www.helga.ch" and parts.path == "/jobs" else None


def canonical_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment:
        return None
    return urlunsplit(("https", parts.netloc.casefold(), parts.path.rstrip("/") or "/", "", ""))


def extract_job_id(value: Any) -> str | None:
    url = canonical_job_url(value)
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def article_text(article: Any) -> str | None:
    values = [optional_text(raw) for raw in article.css("::text").getall()]
    return optional_multiline_text("\n".join(value for value in values if value))


def selector_text(node: Any, selector: str | None = None) -> str | None:
    selected = node.css(selector) if selector else [node]
    if not selected:
        return None
    return optional_text(" ".join(str(value) for value in selected[0].css("::text").getall()))


def deduplicate_helga_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line)) or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip() or None
