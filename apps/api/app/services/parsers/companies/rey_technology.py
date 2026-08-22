from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

REY_CAREERS_URL = "https://www.rey-technology.com/en/career/vacancies/"
REY_APPLICATION_URL = (
    "https://www.rey-technology.com/en/career/vacancies/application/"
)
REY_COMPANY = "Rey Technology"
REY_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
EXPECTED_LANGUAGE = "en-CH"
EXPECTED_SITE_NAME = "Rey Technology"
EXPECTED_LISTING_HEADING = "Vacancies"
JOB_PATH_PATTERN = re.compile(
    r"^/en/career/vacancies/position/([a-z0-9][a-z0-9-]*)/?$"
)
WORKLOAD_PATTERN = re.compile(r"^\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%$")


class ReyTechnologyParseError(DirectCompanyRequestError):
    pass


class ReyTechnologyJobsParser:
    """Collect Rey Technology's complete visible TYPO3 vacancy catalog."""

    parser_id = "rey_technology"

    def __init__(
        self,
        *,
        base_url: str = REY_CAREERS_URL,
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
                headers=REY_HEADERS,
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
        except ReyTechnologyParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Rey Technology vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "Rey Technology vacancy parsing failed"
            ) from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_rey_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Rey Technology vacancies from the complete "
                "visible official careers catalog"
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
                    expected_location=record["listing_location"],
                    expected_workload=record["workload"],
                    expected_start=record["start"],
                    expected_job_id=record["id"],
                )
                return record, detail
            except (httpx.HTTPError, ReyTechnologyParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(
            max_workers=min(self.detail_workers, len(records))
        ) as executor:
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
    if canonical_careers_url(page_url) != canonical_careers_url(expected_url):
        raise ReyTechnologyParseError(
            "Rey Technology careers catalog returned an unexpected page"
        )

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    main_contents = page.css("#main")
    lists = page.css("ul.c-jobs-list__items")
    if (
        len(main_contents) != 1
        or len(lists) != 1
        or unique_text_values(page, "h1") != {EXPECTED_LISTING_HEADING}
    ):
        raise ReyTechnologyParseError(
            "Rey Technology careers page is missing its vacancy catalog"
        )

    cards = lists[0].css("li.c-jobs-list__item")
    if len(cards) > max_jobs:
        raise ReyTechnologyParseError(
            f"Rey Technology exposes {len(cards)} jobs, above the configured limit "
            f"of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, card in enumerate(cards):
        title = single_text(card, ".c-jobs-teaser__title h3")
        location = single_text(card, ".c-jobs-teaser__place span")
        workload_text = single_text(
            card,
            ".c-jobs-teaser__workload span",
            allow_empty=True,
        )
        workload = normalize_workload(workload_text)
        start = single_text(card, ".c-jobs-teaser__start span")
        hrefs = card.css("a.u-cover-object::attr(href)").getall()
        detail_url = (
            canonical_job_url(urljoin(page_url, str(hrefs[0])))
            if len(hrefs) == 1
            else None
        )
        job_id = extract_job_id(detail_url)
        if (
            not title
            or not location
            or workload_text is None
            or (workload_text and not workload)
            or not start
            or not detail_url
            or not job_id
        ):
            raise ReyTechnologyParseError(
                "Rey Technology careers catalog contains an incomplete vacancy"
            )
        if job_id in seen_ids or detail_url in seen_urls:
            raise ReyTechnologyParseError(
                "Rey Technology careers catalog contains duplicate vacancies"
            )
        seen_ids.add(job_id)
        seen_urls.add(detail_url)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": REY_COMPANY,
                "location": normalize_location(location),
                "listing_location": location,
                "workload": workload,
                "start": start,
                "url": detail_url,
                "apply_url": REY_APPLICATION_URL,
                "catalog_index": index,
                "listing_page_url": REY_CAREERS_URL,
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
    expected_workload: str | None,
    expected_start: str,
    expected_job_id: str,
) -> dict[str, Any]:
    public_url = canonical_job_url(page_url)
    if (
        public_url != canonical_job_url(expected_url)
        or extract_job_id(public_url) != expected_job_id
    ):
        raise ReyTechnologyParseError(
            "Rey Technology detail page returned a different vacancy"
        )

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    details = page.css("div.c-jobs-detail")
    if len(details) != 1:
        raise ReyTechnologyParseError(
            "Rey Technology detail page has an invalid identity"
        )
    detail = details[0]
    title = single_text(detail, ".c-jobs-detail__title h1")
    location = prefixed_text(
        single_text(detail, ".c-jobs-detail__place span"),
        "Location:",
    )
    workload = normalize_workload(
        prefixed_text(
            single_text(detail, ".c-jobs-detail__workload span", allow_empty=True),
            "Workload:",
            allow_empty=True,
        )
    )
    start = prefixed_text(
        single_text(detail, ".c-jobs-detail__start span"),
        "Start:",
    )
    text_contents = detail.css("div.c-jobs-detail__text")
    description = (
        html_to_text(text_contents[0].get() or "")
        if len(text_contents) == 1
        else None
    )
    apply_urls = {
        normalized
        for raw in detail.css(".c-jobs-detail__cta a[href]::attr(href)").getall()
        if (normalized := canonical_application_url(urljoin(page_url, str(raw))))
    }
    if (
        not title
        or comparable_text(title) != comparable_text(expected_title)
        or location != expected_location
        or workload != expected_workload
        or start != expected_start
        or apply_urls != {REY_APPLICATION_URL}
        or not description
        or len(description) < 120
    ):
        raise ReyTechnologyParseError(
            "Rey Technology detail page contains an incomplete vacancy"
        )

    return {
        "id": expected_job_id,
        "title": title,
        "company": REY_COMPANY,
        "location": normalize_location(location),
        "listing_location": location,
        "workload": workload,
        "start": start,
        "url": public_url,
        "apply_url": REY_APPLICATION_URL,
        "description": description,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    title = optional_text(detail.get("title")) or optional_text(record.get("title"))
    public_url = optional_text(detail.get("url")) or optional_text(record.get("url"))
    return ParsedJob(
        source="rey_technology",
        title=title,
        company=REY_COMPANY,
        location=(
            optional_text(detail.get("location"))
            or optional_text(record.get("location"))
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
        seniority="Senior" if "senior" in comparable_text(title).split() else None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    site_names = unique_attribute_values(
        page,
        'meta[property="og:site_name"]',
        "content",
    )
    languages = unique_attribute_values(page, "html", "lang")
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or site_names != {EXPECTED_SITE_NAME}
        or languages != {EXPECTED_LANGUAGE}
    ):
        raise ReyTechnologyParseError("Rey Technology page has an invalid identity")


def canonical_careers_url(value: Any) -> str | None:
    return canonical_rey_url(value, expected_path="/en/career/vacancies")


def canonical_application_url(value: Any) -> str | None:
    return canonical_rey_url(value, expected_path="/en/career/vacancies/application")


def canonical_rey_url(value: Any, *, expected_path: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path).rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "rey-technology.com"
        or path != expected_path
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://www.rey-technology.com{expected_path}/"


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path).rstrip("/")
    match = JOB_PATH_PATTERN.fullmatch(path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "rey-technology.com"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://www.rey-technology.com{path}/"


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(unquote(urlsplit(text).path).rstrip("/"))
    return match.group(1) if match else None


def normalize_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if text == "Freiburg":
        return "Freiburg, Germany"
    if "Freiburg" in text:
        return f"{text}, Switzerland / Germany"
    if "Switzerland" in text:
        return text
    return f"{text}, Switzerland"


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if not WORKLOAD_PATTERN.fullmatch(text):
        return None
    compact = re.sub(r"\s+", "", text)
    return compact.replace("-", "–")


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == "https"
        and target.scheme == "https"
        and actual.netloc.casefold().removeprefix("www.")
        == target.netloc.casefold().removeprefix("www.")
        == "rey-technology.com"
        and unquote(actual.path).rstrip("/") == unquote(target.path).rstrip("/")
        and not actual.query
        and not target.query
        and not actual.fragment
        and not target.fragment
    )


def deduplicate_rey_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def single_text(selector: Any, css: str, *, allow_empty: bool = False) -> str | None:
    nodes = selector.css(css)
    if len(nodes) != 1:
        return None
    value = selector_text(nodes[0])
    return "" if allow_empty and value is None else value


def prefixed_text(
    value: Any,
    prefix: str,
    *,
    allow_empty: bool = False,
) -> str | None:
    text = optional_text(value)
    if not text or not text.startswith(prefix):
        return None
    remainder = optional_text(text.removeprefix(prefix))
    return "" if allow_empty and remainder is None else remainder


def selector_text(selector: Any) -> str | None:
    return optional_text(" ".join(selector.css("::text").getall()))


def unique_text_values(selector: Any, css: str) -> set[str]:
    return {
        value
        for node in selector.css(css)
        if (value := selector_text(node))
    }


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f'{css}::attr("{attribute}")').getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    decoded = html.unescape(value)
    decoded = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", decoded)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", decoded)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = html.unescape(text).replace("\xa0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip() or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None
