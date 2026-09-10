from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

VZUG_CAREERS_URL = "https://www.vzug.com/ch/de/jobs"
VZUG_CATALOG_URL = "https://jobs.vzug.com/public/v1/careercenter/1002845/?lang=de"
VZUG_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "V-ZUG AG"
JOB_PATH_PATTERN = re.compile(
    r"^/offene-stellen/[a-z0-9]+(?:-[a-z0-9]+)*/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    r"^/public/v1/redirect/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/ats/?$",
    re.IGNORECASE,
)
WORK_META_PATTERN = re.compile(
    r"(?:du\s+arbeitest\s+)?"
    r"(\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%)\s+in\s+(.+?)"
    r"(?:\s+oder\s+teilweise\s+remote)?$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(
    r"(\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%)",
    re.IGNORECASE,
)
INVISIBLE_CHARACTERS_PATTERN = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")


class VzugParseError(DirectCompanyRequestError):
    pass


class VzugJobsParser:
    """Collect V-ZUG AG's complete public Prospective vacancy catalog."""

    parser_id = "vzug"

    def __init__(
        self,
        *,
        base_url: str = VZUG_CAREERS_URL,
        catalog_url: str = VZUG_CATALOG_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 200,
        detail_workers: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(2, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with CareerHttpClient(
                headers={**VZUG_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                careers_response = client.get(self.base_url)
                careers_response.raise_for_status()
                discovered_catalog_url = parse_careers_html(
                    careers_response.text,
                    page_url=str(careers_response.url),
                    expected_url=self.base_url,
                )
                if not same_url(discovered_catalog_url, self.catalog_url):
                    raise VzugParseError("V-ZUG career page changed its vacancy catalog")

                catalog_response = client.get(self.catalog_url)
                catalog_response.raise_for_status()
                records = parse_listing_html(
                    catalog_response.text,
                    page_url=str(catalog_response.url),
                    expected_url=self.catalog_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except VzugParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(f"V-ZUG vacancy request failed: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("V-ZUG vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_vzug_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} V-ZUG vacancies from the complete Prospective catalog"),
        )

    def enrich_records(
        self,
        client: CareerHttpClient,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(record["url"], headers={"Referer": self.catalog_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_id=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, VzugParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_careers_html(page_html: str, *, page_url: str, expected_url: str) -> str:
    if not same_url(page_url, expected_url):
        raise VzugParseError("V-ZUG career page returned unexpected content")
    page = Selector(page_html)
    canonicals = unique_values(page, 'link[rel="canonical"]::attr(href)')
    titles = unique_values(page, "head > title::text")
    iframe_urls = unique_values(page, "c-iframe iframe::attr(src)")
    if (
        canonicals != {expected_url}
        or titles != {"Offene Stellen und Jobs | V-ZUG Schweiz"}
        or len(iframe_urls) != 1
    ):
        raise VzugParseError("V-ZUG career page has an unexpected identity")
    return next(iter(iframe_urls))


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise VzugParseError("V-ZUG catalog returned unexpected content")
    page = Selector(page_html)
    form = page.css("form#oh-form")
    counts = unique_values(page, "#jobcount > strong::text")
    title = optional_text(page.css("head > title::text").get())
    if (
        len(form) != 1
        or optional_text(form.css('input[name="offset"]::attr(value)').get()) != "0"
        or optional_text(form.css('input[name="limit"]::attr(value)').get()) != "200"
        or optional_text(form.css('input[name="lang"]::attr(value)').get()) != "de"
        or title != "V-Zug Career Center"
        or len(counts) != 1
    ):
        raise VzugParseError("V-ZUG catalog is missing its listing contract")
    try:
        declared_count = int(next(iter(counts)))
    except ValueError as exc:
        raise VzugParseError("V-ZUG catalog has an invalid vacancy count") from exc
    if declared_count > max_jobs:
        raise VzugParseError(f"V-ZUG catalog exceeds the configured limit of {max_jobs} vacancies")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("section#jobResults .jobContent .job"):
        urls = {
            normalized
            for value in card.css("a::attr(href)").getall()
            if (normalized := normalize_job_url(value))
        }
        title_text = selector_text(card, "h4")
        location = selector_text(card, ":scope > span")
        summary = selector_text(card, ":scope > p")
        if len(urls) != 1 or not title_text or not summary:
            raise VzugParseError("V-ZUG catalog contains an incomplete vacancy")
        detail_url = next(iter(urls))
        job_id = extract_job_id(detail_url)
        if not job_id or job_id in seen_ids:
            raise VzugParseError("V-ZUG catalog contains duplicate or invalid vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title_text,
                "location": location,
                "summary": summary,
                "url": detail_url,
                "listing_page_url": page_url,
                "total_available": declared_count,
            }
        )

    if len(records) != declared_count:
        raise VzugParseError(
            f"V-ZUG catalog declared {declared_count} vacancies but exposed {len(records)}"
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_id: str,
    expected_title: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_id:
        raise VzugParseError("V-ZUG vacancy returned unexpected content")
    page = Selector(page_html)
    canonicals = unique_values(page, 'link[rel="canonical"]::attr(href)')
    titles = unique_selector_texts(page, "section#titleArea h1")
    authors = unique_values(page, 'meta[name="author"]::attr(content)')
    work_meta = selector_text(page, "section#titleArea span")
    workload, location, remote = parse_work_meta(work_meta)
    apply_urls = {
        normalized
        for value in page.css("section#callToActionApply a::attr(href)").getall()
        if (normalized := normalize_apply_url(value, expected_id=expected_id))
    }
    description = extract_description(page)
    if (
        canonicals != {expected_url}
        or titles != {expected_title}
        or authors != {EXPECTED_COMPANY}
        or not work_meta
        or len(apply_urls) != 1
        or not description
    ):
        raise VzugParseError("V-ZUG vacancy contains incomplete detail data")
    return {
        "id": expected_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "work_meta": work_meta,
        "workload": workload,
        "location": location,
        "remote": remote,
        "apply_url": next(iter(apply_urls)),
        "description": description,
    }


def extract_description(page: Selector) -> str | None:
    parts: list[str] = []
    for row in page.css("section#aboutJobRows .aboutRow"):
        heading = selector_text(row, ".aboutJobTitle h3")
        body_node = row.css(".aboutJobText")
        body = html_to_text(body_node[0].get()) if len(body_node) == 1 else None
        if not heading or not body:
            return None
        parts.append(f"{heading}\n{body}")
    return optional_multiline_text("\n\n".join(parts)) if parts else None


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    raw = dict(record)
    return ParsedJob(
        source="vzug",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=None,
        employment_type=optional_text(detail.get("workload")),
        seniority=None,
        description=(
            optional_multiline_text(detail.get("description"))
            or optional_text(record.get("summary"))
        ),
        raw=raw,
    )


def parse_work_meta(value: Any) -> tuple[str | None, str | None, bool]:
    text = optional_text(value)
    if not text:
        return None, None, False
    workload_match = WORKLOAD_PATTERN.search(text)
    workload = (
        re.sub(r"\s*[-–]\s*", "–", workload_match.group(1)).replace(" ", "")
        if workload_match
        else None
    )
    match = WORK_META_PATTERN.search(text)
    if not match:
        return workload, None, "remote" in text.casefold()
    workload = re.sub(r"\s*[-–]\s*", "–", match.group(1)).replace(" ", "")
    location = re.sub(r"^(?:der|dem)\s+", "", match.group(2), flags=re.IGNORECASE)
    return workload, optional_text(location), "remote" in text.casefold()


def normalize_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "jobs.vzug.com"
        or parts.query
        or parts.fragment
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
    ):
        return None
    return urlunsplit(("https", "jobs.vzug.com", parts.path.rstrip("/"), "", ""))


def normalize_apply_url(value: Any, *, expected_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.hostname != "ohws.prospective.ch"
        or parts.query
        or parts.fragment
        or not match
        or match.group(1).casefold() != expected_id.casefold()
    ):
        return None
    return urlunsplit(("https", parts.netloc, f"{parts.path.rstrip('/')}/", "", ""))


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1).casefold() if match else None


def deduplicate_vzug_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def same_url(left: Any, right: Any) -> bool:
    def normalized(value: Any) -> tuple[str, str, str, tuple[tuple[str, str], ...]] | None:
        text = optional_text(value)
        if not text:
            return None
        parts = urlsplit(text)
        return (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/") or "/",
            tuple(sorted(parse_qsl(parts.query, keep_blank_values=True))),
        )

    return normalized(left) == normalized(right)


def selector_text(page: Selector, selector: str) -> str | None:
    values = [value for node in page.css(selector) for value in node.css("::text").getall()]
    return optional_text(" ".join(str(value) for value in values))


def unique_selector_texts(page: Selector, selector: str) -> set[str]:
    return {
        value
        for node in page.css(selector)
        if (value := optional_text(" ".join(node.css("::text").getall())))
    }


def unique_values(page: Selector, selector: str) -> set[str]:
    return {value for raw in page.css(selector).getall() if (value := optional_text(raw))}


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = INVISIBLE_CHARACTERS_PATTERN.sub("", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    lines = [line.strip() for line in str(value).splitlines()]
    return "\n".join(line for line in lines if line)


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None
