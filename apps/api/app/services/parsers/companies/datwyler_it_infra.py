from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

DATWYLER_JOBS_BASE_URL = (
    "https://careers.datwyler-itinfra.com/search/?locale=de_DE&"
    "searchResultView=LIST&facetFilters=%7B%22jobLocationCountry%22%3A%5B%22"
    "Schweiz%22%5D%7D&pageNumber=0"
)
DATWYLER_JOBS_API_URL = "https://careers.datwyler-itinfra.com/services/recruiting/v1/jobs"
DATWYLER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^/job/.+/(\d+)-de_DE/?$")
APPLY_PATH_PATTERN = re.compile(r"^/talentcommunity/apply/(\d+)/$")
URL_TITLE_PATTERN = re.compile(r"^[A-Za-z0-9_.%&;-]+$")
EXPECTED_COMPANY = "Dätwyler IT Infra"
EXPECTED_COUNTRY = "Schweiz"
EXPECTED_LOCALE = "de_DE"


class DatwylerItInfraParseError(DirectCompanyRequestError):
    pass


class DatwylerItInfraJobsParser:
    """Collect Dätwyler IT Infra's complete Swiss SuccessFactors catalog."""

    parser_id = "datwyler_it_infra"

    def __init__(
        self,
        *,
        base_url: str = DATWYLER_JOBS_BASE_URL,
        api_url: str = DATWYLER_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**DATWYLER_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except DatwylerItInfraParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Dätwyler IT Infra vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Dätwyler IT Infra vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_datwyler_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Dätwyler IT Infra Switzerland vacancies "
                f"from {total} catalog records across {pages_fetched} page "
                f"{request_label}"
            ),
        )

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        page_number: int,
    ) -> tuple[list[dict[str, Any]], int]:
        response = client.post(
            self.api_url,
            json={
                "keywords": "",
                "locale": EXPECTED_LOCALE,
                "location": "",
                "pageNumber": page_number,
                "sortBy": "recent",
                "facetFilters": {"jobLocationCountry": [EXPECTED_COUNTRY]},
            },
        )
        response.raise_for_status()
        return parse_listing_payload(
            response.json(),
            base_url=self.base_url,
            page_number=page_number,
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        expected_page_size: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, total = self.fetch_listing_page(client, page_number=0)
            pages_fetched += 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise DatwylerItInfraParseError(
                    "Dätwyler IT Infra catalog changed its result count during pagination"
                )
            page_size = len(first_records)
            if page_size <= 0:
                raise DatwylerItInfraParseError(
                    "Dätwyler IT Infra listing is missing its page size"
                )
            if expected_page_size is None:
                expected_page_size = page_size
            elif page_size != expected_page_size:
                raise DatwylerItInfraParseError(
                    "Dätwyler IT Infra catalog changed its page size during pagination"
                )

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise DatwylerItInfraParseError(
                    f"Dätwyler IT Infra exposes {required_pages} pages, above the "
                    f"configured limit of {self.max_pages}"
                )

            page_results = [first_records]
            for page_number in range(1, required_pages):
                records, page_total = self.fetch_listing_page(
                    client,
                    page_number=page_number,
                )
                pages_fetched += 1
                if page_total != expected_total:
                    raise DatwylerItInfraParseError(
                        "Dätwyler IT Infra catalog changed its result count during pagination"
                    )
                expected_count = min(page_size, total - page_number * page_size)
                if len(records) != expected_count:
                    raise DatwylerItInfraParseError(
                        "Dätwyler IT Infra pagination returned an unexpected page size"
                    )
                page_results.append(records)

            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise DatwylerItInfraParseError(
                    "Dätwyler IT Infra catalog changed while pages were collected"
                )

        raise DatwylerItInfraParseError(
            f"Dätwyler IT Infra returned {len(records_by_id)} unique vacancies but "
            f"declared {expected_total or 0}"
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
                    expected_location=record["location"],
                    expected_workplace_type=record["workplace_type"],
                )
            except (httpx.HTTPError, DatwylerItInfraParseError, ValueError) as exc:
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
        job_id = optional_text(record.get("id"))
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=optional_text(record.get("location")),
            url=public_url,
            apply_url=(
                optional_text(detail.get("apply_url")) or build_apply_url(self.base_url, job_id)
            ),
            posted_at=optional_text(record.get("posted_at")),
            employment_type=None,
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_payload(
    payload: Any,
    *,
    base_url: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise DatwylerItInfraParseError("Dätwyler IT Infra listing returned an invalid payload")
    total = payload.get("totalJobs")
    rows = payload.get("jobSearchResult")
    if not isinstance(total, int) or total <= 0 or not isinstance(rows, list) or not rows:
        raise DatwylerItInfraParseError("Dätwyler IT Infra listing is missing its vacancy catalog")

    expected_host = urlsplit(base_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for wrapper in rows:
        record = wrapper.get("response") if isinstance(wrapper, dict) else None
        if not isinstance(record, dict):
            raise DatwylerItInfraParseError(
                "Dätwyler IT Infra listing contains an incomplete vacancy"
            )
        job_id = optional_text(record.get("id"))
        title = optional_text(record.get("unifiedStandardTitle"))
        url_title = html.unescape(optional_text(record.get("unifiedUrlTitle")) or "")
        countries = normalized_string_list(record.get("jobLocationCountry"))
        locales = normalized_string_list(record.get("supportedLocales"))
        locations = [
            value.rstrip("/").strip()
            for raw in normalized_string_list(record.get("jobLocationShort"))
            if (value := html_to_text(raw))
        ]
        workplace_types = normalized_string_list(record.get("workplacetype"))
        posted_at = parse_short_date(record.get("unifiedStandardStart"))
        detail_url = urljoin(
            base_url,
            f"/job/{url_title}/{job_id}-{EXPECTED_LOCALE}",
        )
        if (
            not job_id
            or not job_id.isdigit()
            or not title
            or not URL_TITLE_PATTERN.fullmatch(url_title)
            or countries != [EXPECTED_COUNTRY]
            or EXPECTED_LOCALE not in locales
            or not locations
            or any(not is_swiss_location(value) for value in locations)
            or len(workplace_types) != 1
            or not posted_at
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise DatwylerItInfraParseError(
                "Dätwyler IT Infra listing contains incomplete or non-Swiss vacancy data"
            )
        if job_id in seen_ids:
            raise DatwylerItInfraParseError(
                "Dätwyler IT Infra listing contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": "; ".join(locations),
                "country": EXPECTED_COUNTRY,
                "workplace_type": workplace_types[0],
                "posted_at": posted_at,
                "url": detail_url,
                "listing_page_number": page_number,
            }
        )
    return records, total


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_location: str,
    expected_workplace_type: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_job_id:
        raise DatwylerItInfraParseError(
            "Dätwyler IT Infra detail page returned a different vacancy"
        )

    page = Selector(page_html)
    if len(page.css('[itemtype="http://schema.org/JobPosting"]')) != 1:
        raise DatwylerItInfraParseError(
            "Dätwyler IT Infra detail page is missing its JobPosting data"
        )
    canonicals = {
        urljoin(page_url, value)
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    titles = unique_selector_texts(page, '[itemprop="title"]')
    descriptions = page.css('[itemprop="description"]')
    description = html_to_text(descriptions[0].get()) if len(descriptions) == 1 else None
    apply_urls = {
        normalized
        for raw in page.css("a.dialogApplyBtn::attr(href)").getall()
        if (
            normalized := normalize_apply_url(
                urljoin(page_url, optional_text(raw) or ""),
                expected_job_id=expected_job_id,
                expected_host=urlsplit(expected_url).netloc.casefold(),
            )
        )
    }
    detail_location = extract_labeled_value(page, "Stellenstandort:")
    workplace_type = extract_labeled_value(page, "Arbeitsmodell:")
    expected_city = optional_text(expected_location.split(",", maxsplit=1)[0])
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals), None), expected_url)
        or titles != {expected_title}
        or len(apply_urls) != 1
        or not description
        or detail_location != expected_city
        or workplace_type != expected_workplace_type
    ):
        raise DatwylerItInfraParseError(
            "Dätwyler IT Infra detail page contains an incomplete vacancy"
        )

    return {
        "id": expected_job_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "location": expected_location,
        "workplace_type": workplace_type,
        "apply_url": next(iter(apply_urls)),
        "description": description,
    }


def extract_labeled_value(page: Selector, expected_label: str) -> str | None:
    for token in page.css(".joblayouttoken"):
        label = selector_text(token, ".joblayouttoken-label")
        if label == expected_label:
            values = [
                value
                for node in token.css("span.rtltextaligneligible")
                if (value := html_to_text(node.get()))
            ]
            return values[0] if len(values) == 1 else None
    return None


def normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := optional_text(item))]


def parse_short_date(value: Any) -> str | None:
    text = optional_text(value)
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{2})", text or "")
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(2000 + year, month, day).isoformat()
    except ValueError:
        return None


def is_swiss_location(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and re.search(r",\s*CHE(?:,|$)", text))


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    path = urlsplit(text).path
    job_match = JOB_PATH_PATTERN.fullmatch(path)
    if job_match:
        return job_match.group(1)
    apply_match = APPLY_PATH_PATTERN.fullmatch(path)
    return apply_match.group(1) if apply_match else None


def is_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and extract_job_id(text) is not None
        and not parts.query
        and not parts.fragment
    )


def normalize_apply_url(
    value: Any,
    *,
    expected_job_id: str,
    expected_host: str,
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or not match
        or match.group(1) != expected_job_id
        or parse_qs(parts.query, keep_blank_values=True) != {"locale": [EXPECTED_LOCALE]}
        or parts.fragment
    ):
        return None
    return text


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id or not job_id.isdigit():
        return None
    return urljoin(base_url, f"/talentcommunity/apply/{job_id}/?locale={EXPECTED_LOCALE}")


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
        and not actual.query
        and not actual.fragment
        and not target.query
        and not target.fragment
    )


def deduplicate_datwyler_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_selector_texts(page: Selector, css: str) -> set[str]:
    return {value for raw in page.css(css).getall() if (value := html_to_text(str(raw)))}


def selector_text(selector: Any, css: str) -> str | None:
    return optional_text(" ".join(selector.css(f"{css} ::text").getall()))


def html_to_text(value: Any) -> str | None:
    text = str(value or "")
    if not text:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return optional_multiline_text(text)


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        re.sub(r"^•\s*", "- ", re.sub(r"[ \t]+", " ", line).strip()) for line in text.split("\n")
    ]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return re.sub(r"\n\n(?=- )", "\n", normalized) or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
