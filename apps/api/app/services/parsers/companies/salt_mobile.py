from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SALT_MOBILE_CAREERS_URL = (
    "https://company.jobcloud.ch/de/job-list/1772460841133x163767963229093900?embedded=yes"
)
SALT_MOBILE_LIST_ID = "1772460841133x163767963229093900"
SALT_MOBILE_LIST_PATH = f"/de/job-list/{SALT_MOBILE_LIST_ID}"
SALT_MOBILE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,it-CH;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
PAGE_PARAMETER = "2f2acfb9_page"
PAGE_COUNT_PATTERN = re.compile(r"^(\d+)\s*/\s*(\d+)$")
JOB_PATH_PATTERN = re.compile(
    r"^/de/jobs/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)
APPLICATION_PATH_PATTERN = re.compile(
    r"^/(?:de|fr|it|en)/application/create/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$"
)


class SaltMobileParseError(DirectCompanyRequestError):
    pass


class SaltMobileJobsParser:
    """Collect Salt Mobile's complete JobCloud-hosted Webflow catalog."""

    parser_id = "salt_mobile"

    def __init__(
        self,
        *,
        base_url: str = SALT_MOBILE_CAREERS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**SALT_MOBILE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total_pages = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SaltMobileParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Salt Mobile vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Salt Mobile vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_salt_mobile_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Salt Mobile vacancies across {total_pages} "
                f"Webflow pages using {pages_fetched} requests"
            ),
        )

    def listing_url(self, page: int) -> str:
        url = httpx.URL(self.base_url)
        if page > 1:
            url = url.copy_merge_params({PAGE_PARAMETER: page})
        return str(url)

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_pages: int | None = None
        expected_count: int | None = None
        pages_fetched = 0

        # Webflow pages can shift as a job is published. Union stable UUIDs
        # over bounded full walks until all slots observed in one walk exist.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            response = client.get(self.listing_url(1))
            response.raise_for_status()
            total_pages, first_records = parse_listing_html(
                response.text,
                page_url=str(response.url),
                expected_page=1,
            )
            pages_fetched += 1
            if total_pages > self.max_pages:
                raise SaltMobileParseError(
                    f"Salt Mobile catalog exceeds the configured limit of {self.max_pages} pages"
                )
            if expected_pages is None:
                expected_pages = total_pages
            elif total_pages != expected_pages:
                raise SaltMobileParseError("Salt Mobile changed its page count during pagination")
            page_size = len(first_records)
            if page_size < 1:
                raise SaltMobileParseError("Salt Mobile catalog is missing its page size")

            page_results = [first_records]
            for page_number in range(2, total_pages + 1):
                page_response = client.get(self.listing_url(page_number))
                page_response.raise_for_status()
                page_total, page_records = parse_listing_html(
                    page_response.text,
                    page_url=str(page_response.url),
                    expected_page=page_number,
                )
                pages_fetched += 1
                if page_total != expected_pages:
                    raise SaltMobileParseError(
                        "Salt Mobile changed its page count during pagination"
                    )
                if page_number < total_pages and len(page_records) != page_size:
                    raise SaltMobileParseError("Salt Mobile catalog returned an incomplete page")
                if page_number == total_pages and not 0 < len(page_records) <= page_size:
                    raise SaltMobileParseError("Salt Mobile catalog returned an invalid final page")
                page_results.append(page_records)

            observed_count = sum(len(page_records) for page_records in page_results)
            if expected_count is None:
                expected_count = observed_count
            elif observed_count != expected_count:
                raise SaltMobileParseError(
                    "Salt Mobile changed its vacancy count during pagination"
                )
            for page_number, page_records in enumerate(page_results, start=1):
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_page"] = page_number
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_count
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_count:
                return list(records_by_id.values()), pages_fetched, expected_pages
            if len(records_by_id) > expected_count:
                raise SaltMobileParseError("Salt Mobile catalog changed while pages were collected")

        raise SaltMobileParseError(
            f"Salt Mobile returned {len(records_by_id)} unique vacancies but exposed "
            f"{expected_count or 0} catalog slots"
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
                    expected_id=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, SaltMobileParseError, ValueError) as exc:
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
    expected_page: int,
) -> tuple[int, list[dict[str, Any]]]:
    validate_listing_url(page_url, expected_page=expected_page)
    page = Selector(page_html)
    languages = unique_values(page, "html::attr(lang)")
    slugs = unique_values(page, "html::attr(data-wf-item-slug)")
    titles = unique_values(page, "title::text")
    alternates = unique_values(
        page,
        'link[rel="alternate"][hreflang="de-CH"]::attr(href)',
    )
    page_counts = unique_values(page, ".w-page-count::text")
    alternate_url = f"https://company.jobcloud.ch{SALT_MOBILE_LIST_PATH}"
    if expected_page > 1:
        alternate_url = f"{alternate_url}?{PAGE_PARAMETER}={expected_page}"
    if (
        languages != {"de-CH"}
        or slugs != {SALT_MOBILE_LIST_ID}
        or titles != {"Salt Mobile SA -"}
        or alternates != {alternate_url}
        or len(page_counts) != 1
    ):
        raise SaltMobileParseError("Salt Mobile catalog has an unexpected identity")
    match = PAGE_COUNT_PATTERN.fullmatch(next(iter(page_counts)))
    if not match or int(match.group(1)) != expected_page:
        raise SaltMobileParseError("Salt Mobile catalog returned an unexpected page")
    total_pages = int(match.group(2))
    if total_pages < expected_page:
        raise SaltMobileParseError("Salt Mobile catalog has an invalid page count")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in page.css(".job_list_list > .job_list_item"):
        record = parse_listing_item(item)
        if record["id"] in seen_ids:
            raise SaltMobileParseError("Salt Mobile catalog page contains duplicate vacancy IDs")
        seen_ids.add(record["id"])
        records.append(record)
    if not records:
        raise SaltMobileParseError("Salt Mobile catalog returned an empty page")
    return total_pages, records


def parse_listing_item(item: Any) -> dict[str, Any]:
    title = selector_text(item, '[fs-cmsfilter-field="name"]')
    category = selector_text(item, '[fs-cmsfilter-field="JobCategory"]')
    location = selector_text(item, '[fs-cmsfilter-field="Location"]')
    workload = selector_text(item, '[fs-cmsfilter-field="Pensum"]')
    contract = selector_text(item, '[fs-cmsfilter-field="ContractType"]')
    links = unique_values(item, "a.job_list_item-link::attr(href)")
    if not title or not category or not location or not workload or not contract or len(links) != 1:
        raise SaltMobileParseError("Salt Mobile catalog contains an incomplete vacancy")
    detail_url = normalize_detail_url(next(iter(links)))
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(detail_url or "").path)
    if not detail_url or not match:
        raise SaltMobileParseError("Salt Mobile catalog contains an invalid vacancy URL")
    return {
        "id": match.group(1),
        "title": title,
        "category": category,
        "location": location,
        "workload": workload,
        "contract": contract,
        "url": detail_url,
    }


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_id: str,
    expected_title: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise SaltMobileParseError("Salt Mobile vacancy returned unexpected content")
    page = Selector(page_html)
    languages = unique_values(page, "html::attr(lang)")
    slugs = unique_values(page, "html::attr(data-wf-item-slug)")
    alternates = unique_values(
        page,
        'link[rel="alternate"][hreflang="de-CH"]::attr(href)',
    )
    titles = unique_values(page, "h1::text")
    og_titles = unique_values(page, 'meta[property="og:title"]::attr(content)')
    descriptions = page.css(".text-rich-text.w-richtext")
    apply_urls = {
        normalized
        for raw in page.css("#job-ad-apply-btn::attr(href)").getall()
        if (normalized := normalize_apply_url(raw, expected_id=expected_id))
    }
    if (
        languages != {"de-CH"}
        or slugs != {expected_id}
        or alternates != {expected_url}
        or titles != {expected_title}
        or og_titles != {f"Jetzt bewerben! - {expected_title} bei Salt Mobile SA"}
        or len(descriptions) != 1
        or len(apply_urls) != 1
    ):
        raise SaltMobileParseError("Salt Mobile vacancy has an unexpected identity")
    description = html_to_text(descriptions[0].get())
    metadata = extract_detail_metadata(page)
    posted_at = normalize_publication_date(metadata.get("Veröffentlicht"))
    workload = optional_text(metadata.get("Pensum"))
    contract = optional_text(metadata.get("Vertrag"))
    location = extract_labeled_value(
        description,
        ("Arbeitsort", "Lieu de travail", "Luogo di lavoro"),
    ) or clean_location(metadata.get("Arbeitsort"))
    if not description or not posted_at or not workload or not contract or not location:
        raise SaltMobileParseError("Salt Mobile vacancy contains incomplete details")
    return {
        "title": expected_title,
        "company": "Salt Mobile SA",
        "location": location,
        "workload": workload,
        "contract": contract,
        "employment_type": format_employment_type(contract, workload),
        "posted_at": posted_at,
        "description": description,
        "apply_url": next(iter(apply_urls)),
        "metadata": metadata,
    }


def extract_detail_metadata(page: Selector) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in page.css(".job_details_keyinfo-details"):
        label = selector_text(item, ".text-weight-semibold")
        value = selector_text(item, ".text-size-small")
        if label and value and value.casefold() != "null":
            metadata[label] = value
    return metadata


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="salt_mobile",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company="Salt Mobile SA",
        location=(optional_text(detail.get("location")) or optional_text(record.get("location"))),
        url=optional_text(record.get("url")),
        apply_url=(optional_text(detail.get("apply_url")) or optional_text(record.get("url"))),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or format_employment_type(record.get("contract"), record.get("workload"))
        ),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def validate_listing_url(value: str, *, expected_page: int) -> None:
    parts = urlsplit(value)
    query = httpx.QueryParams(parts.query)
    actual_page = optional_int(query.get(PAGE_PARAMETER)) or 1
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "company.jobcloud.ch"
        or parts.path != SALT_MOBILE_LIST_PATH
        or query.get("embedded") != "yes"
        or actual_page != expected_page
        or parts.fragment
    ):
        raise SaltMobileParseError("Salt Mobile catalog returned an unexpected URL")


def normalize_detail_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path
    if not parts.scheme and not parts.netloc:
        parts = urlsplit(f"https://company.jobcloud.ch{path}")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "company.jobcloud.ch"
        or parts.query
        or parts.fragment
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
    ):
        return None
    return urlunsplit(("https", "company.jobcloud.ch", parts.path, "", ""))


def normalize_apply_url(value: Any, *, expected_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLICATION_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() not in {"www.jobup.ch", "www.jobs.ch"}
        or not match
        or match.group(1) != expected_id
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", parts.netloc.casefold(), parts.path.rstrip("/"), "", ""))


def extract_labeled_value(value: str | None, labels: tuple[str, ...]) -> str | None:
    if not value:
        return None
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?im)^(?:{label_pattern})\s*:\s*(.+)$", value)
    return optional_text(match.group(1)) if match else None


def clean_location(value: Any) -> str | None:
    text = optional_text(value)
    return text.lstrip(", ") or None if text else None


def normalize_publication_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    except ValueError:
        return None


def format_employment_type(contract: Any, workload: Any) -> str | None:
    contract_text = optional_text(contract)
    workload_text = optional_text(workload)
    if not contract_text and not workload_text:
        return None
    labels = {
        "festanstellung": "Permanent",
        "befristet": "Fixed-term",
        "temporär": "Temporary",
        "praktikum": "Internship",
    }
    normalized_contract = labels.get((contract_text or "").casefold(), contract_text)
    return " · ".join(value for value in (normalized_contract, workload_text) if value)


def deduplicate_salt_mobile_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    output: list[ParsedJob] = []
    seen: set[str] = set()
    for job in jobs:
        key = optional_text(job.raw.get("id")) or optional_text(job.url)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(job)
    return output


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def selector_text(selector: Any, css: str) -> str | None:
    nodes = selector.css(css)
    return optional_text(" ".join(nodes[0].css("::text").getall())) if len(nodes) == 1 else None


def unique_values(selector: Any, css: str) -> set[str]:
    return {value for raw in selector.css(css).getall() if (value := optional_text(raw))}


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def same_url(left: Any, right: Any) -> bool:
    actual = optional_text(left)
    expected = optional_text(right)
    if not actual or not expected:
        return False
    left_parts = urlsplit(actual)
    right_parts = urlsplit(expected)
    return (
        left_parts.scheme == right_parts.scheme == "https"
        and left_parts.netloc.casefold() == right_parts.netloc.casefold()
        and left_parts.path.rstrip("/") == right_parts.path.rstrip("/")
        and left_parts.query == right_parts.query
        and not left_parts.fragment
    )
