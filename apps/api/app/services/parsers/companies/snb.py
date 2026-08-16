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

SNB_JOBS_BASE_URL = "https://careers.snb.ch/search/?locale=de_DE"
SNB_JOBS_API_URL = "https://careers.snb.ch/services/recruiting/v1/jobs"
SNB_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Schweizerische Nationalbank"
EXPECTED_LOCALE = "de_DE"
CSRF_TOKEN_PATTERN = re.compile(r'"X-CSRF-Token"\s*:\s*"([^"]+)"')
JOB_PATH_PATTERN = re.compile(r"^/job/[^/?#]+/(\d+)-de_DE/?$", re.IGNORECASE)
APPLY_PATH_PATTERN = re.compile(r"^/talentcommunity/apply/(\d+)/?$", re.IGNORECASE)
URL_TITLE_PATTERN = re.compile(r"^[^/?#\\\s]+$")
SWISS_LOCATION_PATTERN = re.compile(r"(?:^|,\s*)Schweiz\s*$", re.IGNORECASE)
WORKLOAD_PATTERN = re.compile(
    r"\b(?:\d{1,3}\s*%\s*[–-]\s*\d{1,3}\s*%|"
    r"\d{1,3}\s*[–-]\s*\d{1,3}\s*%|\d{1,3}\s*%)"
)


class SnbParseError(DirectCompanyRequestError):
    pass


class SnbJobsParser:
    """Collect the complete Swiss vacancy catalog from SNB SuccessFactors."""

    parser_id = "snb"

    def __init__(
        self,
        *,
        base_url: str = SNB_JOBS_BASE_URL,
        api_url: str = SNB_JOBS_API_URL,
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
                headers={**SNB_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                csrf_token = self.bootstrap_session(client)
                catalog_records, pages_fetched, total = self.collect_listing_records(
                    client,
                    csrf_token=csrf_token,
                )
                records = [record for record in catalog_records if record["is_swiss"]]
                self.enrich_records(client, records)
        except SnbParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("SNB vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("SNB vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_snb_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} SNB Switzerland vacancies from {total} global "
                f"catalog records across {pages_fetched} page {request_label}"
            ),
        )

    def bootstrap_session(self, client: httpx.Client) -> str:
        response = client.get(
            self.base_url,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        )
        response.raise_for_status()
        if not same_url(str(response.url), self.base_url):
            raise SnbParseError("SNB search page returned unexpected content")
        match = CSRF_TOKEN_PATTERN.search(response.text)
        canonicals = {
            urljoin(str(response.url), value)
            for raw in Selector(response.text).css('link[rel="canonical"]::attr(href)').getall()
            if (value := optional_text(raw))
        }
        expected_canonical = str(httpx.URL(self.base_url).copy_remove_param("locale"))
        if (
            not match
            or len(canonicals) != 1
            or not same_url(next(iter(canonicals)), expected_canonical)
        ):
            raise SnbParseError("SNB search page is missing its session contract")
        return match.group(1)

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        csrf_token: str,
        page_number: int,
    ) -> tuple[list[dict[str, Any]], int]:
        response = client.post(
            self.api_url,
            headers={"X-CSRF-Token": csrf_token},
            json={
                "locale": EXPECTED_LOCALE,
                "pageNumber": page_number,
                "sortBy": "referencedate",
                "keywords": "",
                "location": "",
                "facetFilters": {},
                "brand": "",
                "skills": [],
                "categoryId": 0,
                "alertId": "",
                "rcmCandidateId": "",
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
        *,
        csrf_token: str,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        expected_page_size: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, total = self.fetch_listing_page(
                client,
                csrf_token=csrf_token,
                page_number=0,
            )
            pages_fetched += 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise SnbParseError("SNB catalog changed its result count during pagination")
            if total == 0:
                return [], pages_fetched, 0

            page_size = len(first_records)
            if page_size <= 0:
                raise SnbParseError("SNB listing is missing its page size")
            if expected_page_size is None:
                expected_page_size = page_size
            elif page_size != expected_page_size:
                raise SnbParseError("SNB catalog changed its page size during pagination")

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise SnbParseError(
                    f"SNB exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [first_records]
            for page_number in range(1, required_pages):
                page_records, page_total = self.fetch_listing_page(
                    client,
                    csrf_token=csrf_token,
                    page_number=page_number,
                )
                pages_fetched += 1
                if page_total != expected_total:
                    raise SnbParseError("SNB catalog changed its result count during pagination")
                expected_count = min(page_size, total - page_number * page_size)
                if len(page_records) != expected_count:
                    raise SnbParseError("SNB pagination returned an unexpected page size")
                page_results.append(page_records)

            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise SnbParseError("SNB catalog changed while pages were collected")

        raise SnbParseError(
            f"SNB returned {len(records_by_id)} unique vacancies but declared {expected_total or 0}"
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
                response = client.get(
                    str(record["url"]),
                    headers={
                        "Accept": (
                            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                        ),
                        "Referer": self.base_url,
                    },
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=str(record["url"]),
                    expected_job_id=str(record["id"]),
                    expected_title=str(record["title"]),
                    expected_cities=list(record["cities"]),
                    expected_employment_type=str(record["employment_type"]),
                    expected_work_model=str(record["work_model"]),
                )
            except (httpx.HTTPError, SnbParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_listing_payload(
    payload: Any,
    *,
    base_url: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise SnbParseError("SNB listing returned an invalid payload")
    total = payload.get("totalJobs")
    rows = payload.get("jobSearchResult")
    if not isinstance(total, int) or total < 0 or not isinstance(rows, list):
        raise SnbParseError("SNB listing is missing its vacancy catalog")
    if total > 0 and not rows:
        raise SnbParseError("SNB listing is missing its vacancy catalog")

    expected_host = urlsplit(base_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for wrapper in rows:
        record = wrapper.get("response") if isinstance(wrapper, dict) else None
        if not isinstance(record, dict):
            raise SnbParseError("SNB listing contains an incomplete vacancy")
        job_id = optional_text(record.get("id"))
        title = optional_text(record.get("unifiedStandardTitle"))
        url_title = html.unescape(optional_text(record.get("unifiedUrlTitle")) or "")
        locales = normalized_string_list(record.get("supportedLocales"))
        locations = [
            value
            for raw in normalized_string_list(record.get("jobLocationShort"))
            if (value := optional_text(html.unescape(raw)))
        ]
        work_models = normalized_string_list(record.get("cust_arbeitsform"))
        employment_types = normalized_string_list(record.get("cust_vertragsart"))
        posted_at = parse_short_date(record.get("unifiedStandardStart"))
        detail_url = urljoin(base_url, f"/job/{url_title}/{job_id}-{EXPECTED_LOCALE}/")
        cities = [location.split(",", 1)[0].strip() for location in locations]
        if (
            not job_id
            or not job_id.isdigit()
            or not title
            or not URL_TITLE_PATTERN.fullmatch(url_title)
            or EXPECTED_LOCALE not in locales
            or not locations
            or any(not city for city in cities)
            or len(work_models) != 1
            or len(employment_types) != 1
            or not posted_at
            or not is_job_url(detail_url, expected_host=expected_host)
        ):
            raise SnbParseError("SNB listing contains an incomplete vacancy")
        if job_id in seen_ids:
            raise SnbParseError("SNB listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": "; ".join(locations),
                "cities": cities,
                "is_swiss": all(is_swiss_location(value) for value in locations),
                "work_model": work_models[0],
                "employment_type": employment_types[0],
                "posted_at": posted_at,
                "url": detail_url,
                "listing_page_number": page_number,
                "listing": dict(record),
            }
        )
    if len(records) > total:
        raise SnbParseError("SNB listing returned more vacancies than declared")
    return records, total


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_cities: list[str],
    expected_employment_type: str,
    expected_work_model: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or extract_job_id(page_url) != expected_job_id:
        raise SnbParseError("SNB detail page returned a different vacancy")
    page = Selector(page_html)
    canonicals = {
        urljoin(page_url, value)
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
        if (value := optional_text(raw))
    }
    titles = {
        title
        for raw in page.css('meta[property="og:title"]::attr(content)').getall()
        if (title := optional_text(html.unescape(raw)))
    }
    document_titles = {
        title
        for raw in page.css("head > title::text").getall()
        if (title := optional_text(html.unescape(raw)))
    }
    description_parts = [
        value
        for node in page.css(".joblayouttoken span.rtltextaligneligible")
        if (value := html_to_text(node.get()))
    ]
    description = "\n\n".join(dict.fromkeys(description_parts)) or None
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
    first_part = description_parts[0] if description_parts else ""
    workload = extract_workload(first_part)
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or titles != {expected_title}
        or document_titles != {f"{expected_title} Stellendetails | {EXPECTED_COMPANY}"}
        or len(description_parts) < 2
        or not description
        or expected_title not in first_part
        or (expected_employment_type.casefold() != "lehrstelle" and not workload)
        or any(city not in first_part for city in expected_cities)
        or expected_employment_type not in first_part
        or expected_work_model not in first_part
        or len(apply_urls) != 1
    ):
        raise SnbParseError("SNB detail page contains an incomplete vacancy")
    return {
        "id": expected_job_id,
        "title": expected_title,
        "company": EXPECTED_COMPANY,
        "workload": workload,
        "employment_type": expected_employment_type,
        "work_model": expected_work_model,
        "apply_url": next(iter(apply_urls)),
        "description": description,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    job_id = optional_text(record.get("id"))
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="snb",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=optional_text(record.get("location")),
        url=public_url,
        apply_url=(
            optional_text(detail.get("apply_url"))
            or build_apply_url(public_url or SNB_JOBS_BASE_URL, job_id)
        ),
        posted_at=optional_text(record.get("posted_at")),
        employment_type=join_unique(
            optional_text(detail.get("workload")),
            optional_text(record.get("employment_type")),
            optional_text(record.get("work_model")),
        ),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def parse_short_date(value: Any) -> str | None:
    text = optional_text(value)
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2})", text or "")
    if not match:
        return None
    day, month, short_year = (int(part) for part in match.groups())
    try:
        return date(2000 + short_year, month, day).isoformat()
    except ValueError:
        return None


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    match = WORKLOAD_PATTERN.search(text or "")
    return optional_text(match.group(0)) if match else None


def normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := optional_text(item))]


def is_swiss_location(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and SWISS_LOCATION_PATTERN.search(text))


def is_job_url(value: Any, *, expected_host: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parsed = urlsplit(text)
    return (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == expected_host
        and not parsed.query
        and not parsed.fragment
        and JOB_PATH_PATTERN.fullmatch(parsed.path) is not None
    )


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1) if match else None


def normalize_apply_url(
    value: Any,
    *,
    expected_job_id: str,
    expected_host: str,
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parsed = urlsplit(html.unescape(text))
    match = APPLY_PATH_PATTERN.fullmatch(parsed.path)
    query = parse_qs(parsed.query)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != expected_host
        or parsed.fragment
        or not match
        or match.group(1) != expected_job_id
        or query != {"locale": [EXPECTED_LOCALE]}
    ):
        return None
    return f"https://{expected_host}/talentcommunity/apply/{expected_job_id}/?locale=de_DE"


def build_apply_url(base_url: str, job_id: str | None) -> str | None:
    if not job_id:
        return None
    host = urlsplit(base_url).netloc.casefold()
    return f"https://{host}/talentcommunity/apply/{job_id}/?locale=de_DE"


def same_url(left: Any, right: Any) -> bool:
    left_text = optional_text(left)
    right_text = optional_text(right)
    if not left_text or not right_text:
        return False

    def normalized(value: str) -> tuple[str, str, str, str]:
        parsed = urlsplit(value)
        return (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/") or "/",
            parsed.query,
        )

    return normalized(left_text) == normalized(right_text)


def deduplicate_snb_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def join_unique(*values: str | None) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    return normalized or None
