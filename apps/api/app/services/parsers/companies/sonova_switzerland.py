from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

SONOVA_SWITZERLAND_JOBS_BASE_URL = (
    "https://www.sonova.com/careers/?query-1-job-country=switzerland-en"
)
SONOVA_JOBS_API_URL = "https://www.sonova.com/en/jobs_list/active?lang=en"
SONOVA_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
SUCCESSFACTORS_HOST = "career5.successfactors.eu"
PUBLIC_JOBS_HOST = "jobs.sonova.com"
PUBLIC_JOB_PATH = re.compile(r"^/job/.+/(\d+)/?$", re.IGNORECASE)
APPLY_PATH = re.compile(r"^/talentcommunity/apply/(\d+)/?$", re.IGNORECASE)
INTERNAL_ID_PATTERN = re.compile(r'"internalId"\s*:\s*"(\d+)-[^"]+"')
SWITZERLAND_TERM_ID = "718"


class SonovaSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SonovaSwitzerlandJobsParser:
    """Collect Swiss vacancies from Sonova's complete public widget snapshot."""

    parser_id = "sonova_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SONOVA_SWITZERLAND_JOBS_BASE_URL,
        api_url: str | None = None,
        timeout_seconds: float = 30.0,
        max_catalog_records: int = 2_000,
        detail_workers: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_catalog_records = max(1, max_catalog_records)
        self.detail_workers = min(2, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with CareerHttpClient(
                headers={**SONOVA_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except SonovaSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(f"Sonova vacancy request failed: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Sonova vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_sonova_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Sonova Switzerland vacancies from {total} "
                + (
                    "active group catalog records in 1 API request"
                    if self.api_url
                    else "records in the official Swiss careers catalog"
                )
            ),
        )

    def collect_listing_records(
        self,
        client: CareerHttpClient,
    ) -> tuple[list[dict[str, Any]], int]:
        if self.api_url is None:
            return self.collect_public_listing(client)
        response = client.get(self.api_url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise SonovaSwitzerlandParseError("Sonova jobs API returned a malformed catalog")
        if len(payload) > self.max_catalog_records:
            raise SonovaSwitzerlandParseError(
                f"Sonova returned {len(payload)} records, above the configured limit "
                f"of {self.max_catalog_records}"
            )

        seen_ids: set[str] = set()
        records: list[dict[str, Any]] = []
        for value in payload:
            if not isinstance(value, dict):
                raise SonovaSwitzerlandParseError("Sonova jobs API returned a malformed record")
            job_id = optional_text(value.get("jobReqId"))
            country = facet(value.get("country"))
            if not job_id or not job_id.isdigit() or job_id in seen_ids:
                raise SonovaSwitzerlandParseError(
                    "Sonova jobs API returned duplicate or malformed vacancy IDs"
                )
            seen_ids.add(job_id)
            if not country:
                raise SonovaSwitzerlandParseError(
                    "Sonova jobs API returned a malformed country facet"
                )
            is_swiss_id = country[0] == SWITZERLAND_TERM_ID
            is_swiss_label = country[1] == "Switzerland"
            if is_swiss_id != is_swiss_label:
                raise SonovaSwitzerlandParseError(
                    "Sonova jobs API returned an inconsistent Switzerland facet"
                )
            if is_swiss_id:
                records.append(parse_listing_record(value))

        for record in records:
            record["total_available"] = len(records)
            record["group_catalog_total"] = len(payload)
        return records, len(payload)

    def collect_public_listing(self, client: CareerHttpClient) -> tuple[list[dict[str, Any]], int]:
        url = self.base_url
        seen_pages: set[str] = set()
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        while url:
            if url in seen_pages:
                raise SonovaSwitzerlandParseError("Sonova catalog pagination repeated a page")
            seen_pages.add(url)
            response = client.get(url, headers={"Accept": "text/html"})
            response.raise_for_status()
            if str(response.url) != url:
                raise SonovaSwitzerlandParseError("Sonova catalog redirected unexpectedly")
            page = Selector(response.text)
            selected = page.css(
                'select[name="query-1-job-country"] option[selected]::attr(value)'
            ).getall()
            if selected != ["switzerland-en"]:
                raise SonovaSwitzerlandParseError("Sonova catalog lost its Switzerland filter")
            rows = page.css(".wp-block-query .table__content.table__row")
            if not rows and (records or not page.css(".wp-block-query-no-results")):
                raise SonovaSwitzerlandParseError("Sonova catalog is missing its vacancy rows")
            for row in rows:
                links = row.css("h3 a[href]")
                job_url = links[0].css("::attr(href)").get() if len(links) == 1 else None
                job_id = successfactors_job_id(job_url)
                title = optional_text(" ".join(links[0].css("::text").getall())) if links else None
                location = optional_text(" ".join(row.css("._sf_location::text").getall()))
                brand = optional_text(" ".join(row.css("._sf_brand::text").getall()))
                if not job_id or not title or not brand or not is_swiss_location(location):
                    raise SonovaSwitzerlandParseError(
                        "Sonova catalog contains an incomplete or non-Swiss vacancy"
                    )
                if job_id in seen_ids:
                    raise SonovaSwitzerlandParseError("Sonova catalog contains duplicate vacancies")
                seen_ids.add(job_id)
                records.append(
                    {
                        "id": job_id,
                        "title": title,
                        "location": location,
                        "brand": brand,
                        "url": job_url,
                        "contract_type": None,
                        "posted_at": None,
                    }
                )
            if len(records) > self.max_catalog_records:
                raise SonovaSwitzerlandParseError("Sonova catalog exceeds the configured limit")
            next_links = page.css(".wp-block-query-pagination-next::attr(href)").getall()
            if len(next_links) > 1:
                raise SonovaSwitzerlandParseError("Sonova catalog has ambiguous pagination")
            url = urljoin(url, next_links[0]) if next_links else ""
            if url:
                parts = urlsplit(url)
                query = parse_qs(parts.query)
                if (
                    parts.scheme != "https"
                    or parts.netloc != urlsplit(self.base_url).netloc
                    or parts.path != "/careers/"
                    or parts.fragment
                    or query.get("query-1-job-country") != ["switzerland-en"]
                    or query.get("query-1-page") != [str(len(seen_pages) + 1)]
                    or set(query) != {"query-1-job-country", "query-1-page"}
                ):
                    raise SonovaSwitzerlandParseError("Sonova catalog has invalid pagination")
        for record in records:
            record["total_available"] = len(records)
            record["group_catalog_total"] = len(records)
        return records, len(records)

    def enrich_records(
        self,
        client: CareerHttpClient,
        records: list[dict[str, Any]],
    ) -> None:
        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(record["url"], headers={"Accept": "text/html"})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                    expected_location=record["location"],
                )
            except (httpx.HTTPError, SonovaSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records) or 1)) as pool:
            futures = [pool.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or record["title"],
            company=optional_text(detail.get("company")) or record["brand"],
            location=optional_text(detail.get("location")) or record["location"],
            url=optional_text(detail.get("url")) or record["url"],
            apply_url=optional_text(detail.get("apply_url")) or record["url"],
            posted_at=optional_text(detail.get("posted_at")) or record["posted_at"],
            employment_type=record["contract_type"],
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SonovaSwitzerlandParseError("Sonova jobs API returned a malformed record")
    title = optional_text(value.get("title"))
    url = optional_text(value.get("url")) or ""
    contract = facet(value.get("contract_type"))
    brand = facet(value.get("brand"))
    category = facet(value.get("category"))
    country = facet(value.get("country"))
    location = facet(value.get("location"))
    url_job_id = successfactors_job_id(url)
    location_label = location[1] if location else None
    job_id = optional_text(value.get("jobReqId"))
    if (
        not job_id
        or value.get("jobReqId") != job_id
        or url_job_id != job_id
        or not title
        or not contract
        or not brand
        or not category
        or country != (SWITZERLAND_TERM_ID, "Switzerland")
        or not location_label
    ):
        raise SonovaSwitzerlandParseError(
            "Sonova jobs API returned an incomplete or non-Swiss vacancy"
        )
    return {
        "id": job_id,
        "title": title,
        "brand": brand[1],
        "brand_id": brand[0],
        "category": category[1],
        "category_id": category[0],
        "country": country[1],
        "country_id": country[0],
        "location": f"{location_label}, Switzerland",
        "location_id": location[0],
        "contract_type": contract[1],
        "contract_type_id": contract[0],
        "posted_at": None,
        "url": url,
    }


def facet(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    facet_id = optional_text(value.get("id"))
    label = optional_text(value.get("label"))
    if facet_id and facet_id.isdigit() and label:
        return facet_id, label
    return None


def comparable_title(value: Any) -> str:
    return re.sub(r"[–—−]", "-", optional_text(value) or "").casefold()


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_location: str,
) -> dict[str, Any]:
    page = Selector(page_html)
    if not page.css('[itemtype="http://schema.org/JobPosting"]').get():
        raise SonovaSwitzerlandParseError("Sonova detail page is missing JobPosting data")
    canonical = optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    company = property_attribute(page, "hiringOrganization", "content")
    location = property_attribute(page, "streetAddress", "content")
    posted_at = normalize_date(property_attribute(page, "datePosted", "content"))
    description = html_to_text(page.css(".jobdescription").get())
    internal_ids = set(INTERNAL_ID_PATTERN.findall(page_html))
    public_id = public_job_id(canonical)
    apply_urls = {
        urljoin(canonical or page_url, str(path))
        for path in page.css("a.dialogApplyBtn::attr(href)").getall()
        if public_id and is_apply_url(urljoin(canonical or page_url, str(path)), public_id)
    }
    listing_city = optional_text(expected_location.split(",", maxsplit=1)[0])
    detail_city = optional_text(location.split(",", maxsplit=1)[0]) if location else None
    if (
        comparable_title(title) != comparable_title(expected_title)
        or not canonical
        or not public_id
        or urlsplit(page_url).netloc.casefold() != PUBLIC_JOBS_HOST
        or internal_ids != {expected_job_id}
        or not company
        or not is_swiss_location(location)
        or not listing_city
        or not detail_city
        or listing_city.casefold() != detail_city.casefold()
        or not posted_at
        or not description
        or len(apply_urls) != 1
    ):
        raise SonovaSwitzerlandParseError(
            "Sonova detail page contains an incomplete or mismatched vacancy"
        )
    return {
        "id": expected_job_id,
        "public_id": public_id,
        "title": title,
        "company": company,
        "location": location,
        "url": canonical,
        "apply_url": next(iter(apply_urls)),
        "posted_at": posted_at,
        "description": description,
    }


def successfactors_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    job_ids = query.get("jobId", [])
    return (
        job_ids[0]
        if parts.scheme == "https"
        and parts.netloc.casefold() == SUCCESSFACTORS_HOST
        and parts.path == "/sfcareer/jobreqcareer"
        and query.get("company") == ["Sonova"]
        and len(job_ids) == 1
        and job_ids[0].isdigit()
        and len(query.get("locale", [])) == 1
        else None
    )


def public_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = PUBLIC_JOB_PATH.fullmatch(parts.path)
    if (
        parts.scheme == "https"
        and parts.netloc.casefold() == PUBLIC_JOBS_HOST
        and match
        and not parts.query
        and not parts.fragment
    ):
        return match.group(1)
    return None


def is_apply_url(value: str, public_id: str) -> bool:
    parts = urlsplit(value)
    match = APPLY_PATH.fullmatch(parts.path)
    return bool(
        parts.scheme == "https"
        and parts.netloc.casefold() == PUBLIC_JOBS_HOST
        and match
        and match.group(1) == public_id
        and not parts.fragment
    )


def property_attribute(page: Selector, itemprop: str, attribute: str) -> str | None:
    return optional_text(page.css(f'[itemprop="{itemprop}"]::attr({attribute})').get())


def is_swiss_location(value: Any) -> bool:
    text = optional_text(value)
    return bool(text and (text == "Switzerland" or text.endswith(", Switzerland")))


def deduplicate_sonova_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id"))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    for date_format in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%a %b %d %H:%M:%S UTC %Y",
    ):
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return None


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    return optional_multiline_text(html.unescape(re.sub(r"<[^>]+>", "", text)))


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
