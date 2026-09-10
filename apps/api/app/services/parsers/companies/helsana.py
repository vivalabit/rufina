from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient

HELSANA_JOBS_URL = (
    "https://www.helsana.ch/de/helsana-gruppe/jobs/stellenangebote.html"
)
HELSANA_CAREER_CENTER_URL = "https://jobs.helsana.ch/?lang=de"
HELSANA_COMPANY = "Helsana Versicherungen AG"
HELSANA_CAREER_CENTER_ID = "1002787"
HELSANA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
JOB_PATH_PATTERN = re.compile(
    rf"^/(offene-stellen|emplois-vacantes|posizioni-aperte)/"
    rf"([a-z0-9]+(?:-[a-z0-9]+)*)/({UUID_PATTERN})$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    rf"^/public/v1/redirect/({UUID_PATTERN})/ats/$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class HelsanaParseError(DirectCompanyRequestError):
    pass


class HelsanaJobsParser:
    """Collect Helsana's complete official paginated Career Center catalog."""

    parser_id = "helsana"

    def __init__(
        self,
        *,
        base_url: str = HELSANA_JOBS_URL,
        career_center_url: str = HELSANA_CAREER_CENTER_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.career_center_url = career_center_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(2, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with CareerHttpClient(
                headers=HELSANA_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                parent_response = client.get(self.base_url)
                parent_response.raise_for_status()
                career_center_url = parse_corporate_html(
                    parent_response.text,
                    page_url=str(parent_response.url),
                    expected_url=self.base_url,
                    expected_career_center_url=self.career_center_url,
                )
                records, pages_fetched, total = self.collect_listing_records(
                    client,
                    career_center_url=career_center_url,
                )
                self.enrich_records(client, records)
        except HelsanaParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(f"Helsana vacancy request failed: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Helsana vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_helsana_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Helsana vacancies from {total} catalog "
                f"records across {pages_fetched} page {request_label}"
            ),
        )

    def fetch_listing_page(
        self,
        client: CareerHttpClient,
        *,
        career_center_url: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        response = client.post_catalog(
            career_center_url,
            data={"offset": str(offset), "limit": str(limit), "lang": "de"},
            headers={"Referer": self.base_url},
        )
        response.raise_for_status()
        records, metadata = parse_listing_html(
            response.text,
            page_url=str(response.url),
            expected_url=career_center_url,
        )
        if metadata["offset"] != offset or metadata["limit"] != limit:
            raise HelsanaParseError(
                "Helsana pagination returned an unexpected result range"
            )
        return records, metadata

    def collect_listing_records(
        self,
        client: CareerHttpClient,
        *,
        career_center_url: str,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        page_limit = 12
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, first_metadata = self.fetch_listing_page(
                client,
                career_center_url=career_center_url,
                offset=0,
                limit=page_limit,
            )
            pages_fetched += 1
            total = first_metadata["total"]
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise HelsanaParseError(
                    "Helsana catalog changed its result count during pagination"
                )
            if total == 0:
                return [], pages_fetched, 0

            required_pages = ceil(total / page_limit)
            if required_pages > self.max_pages:
                raise HelsanaParseError(
                    f"Helsana exposes {required_pages} pages, above the configured "
                    f"limit of {self.max_pages}"
                )

            page_results = [first_records]
            for offset in range(page_limit, total, page_limit):
                records, metadata = self.fetch_listing_page(
                    client,
                    career_center_url=career_center_url,
                    offset=offset,
                    limit=page_limit,
                )
                pages_fetched += 1
                if metadata["total"] != expected_total:
                    raise HelsanaParseError(
                        "Helsana catalog changed its result count during pagination"
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
                raise HelsanaParseError(
                    "Helsana catalog changed while pages were collected"
                )

        raise HelsanaParseError(
            f"Helsana returned {len(records_by_id)} unique vacancies but declared "
            f"{expected_total or 0}"
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
                response = client.get(
                    record["url"],
                    headers={"Referer": self.career_center_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
            except (httpx.HTTPError, HelsanaParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_corporate_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_career_center_url: str,
) -> str:
    expected = canonical_corporate_url(expected_url)
    career_center = canonical_career_center_url(expected_career_center_url)
    if not expected or not career_center or canonical_corporate_url(page_url) != expected:
        raise HelsanaParseError("Helsana careers page returned an unexpected page")

    page = Selector(page_html)
    canonical = canonical_corporate_url(
        page.css('link[rel="canonical"]::attr(href)').get()
    )
    og_url = canonical_corporate_url(
        page.css('meta[property="og:url"]::attr(content)').get()
    )
    logo = optional_text(page.css("detail-page::attr(header)").get())
    widgets = page.css("hls-video[src]")
    widget_url = (
        canonical_career_center_url(
            urljoin(page_url, optional_text(widgets[0].attrib.get("src")) or "")
        )
        if len(widgets) == 1
        else None
    )
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de"
        or selector_text(page, "title") != "Offene Stellen - Helsana"
        or selector_text(page, "h1.h1") != "Offene Stellen"
        or canonical != expected
        or og_url != expected
        or len(page.css("detail-page")) != 1
        or not logo
        or "helsana-logo.svg" not in html.unescape(logo)
    ):
        raise HelsanaParseError("Helsana careers page has an unexpected identity")
    if widget_url != career_center:
        raise HelsanaParseError(
            "Helsana careers page is missing its official Career Center"
        )
    return widget_url


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if canonical_career_center_url(page_url) != canonical_career_center_url(expected_url):
        raise HelsanaParseError("Helsana Career Center returned an unexpected page")

    page = Selector(page_html)
    forms = page.css("form#careercenter-form")
    catalogs = page.css("div#jobs")
    stylesheet = (
        f"/careercenter/{HELSANA_CAREER_CENTER_ID}/assets/css/helsana.css"
    )
    stylesheet_paths = {
        urlsplit(urljoin(page_url, raw)).path
        for raw in page.css('link[rel="stylesheet"]::attr(href)').getall()
    }
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de"
        or selector_text(page, "title") != "Helsana: Career center"
        or len(forms) != 1
        or len(catalogs) != 1
        or stylesheet not in stylesheet_paths
    ):
        raise HelsanaParseError("Helsana Career Center has an unexpected identity")

    form = forms[0]
    form_offset = parse_nonnegative_int(
        form.css('input[name="offset"]::attr(value)').get()
    )
    limit = parse_positive_int(form.css('input[name="limit"]::attr(value)').get())
    language = optional_text(form.css('input[name="lang"]::attr(value)').get())
    totals = page.css("span.nrOfJobs")
    total = parse_nonnegative_int(selector_text(totals[0])) if len(totals) == 1 else None
    if form_offset is None or limit is None or language != "de" or total is None:
        raise HelsanaParseError("Helsana Career Center has invalid pagination metadata")

    active_pages = page.css("div.paging > a.page.paging.active")
    if total == 0:
        offset = 0
    elif len(active_pages) == 1:
        page_number = parse_positive_int(selector_text(active_pages[0]))
        expected_title = f"Seite {page_number}" if page_number else None
        if optional_text(active_pages[0].attrib.get("title")) != expected_title:
            raise HelsanaParseError(
                "Helsana Career Center has invalid pagination metadata"
            )
        offset = (page_number - 1) * limit if page_number else -1
    else:
        raise HelsanaParseError("Helsana Career Center has invalid pagination metadata")

    cards = catalogs[0].css(":scope > div.job")
    expected_count = min(limit, max(0, total - offset))
    if len(cards) != expected_count:
        raise HelsanaParseError("Helsana Career Center returned an incomplete page")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, card in enumerate(cards):
        links = card.css(":scope > a[href]")
        detail_url = (
            canonical_job_url(urljoin(page_url, links[0].attrib.get("href", "")))
            if len(links) == 1
            else None
        )
        job_id = job_id_from_url(detail_url)
        title = selector_text(card, "h4")
        title_attr = optional_text(links[0].attrib.get("title")) if links else None
        location = selector_text(card, "p.city")
        if (
            not detail_url
            or not urlsplit(detail_url).path.startswith("/offene-stellen/")
            or not job_id
            or not title
            or title != title_attr
            or not location
            or job_id in seen_ids
        ):
            raise HelsanaParseError(
                "Helsana Career Center contains an invalid or duplicate vacancy"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": HELSANA_COMPANY,
                "location": location,
                "employment_type": extract_workload(title),
                "url": detail_url,
                "catalog_index": offset + index,
                "listing_page_url": canonical_career_center_url(page_url),
            }
        )
    return records, {"offset": offset, "limit": limit, "total": total}


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"))
    expected_id = optional_text(expected_record.get("id"))
    if not expected_url or not expected_id or job_id_from_url(page_url) != expected_id:
        raise HelsanaParseError("Helsana vacancy returned an unexpected page")

    page = Selector(page_html)
    canonical = canonical_job_url(page.css('link[rel="canonical"]::attr(href)').get())
    postings = job_postings(page_html)
    posting = postings[0] if len(postings) == 1 else None
    title = selector_text(page, "section.title h1#addTooltip")
    location = selector_text(page, "section.title h4")
    apply_urls = {
        normalized
        for raw in page.css('a.button.apply[href]::attr(href)').getall()
        if (normalized := canonical_apply_url(raw, expected_id=expected_id))
    }
    if (
        job_id_from_url(canonical) != expected_id
        or job_slug_from_url(canonical) != job_slug_from_url(expected_url)
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != "Helsana"
        or not isinstance(posting, dict)
        or title != optional_text(expected_record.get("title"))
        or location != optional_text(expected_record.get("location"))
        or len(apply_urls) != 1
    ):
        raise HelsanaParseError("Helsana vacancy has an unexpected identity")

    schema_title = optional_text(html.unescape(optional_text(posting.get("title")) or ""))
    organization = posting.get("hiringOrganization")
    organization_name = (
        optional_text(organization.get("name")) if isinstance(organization, dict) else None
    )
    address = posting.get("jobLocation")
    address = address.get("address") if isinstance(address, dict) else None
    country = optional_text(address.get("addressCountry")) if isinstance(address, dict) else None
    description = html_to_text(optional_text(posting.get("description")))
    posted_at = optional_text(posting.get("datePosted"))
    if (
        schema_title != title
        or organization_name != HELSANA_COMPANY
        or comparable_text(country)
        not in {"ch", "schweiz", "switzerland", "suisse", "svizzera"}
        or not description
        or len(description) < 80
        or not posted_at
        or not DATE_PATTERN.fullmatch(posted_at)
    ):
        raise HelsanaParseError("Helsana vacancy contains invalid JobPosting metadata")

    salary = parse_salary(posting.get("baseSalary"))
    return {
        "title": title,
        "company": organization_name,
        "location": location,
        "apply_url": next(iter(apply_urls)),
        "posted_at": posted_at,
        "employment_type": extract_workload(title),
        "schema_employment_type": optional_text(posting.get("employmentType")),
        "valid_through": optional_text(posting.get("validThrough")),
        "description": description,
        **salary,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="helsana",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=HELSANA_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        salary=optional_text(detail.get("salary")),
        salary_min=detail.get("salary_min") if isinstance(detail.get("salary_min"), int) else None,
        salary_max=detail.get("salary_max") if isinstance(detail.get("salary_max"), int) else None,
        salary_currency=optional_text(detail.get("salary_currency")),
        salary_unit=optional_text(detail.get("salary_unit")),
        raw=dict(record),
    )


def parse_salary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    amount = value.get("value")
    if not isinstance(amount, dict):
        return {}
    minimum = parse_nonnegative_int(amount.get("minValue"))
    maximum = parse_nonnegative_int(amount.get("maxValue"))
    currency = optional_text(value.get("currency"))
    unit_value = amount.get("unitText")
    if isinstance(unit_value, list):
        unit_value = next((item for item in unit_value if isinstance(item, str)), None)
    unit = optional_text(unit_value)
    if minimum is None or maximum is None or not currency or not unit:
        return {}
    return {
        "salary": f"{minimum}–{maximum} {currency}/{unit}",
        "salary_min": minimum,
        "salary_max": maximum,
        "salary_currency": currency,
        "salary_unit": unit,
    }


def job_postings(page_html: str) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    scripts = re.findall(
        r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    for raw in scripts:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        postings.extend(
            item
            for item in values
            if isinstance(item, dict) and item.get("@type") == "JobPosting"
        )
    return postings


def canonical_corporate_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = "/de/helsana-gruppe/jobs/stellenangebote.html"
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.helsana.ch"
        or parts.path != path
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.helsana.ch", path, "", ""))


def canonical_career_center_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.helsana.ch"
        or parts.path != "/"
        or parse_qs(parts.query, keep_blank_values=True) != {"lang": ["de"]}
        or parts.fragment
    ):
        return None
    return "https://jobs.helsana.ch/?lang=de"


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.helsana.ch"
        or not JOB_PATH_PATTERN.fullmatch(path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.helsana.ch", path, "", ""))


def canonical_apply_url(value: Any, *, expected_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "ohws.prospective.ch"
        or not match
        or match.group(1).casefold() != expected_id.casefold()
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "ohws.prospective.ch", parts.path, "", ""))


def job_id_from_url(value: Any) -> str | None:
    url = canonical_job_url(value)
    if not url or not (match := JOB_PATH_PATTERN.fullmatch(urlsplit(url).path)):
        return None
    return match.group(3).casefold()


def job_slug_from_url(value: Any) -> str | None:
    url = canonical_job_url(value)
    if not url or not (match := JOB_PATH_PATTERN.fullmatch(urlsplit(url).path)):
        return None
    return match.group(2).casefold()


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    match = WORKLOAD_PATTERN.search(text) if text else None
    if not match:
        return None
    return re.sub(r"\s*[-–]\s*", "–", re.sub(r"\s+%", "%", match.group(0)))


def deduplicate_helsana_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = job_id_from_url(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def selector_text(node: Any, selector: str | None = None) -> str | None:
    target = node.css(selector) if selector else node
    return optional_text(" ".join(target.css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def parse_nonnegative_int(value: Any) -> int | None:
    text = optional_text(str(value)) if value is not None else None
    if not text or not text.isdigit():
        return None
    return int(text)


def parse_positive_int(value: Any) -> int | None:
    parsed = parse_nonnegative_int(value)
    return parsed if parsed and parsed > 0 else None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"[\s\u200b]+", " ", value).strip() or None
